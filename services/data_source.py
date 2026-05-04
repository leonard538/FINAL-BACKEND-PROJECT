import dlt
from typing import Dict, List, Any, Iterator, Optional, Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from config import get_config
from loki_logger import get_logger
from .hubspot_api_service import HubSpotAPIService


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_hubspot_datetime(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None

    # HubSpot may return ISO strings or millisecond epoch values.
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat()

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return datetime.fromtimestamp(float(stripped) / 1000.0, tz=timezone.utc).isoformat()

        try:
            if stripped.endswith("Z"):
                stripped = stripped[:-1] + "+00:00"
            return datetime.fromisoformat(stripped).isoformat()
        except ValueError:
            return None

    return None


def _transform_deal_record(
    record: Dict[str, Any],
    scan_id: str,
    organization_id: str,
    page_number: int,
    source_cursor: Optional[str],
) -> Dict[str, Any]:
    properties = record.get("properties") or {}

    transformed = {
        # Primary and source identifiers
        "id": str(record.get("id")),
        "hs_object_id": str(record.get("id")),

        # Flattened business fields for easy querying in warehouse
        "deal_name": properties.get("dealname"),
        "deal_stage": properties.get("dealstage"),
        "pipeline": properties.get("pipeline"),
        "amount": _to_float(properties.get("amount")),
        "close_date": _parse_hubspot_datetime(properties.get("closedate")),
        "hs_createdate": _parse_hubspot_datetime(properties.get("createdate")),
        "hs_lastmodifieddate": _parse_hubspot_datetime(properties.get("hs_lastmodifieddate")),

        # Raw payload for traceability and future backfills
        "properties": properties,

        # HubSpot object metadata
        "created_at": _parse_hubspot_datetime(record.get("createdAt")),
        "updated_at": _parse_hubspot_datetime(record.get("updatedAt")),
        "archived": _to_bool(record.get("archived", False)),

        # Extraction metadata
        "_extracted_at": datetime.now(timezone.utc).isoformat(),
        "_scan_id": scan_id,
        "_organization_id": organization_id,
        "_page_number": page_number,
        "_source_service": "hubspot_deals",
        "_source_cursor": source_cursor,
    }

    return transformed

def create_data_source(
    job_config: Dict[str, Any],
    auth_config: Dict[str, Any],
    filters: Dict[str, Any],
    checkpoint_callback: Optional[Callable] = None,
    check_cancel_callback: Optional[Callable] = None,
    check_pause_callback: Optional[Callable] = None,  # Add pause callback parameter
    resume_from: Optional[Dict[str, Any]] = None,
):
    """
    Create DLT source function for HubSpot deals extraction with checkpoint support.
    """
    logger = get_logger(__name__)

    access_token = (
        auth_config.get("accessToken")
        or auth_config.get("access_token")
        or auth_config.get("token")
    )
    if not access_token:
        raise ValueError("No access token found in auth configuration")

    app_config = get_config()
    hubspot_config = app_config.get_hubspot_config()
    hubspot_config["api_token"] = access_token
    api_service = HubSpotAPIService(config=hubspot_config)

    organization_id = job_config.get("organizationId")
    if not organization_id:
        raise ValueError("No organization ID found in job configuration")

    logger.info(
        "Starting HubSpot deals data extraction",
        extra={
            "organization_id": organization_id,
            "filters": filters,
            "job_config": job_config,
        },
    )

    @dlt.resource(name="hubspot_deals", write_disposition="merge", primary_key="id")
    def get_hubspot_deals() -> Iterator[Dict[str, Any]]:
        """
        Extract deals from HubSpot using cursor-based pagination.
        """

        # Initialize state
        if resume_from:
            after = resume_from.get("cursor")
            page_count = resume_from.get("page_number", 0)
            total_records = resume_from.get("records_processed", 0)
            logger.info(
                "Resuming HubSpot extraction",
                extra={
                    "operation": "data_extraction",
                    "page_number": page_count + 1,
                    "total_processed": total_records,
                },
            )
        else:
            after = None
            page_count = 0
            total_records = 0
            logger.info(
                "Starting fresh HubSpot extraction",
                extra={"operation": "data_extraction", "source": "hubspot_deals"},
            )

        # Configuration
        checkpoint_interval = int(filters.get("checkpoint_interval", 10))
        page_size = int(filters.get("limit", 100))
        page_size = max(1, min(100, page_size))
        max_pages = int(filters.get("max_pages", 1000))
        cancel_check_interval = 1
        pause_check_interval = 1
        job_id = filters.get("scan_id") or job_config.get("scanId") or "unknown"
        requested_properties = filters.get("properties") or []
        pipeline_name = filters.get("pipeline")
        include_archived = _to_bool(filters.get("archived", False))

        if not isinstance(requested_properties, list):
            requested_properties = []

        while page_count < max_pages:
            try:
                # Check for cancellation
                if page_count % cancel_check_interval == 0:
                    if check_cancel_callback and check_cancel_callback(job_id):
                        logger.info(
                            "Extraction cancelled by user",
                            extra={
                                "operation": "data_extraction",
                                "job_id": job_id,
                                "page_number": page_count + 1,
                                "total_processed": total_records,
                            },
                        )

                        # Save cancellation checkpoint
                        if checkpoint_callback:
                            try:
                                cancel_checkpoint = {
                                    "phase": "main_data_cancelled",
                                    "records_processed": total_records,
                                    "cursor": after,
                                    "page_number": page_count,
                                    "batch_size": page_size,
                                    "checkpoint_data": {
                                        "cancellation_reason": "user_requested",
                                        "cancelled_at_page": page_count,
                                        "service": "hubspot_deals",
                                    },
                                }
                                checkpoint_callback(job_id, cancel_checkpoint)
                            except Exception as e:
                                logger.warning(
                                    "Failed to save cancellation checkpoint",
                                    extra={"job_id": job_id, "error": str(e)},
                                )
                        break

                # Check for pause request
                if page_count % pause_check_interval == 0:
                    if check_pause_callback and check_pause_callback(job_id):
                        logger.info(
                            "Extraction paused by user",
                            extra={
                                "operation": "data_extraction",
                                "job_id": job_id,
                                "page_number": page_count + 1,
                                "total_processed": total_records,
                            },
                        )

                        # Save pause checkpoint - this allows resuming from exact position
                        if checkpoint_callback:
                            try:
                                pause_checkpoint = {
                                    "phase": "main_data_paused",
                                    "records_processed": total_records,
                                    "cursor": after,
                                    "page_number": page_count,
                                    "batch_size": page_size,
                                    "checkpoint_data": {
                                        "pause_reason": "user_requested",
                                        "paused_at_page": page_count,
                                        "paused_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                        "service": "hubspot_deals",
                                    },
                                }
                                checkpoint_callback(job_id, pause_checkpoint)

                                logger.info(
                                    "Pause checkpoint saved",
                                    extra={
                                        "operation": "data_extraction",
                                        "job_id": job_id,
                                        "page_number": page_count,
                                        "total_processed": total_records,
                                    },
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to save pause checkpoint",
                                    extra={"job_id": job_id, "error": str(e)},
                                )

                        # Exit gracefully - this allows the job to be resumed later
                        break

                logger.debug(
                    "Fetching data page",
                    extra={
                        "operation": "data_extraction",
                        "job_id": job_id,
                        "page_number": page_count + 1,
                        "after": after,
                    },
                )

                data = api_service.get_deals(
                    limit=page_size,
                    after=after,
                    properties=requested_properties if requested_properties else None,
                    archived=include_archived,
                )

                page_records = 0
                last_processed_id = None

                deals = data.get("results") or []
                if deals:
                    for record in deals:
                        # Check for pause/cancel even within record processing for faster response
                        if check_pause_callback and check_pause_callback(job_id):
                            logger.info(
                                "Extraction paused mid-page",
                                extra={
                                    "operation": "data_extraction",
                                    "job_id": job_id,
                                    "page_number": page_count + 1,
                                    "records_in_page": page_records,
                                    "total_processed": total_records + page_records,
                                },
                            )

                            # Save mid-page pause checkpoint
                            if checkpoint_callback:
                                try:
                                    mid_page_checkpoint = {
                                        "phase": "main_data_paused_mid_page",
                                        "records_processed": total_records
                                        + page_records,
                                        "cursor": after,
                                        "page_number": page_count,
                                        "batch_size": page_size,
                                        "checkpoint_data": {
                                            "pause_reason": "user_requested_mid_page",
                                            "paused_at_page": page_count,
                                            "records_completed_in_page": page_records,
                                            "paused_at": datetime.now(
                                                timezone.utc
                                            ).isoformat(),
                                            "service": "hubspot_deals",
                                        },
                                    }
                                    checkpoint_callback(job_id, mid_page_checkpoint)
                                except Exception as e:
                                    logger.warning(
                                        "Failed to save mid-page pause checkpoint",
                                        extra={"job_id": job_id, "error": str(e)},
                                    )
                            return  # Exit the generator

                        transformed = _transform_deal_record(
                            record=record,
                            scan_id=job_id,
                            organization_id=organization_id,
                            page_number=page_count + 1,
                            source_cursor=after,
                        )

                        # Optional pipeline filter from job/filter context.
                        if pipeline_name and transformed.get("pipeline") not in {None, pipeline_name}:
                            continue

                        last_processed_id = transformed.get("id")
                        yield transformed
                        page_records += 1

                # Update counters
                total_records += page_records
                page_count += 1

                next_cursor = None
                if data.get("paging") and data["paging"].get("next"):
                    next_cursor = data["paging"]["next"].get("after")

                # Save checkpoint periodically
                if checkpoint_callback and page_count % checkpoint_interval == 0:
                    try:
                        checkpoint_data = {
                            "phase": "main_data",
                            "records_processed": total_records,
                            "cursor": next_cursor,
                            "page_number": page_count,
                            "batch_size": page_size,
                            "last_processed_id": last_processed_id,
                            "checkpoint_data": {
                                "pages_processed": page_count,
                                "last_page_records": page_records,
                                "service": "hubspot_deals",
                                "pipeline_name": pipeline_name,
                            },
                        }

                        checkpoint_callback(job_id, checkpoint_data)

                        logger.debug(
                            "Checkpoint saved",
                            extra={
                                "operation": "data_extraction",
                                "job_id": job_id,
                                "page_number": page_count,
                                "total_records": total_records,
                            },
                        )

                    except Exception as checkpoint_error:
                        logger.warning(
                            "Failed to save checkpoint",
                            extra={
                                "operation": "data_extraction",
                                "job_id": job_id,
                                "error": str(checkpoint_error),
                            },
                        )

                # HubSpot pagination is cursor-based via paging.next.after
                if next_cursor:
                    after = next_cursor
                else:
                    # Final checkpoint on completion
                    if checkpoint_callback:
                        try:
                            final_checkpoint = {
                                "phase": "main_data_completed",
                                "records_processed": total_records,
                                "cursor": None,
                                "page_number": page_count,
                                "batch_size": page_size,
                                "checkpoint_data": {
                                    "completion_status": "success",
                                    "total_pages": page_count,
                                    "final_total": total_records,
                                    "service": "hubspot_deals",
                                },
                            }
                            checkpoint_callback(job_id, final_checkpoint)
                        except Exception as e:
                            logger.warning(
                                "Failed to save final checkpoint",
                                extra={"job_id": job_id, "error": str(e)},
                            )

                    logger.info(
                        "Data extraction completed",
                        extra={
                            "operation": "data_extraction",
                            "job_id": job_id,
                            "total_records": total_records,
                            "total_pages": page_count,
                        },
                    )
                    break

            except Exception as e:
                logger.error(
                    "Error fetching data page",
                    extra={
                        "operation": "data_extraction",
                        "job_id": job_id,
                        "page_number": page_count + 1,
                        "error": str(e),
                    },
                    exc_info=True,
                )

                # Save error checkpoint for debugging
                if checkpoint_callback:
                    try:
                        error_checkpoint = {
                            "phase": "main_data_error",
                            "records_processed": total_records,
                            "cursor": after,
                            "page_number": page_count,
                            "batch_size": page_size,
                            "checkpoint_data": {
                                "error": str(e),
                                "error_page": page_count + 1,
                                "recovery_cursor": after,
                                "service": "hubspot_deals",
                            },
                        }
                        checkpoint_callback(job_id, error_checkpoint)
                    except:
                        pass

                raise e

    return [get_hubspot_deals]