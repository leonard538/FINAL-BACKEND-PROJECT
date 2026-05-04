"""
HubSpot API Service

This module provides a robust service for interacting with the HubSpot CRM API.
It handles authentication, rate limiting, pagination, error handling, and logging.

Rate Limit: 150 requests per 10 seconds (HubSpot limit)
"""

import requests
import time
import logging
from typing import Dict, List, Optional, Any, Iterator, Tuple
from datetime import datetime, timezone
from urllib.parse import urljoin
from functools import wraps
from config import get_config
from loki_logger import get_logger


class HubSpotAPIError(Exception):
    """Base exception for HubSpot API errors"""
    pass


class HubSpotAuthenticationError(HubSpotAPIError):
    """Raised when authentication fails"""
    pass


class HubSpotRateLimitError(HubSpotAPIError):
    """Raised when rate limit is exceeded"""
    pass


class HubSpotNotFoundError(HubSpotAPIError):
    """Raised when resource is not found"""
    pass


class HubSpotValidationError(HubSpotAPIError):
    """Raised when input validation fails"""
    pass


class RateLimiter:
    """Simple rate limiter to handle HubSpot's 150 requests per 10 seconds limit"""
    
    def __init__(self, max_requests: int = 150, window_seconds: int = 10):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = []
        self.logger = get_logger(__name__)
    
    def wait_if_needed(self):
        """Wait if necessary to comply with rate limits"""
        now = time.time()
        
        # Remove old requests outside the window
        self.requests = [req_time for req_time in self.requests 
                         if now - req_time < self.window_seconds]
        
        # If we've hit the limit, wait until the oldest request is outside the window
        if len(self.requests) >= self.max_requests:
            sleep_time = self.window_seconds - (now - self.requests[0]) + 0.1
            if sleep_time > 0:
                self.logger.warning(
                    "Rate limit reached, waiting for next window",
                    extra={
                        'operation': 'rate_limiter_wait',
                        'sleep_seconds': round(sleep_time, 2),
                        'requests_in_window': len(self.requests)
                    }
                )
                time.sleep(sleep_time)
        
        # Record this request
        self.requests.append(time.time())


class HubSpotAPIService:
    """
    Service for interacting with HubSpot CRM API.
    
    This service provides methods to:
    - Authenticate and validate credentials
    - Fetch deals with pagination
    - Handle rate limiting and retries
    - Log all operations
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize HubSpot API service.
        
        Args:
            config: Optional configuration dictionary. If not provided, loads from Config class.
        """
        self.config = config or get_config().get_hubspot_config()
        self.logger = get_logger(__name__)
        
        # Validate required configuration
        self._validate_config()
        
        # Initialize session with default headers
        self.session = requests.Session()
        self._set_auth_headers()
        
        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            max_requests=self.config['rate_limit'],
            window_seconds=self.config['rate_limit_window']
        )
        
        self.logger.info(
            "HubSpot API service initialized",
            extra={
                'operation': 'hubspot_service_init',
                'base_url': self.config['api_base_url'],
                'rate_limit': self.config['rate_limit'],
                'timeout': self.config['timeout']
            }
        )
    
    def _validate_config(self):
        """Validate that required configuration is present"""
        required_keys = ['api_token', 'api_base_url', 'timeout']
        missing_keys = [key for key in required_keys if not self.config.get(key)]
        
        if missing_keys:
            msg = f"Missing required HubSpot config keys: {', '.join(missing_keys)}"
            self.logger.error(msg, extra={'operation': 'config_validation_failed'})
            raise HubSpotValidationError(msg)
        
        if not self.config['api_token']:
            msg = "HubSpot API token is empty"
            self.logger.error(msg, extra={'operation': 'config_validation_failed'})
            raise HubSpotValidationError(msg)
    
    def _set_auth_headers(self):
        """Set authentication headers for all requests"""
        self.session.headers.update({
            'Authorization': f'Bearer {self.config["api_token"]}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'HubSpot-Deals-ETL-Service/1.0'
        })
    
    def validate_credentials(self) -> bool:
        """
        Validate HubSpot credentials by making a test request.
        
        Returns:
            True if credentials are valid
            
        Raises:
            HubSpotAuthenticationError: If authentication fails
        """
        self.logger.info(
            "Validating HubSpot credentials",
            extra={'operation': 'validate_credentials_start'}
        )
        
        try:
            # Make a simple GET request to validate token
            url = urljoin(self.config['api_base_url'], '/crm/v3/objects/deals?limit=1')
            
            response = self.session.get(
                url,
                timeout=self.config['timeout']
            )
            
            if response.status_code == 401:
                msg = "HubSpot authentication failed: Invalid or expired token"
                self.logger.error(
                    msg,
                    extra={
                        'operation': 'validate_credentials_failed',
                        'status_code': 401,
                        'error_type': 'authentication'
                    }
                )
                raise HubSpotAuthenticationError(msg)
            
            if response.status_code == 403:
                msg = "HubSpot authentication failed: Insufficient permissions"
                self.logger.error(
                    msg,
                    extra={
                        'operation': 'validate_credentials_failed',
                        'status_code': 403,
                        'error_type': 'authorization'
                    }
                )
                raise HubSpotAuthenticationError(msg)
            
            if response.status_code != 200:
                msg = f"HubSpot validation request failed: {response.status_code}"
                self.logger.error(
                    msg,
                    extra={
                        'operation': 'validate_credentials_failed',
                        'status_code': response.status_code,
                        'response_text': response.text[:500]
                    }
                )
                raise HubSpotAPIError(msg)
            
            self.logger.info(
                "HubSpot credentials validated successfully",
                extra={'operation': 'validate_credentials_success'}
            )
            return True
            
        except requests.RequestException as e:
            msg = f"Failed to validate HubSpot credentials: {str(e)}"
            self.logger.error(
                msg,
                extra={
                    'operation': 'validate_credentials_failed',
                    'error_type': 'request_exception',
                    'error': str(e)
                }
            )
            raise HubSpotAPIError(msg) from e
    
    def _handle_response_error(self, response: requests.Response, operation: str) -> None:
        """
        Handle error responses from HubSpot API.
        
        Args:
            response: The response object
            operation: Name of the operation for logging
            
        Raises:
            Appropriate HubSpotAPIError subclass
        """
        status_code = response.status_code
        
        try:
            error_data = response.json()
            error_msg = error_data.get('message', 'Unknown error')
            error_type = error_data.get('errorType', 'UNKNOWN')
        except:
            error_msg = response.text[:200]
            error_type = 'UNKNOWN'
        
        log_extra = {
            'operation': operation,
            'status_code': status_code,
            'error_type': error_type,
            'error_message': error_msg
        }
        
        if status_code == 401:
            self.logger.error(
                f"HubSpot authentication error: {error_msg}",
                extra={**log_extra, 'error_category': 'authentication'}
            )
            raise HubSpotAuthenticationError(error_msg)
        
        elif status_code == 403:
            self.logger.error(
                f"HubSpot authorization error: {error_msg}",
                extra={**log_extra, 'error_category': 'authorization'}
            )
            raise HubSpotAuthenticationError(error_msg)
        
        elif status_code == 404:
            self.logger.warning(
                f"HubSpot resource not found: {error_msg}",
                extra={**log_extra, 'error_category': 'not_found'}
            )
            raise HubSpotNotFoundError(error_msg)
        
        elif status_code == 429:
            self.logger.warning(
                f"HubSpot rate limit exceeded: {error_msg}",
                extra={**log_extra, 'error_category': 'rate_limit'}
            )
            raise HubSpotRateLimitError(error_msg)
        
        elif status_code == 400:
            self.logger.error(
                f"HubSpot bad request: {error_msg}",
                extra={**log_extra, 'error_category': 'validation'}
            )
            raise HubSpotValidationError(error_msg)
        
        elif status_code >= 500:
            self.logger.error(
                f"HubSpot server error: {error_msg}",
                extra={**log_extra, 'error_category': 'server_error'}
            )
            raise HubSpotAPIError(f"HubSpot server error ({status_code}): {error_msg}")
        
        else:
            self.logger.error(
                f"HubSpot API error: {error_msg}",
                extra={**log_extra, 'error_category': 'unknown'}
            )
            raise HubSpotAPIError(f"HubSpot API error ({status_code}): {error_msg}")
    
    def _make_request_with_retry(
        self,
        method: str,
        url: str,
        operation: str,
        **kwargs
    ) -> requests.Response:
        """
        Make HTTP request with retry logic and rate limiting.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            operation: Name of operation for logging
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            Response object
            
        Raises:
            HubSpotAPIError: If all retry attempts fail
        """
        # Apply rate limiting
        self.rate_limiter.wait_if_needed()
        
        max_retries = self.config['retry_attempts']
        retry_delay = self.config['retry_delay']
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                self.logger.debug(
                    f"Making {method} request",
                    extra={
                        'operation': operation,
                        'method': method,
                        'url': url,
                        'attempt': attempt + 1,
                        'max_attempts': max_retries
                    }
                )
                
                response = self.session.request(
                    method,
                    url,
                    timeout=self.config['timeout'],
                    **kwargs
                )
                
                # Check for rate limit in response
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After', retry_delay)
                    self.logger.warning(
                        "Rate limited by HubSpot, waiting before retry",
                        extra={
                            'operation': operation,
                            'attempt': attempt + 1,
                            'retry_after': retry_after
                        }
                    )
                    if attempt < max_retries - 1:
                        time.sleep(float(retry_after))
                        continue
                
                # Check for server errors (5xx) - retry these
                if 500 <= response.status_code < 600:
                    if attempt < max_retries - 1:
                        self.logger.warning(
                            "HubSpot server error, retrying",
                            extra={
                                'operation': operation,
                                'status_code': response.status_code,
                                'attempt': attempt + 1
                            }
                        )
                        time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                        continue
                
                # If status is not 2xx, handle the error
                if not response.ok:
                    self._handle_response_error(response, operation)
                
                self.logger.debug(
                    f"Request successful",
                    extra={
                        'operation': operation,
                        'status_code': response.status_code,
                        'attempt': attempt + 1
                    }
                )
                
                return response
                
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exception = e
                self.logger.warning(
                    f"Request failed: {str(e)}",
                    extra={
                        'operation': operation,
                        'error_type': type(e).__name__,
                        'attempt': attempt + 1
                    }
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                else:
                    raise
        
        # All retries exhausted
        msg = f"Failed to complete {operation} after {max_retries} attempts"
        self.logger.error(
            msg,
            extra={
                'operation': operation,
                'last_exception': str(last_exception),
                'max_attempts': max_retries
            }
        )
        raise HubSpotAPIError(msg)
    
    def get_deals(
        self,
        limit: int = 100,
        after: Optional[str] = None,
        properties: Optional[List[str]] = None,
        archived: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Retrieve deals from HubSpot.
        
        Args:
            limit: Number of deals to retrieve (1-100, default 100)
            after: Pagination cursor for the next page
            properties: List of deal properties to retrieve
            archived: Include archived deals
            **kwargs: Additional query parameters
            
        Returns:
            Dictionary with 'results' list and optional 'paging' info
            
        Raises:
            HubSpotAPIError: If request fails
        """
        # Validate limit
        if not 1 <= limit <= 100:
            raise HubSpotValidationError("Limit must be between 1 and 100")
        
        # Build query parameters
        params = {
            'limit': limit,
            'archived': 'true' if archived else 'false'
        }
        
        if after:
            params['after'] = after
        
        if properties:
            params['properties'] = ','.join(properties)
        
        # Add any additional parameters
        params.update(kwargs)
        
        url = urljoin(
            self.config['api_base_url'],
            self.config['deals_endpoint']
        )
        
        self.logger.info(
            "Fetching deals from HubSpot",
            extra={
                'operation': 'get_deals',
                'limit': limit,
                'has_after': bool(after),
                'num_properties': len(properties) if properties else 0,
                'archived': archived
            }
        )
        
        try:
            response = self._make_request_with_retry(
                'GET',
                url,
                'get_deals',
                params=params
            )
            
            data = response.json()
            
            self.logger.info(
                "Deals retrieved successfully",
                extra={
                    'operation': 'get_deals',
                    'num_results': len(data.get('results', [])),
                    'has_next_page': 'paging' in data and 'next' in data.get('paging', {})
                }
            )
            
            return data
            
        except HubSpotAPIError:
            raise
        except Exception as e:
            msg = f"Unexpected error while fetching deals: {str(e)}"
            self.logger.error(
                msg,
                extra={
                    'operation': 'get_deals',
                    'error_type': type(e).__name__,
                    'error': str(e)
                }
            )
            raise HubSpotAPIError(msg) from e
    
    def get_deals_paginated(
        self,
        properties: Optional[List[str]] = None,
        archived: bool = False,
        max_pages: Optional[int] = None,
        page_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch all deals with automatic pagination.
        
        This is a generator that yields deal batches, handling pagination automatically.
        
        Args:
            properties: List of deal properties to retrieve
            archived: Include archived deals
            max_pages: Maximum number of pages to fetch (None = all)
            page_size: Number of deals per page
            
        Yields:
            Dictionaries containing deal data and pagination info
            
        Example:
            for page in service.get_deals_paginated(properties=['dealname', 'amount']):
                for deal in page['results']:
                    process_deal(deal)
        """
        self.logger.info(
            "Starting paginated deals retrieval",
            extra={
                'operation': 'get_deals_paginated',
                'page_size': page_size,
                'max_pages': max_pages,
                'num_properties': len(properties) if properties else 0
            }
        )
        
        after = None
        page_count = 0
        
        while True:
            # Check max pages limit
            if max_pages and page_count >= max_pages:
                self.logger.info(
                    "Reached max pages limit",
                    extra={
                        'operation': 'get_deals_paginated',
                        'pages_fetched': page_count
                    }
                )
                break
            
            try:
                # Fetch page
                data = self.get_deals(
                    limit=page_size,
                    after=after,
                    properties=properties,
                    archived=archived
                )
                
                page_count += 1
                yield data
                
                # Check for next page
                paging = data.get('paging')
                if not paging or 'next' not in paging:
                    self.logger.info(
                        "No more pages available",
                        extra={
                            'operation': 'get_deals_paginated',
                            'total_pages': page_count
                        }
                    )
                    break
                
                after = paging['next'].get('after')
                if not after:
                    break
                    
            except HubSpotRateLimitError:
                self.logger.warning(
                    "Rate limited during pagination, backing off",
                    extra={
                        'operation': 'get_deals_paginated',
                        'pages_fetched': page_count
                    }
                )
                # Rate limiter will handle backoff on next request
                continue
            except HubSpotAPIError as e:
                self.logger.error(
                    f"Error during paginated retrieval: {str(e)}",
                    extra={
                        'operation': 'get_deals_paginated',
                        'pages_fetched': page_count,
                        'error': str(e)
                    }
                )
                raise
    
    def get_deal(self, deal_id: str) -> Dict[str, Any]:
        """
        Retrieve a single deal by ID.
        
        Args:
            deal_id: The HubSpot deal ID
            
        Returns:
            Deal object
            
        Raises:
            HubSpotNotFoundError: If deal not found
            HubSpotAPIError: If request fails
        """
        if not deal_id or not str(deal_id).strip():
            raise HubSpotValidationError("Deal ID is required")
        
        url = urljoin(
            self.config['api_base_url'],
            f"{self.config['deals_endpoint']}/{deal_id}"
        )
        
        self.logger.debug(
            "Fetching single deal",
            extra={
                'operation': 'get_deal',
                'deal_id': deal_id
            }
        )
        
        try:
            response = self._make_request_with_retry(
                'GET',
                url,
                'get_deal'
            )
            
            data = response.json()
            
            self.logger.debug(
                "Single deal retrieved successfully",
                extra={
                    'operation': 'get_deal',
                    'deal_id': deal_id
                }
            )
            
            return data
            
        except HubSpotNotFoundError:
            self.logger.warning(
                f"Deal not found",
                extra={
                    'operation': 'get_deal',
                    'deal_id': deal_id
                }
            )
            raise
        except HubSpotAPIError:
            raise
    
    def close(self):
        """Close the HTTP session"""
        if self.session:
            self.session.close()
            self.logger.debug(
                "HubSpot API service session closed",
                extra={'operation': 'close_session'}
            )
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
        return False
