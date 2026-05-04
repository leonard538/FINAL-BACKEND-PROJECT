"""
Example usage of HubSpotAPIService

This script demonstrates how to use the HubSpot API service for common operations.
Run this with proper .env configuration to test against your HubSpot Developer Account.
"""

import sys
import logging
from config import get_config
from services.hubspot_api_service import HubSpotAPIService, HubSpotAPIError
from loki_logger import get_logger


def setup_logging():
    """Setup logging for examples"""
    logger = get_logger(__name__)
    return logger


def example_validate_credentials():
    """Example: Validate HubSpot credentials"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Validate HubSpot Credentials")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        service = HubSpotAPIService()
        
        print("Validating credentials...")
        is_valid = service.validate_credentials()
        
        if is_valid:
            print("✓ Credentials validated successfully!")
            logger.info("Credentials validated", extra={'example': 'validate_credentials'})
        
        service.close()
        
    except HubSpotAPIError as e:
        print(f"✗ Credential validation failed: {e}")
        logger.error(f"Validation failed: {e}", extra={'example': 'validate_credentials'})


def example_get_deals_single_page():
    """Example: Fetch a single page of deals"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Fetch Single Page of Deals")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        service = HubSpotAPIService()
        
        print("Fetching first page of deals...")
        data = service.get_deals(
            limit=5,
            properties=['dealname', 'amount', 'dealstage', 'closedate']
        )
        
        print(f"✓ Retrieved {len(data['results'])} deals")
        
        for deal in data['results']:
            deal_id = deal.get('id')
            deal_name = deal.get('properties', {}).get('dealname', 'N/A')
            amount = deal.get('properties', {}).get('amount', 'N/A')
            print(f"  - Deal {deal_id}: {deal_name} (Amount: ${amount})")
        
        if 'paging' in data and 'next' in data['paging']:
            print(f"✓ Next page available (cursor: {data['paging']['next']['after']})")
        else:
            print("✓ No more pages available")
        
        logger.info("Deals fetched", extra={'example': 'get_deals', 'count': len(data['results'])})
        service.close()
        
    except HubSpotAPIError as e:
        print(f"✗ Failed to fetch deals: {e}")
        logger.error(f"Fetch failed: {e}", extra={'example': 'get_deals'})


def example_get_deals_paginated():
    """Example: Fetch all deals with automatic pagination"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Fetch All Deals with Pagination")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        service = HubSpotAPIService()
        
        print("Fetching all deals with pagination (limit: 3 pages)...")
        total_deals = 0
        page_count = 0
        
        for page in service.get_deals_paginated(
            properties=['dealname', 'amount', 'dealstage'],
            max_pages=3,
            page_size=10
        ):
            page_count += 1
            deals = page.get('results', [])
            total_deals += len(deals)
            
            print(f"  Page {page_count}: {len(deals)} deals")
            for deal in deals[:2]:  # Show first 2 deals per page
                deal_name = deal.get('properties', {}).get('dealname', 'N/A')
                print(f"    - {deal_name}")
        
        print(f"✓ Retrieved {total_deals} deals across {page_count} pages")
        logger.info(
            "Paginated fetch completed",
            extra={'example': 'get_deals_paginated', 'total': total_deals, 'pages': page_count}
        )
        service.close()
        
    except HubSpotAPIError as e:
        print(f"✗ Paginated fetch failed: {e}")
        logger.error(f"Paginated fetch failed: {e}", extra={'example': 'get_deals_paginated'})


def example_get_single_deal():
    """Example: Fetch a single deal by ID"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Fetch Single Deal by ID")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        service = HubSpotAPIService()
        
        # First, get a deal ID from the first page
        print("Getting a deal ID to fetch...")
        data = service.get_deals(limit=1)
        
        if not data.get('results'):
            print("✗ No deals available to fetch")
            service.close()
            return
        
        deal_id = data['results'][0]['id']
        print(f"Fetching deal with ID: {deal_id}...")
        
        deal = service.get_deal(deal_id)
        
        deal_name = deal.get('properties', {}).get('dealname', 'N/A')
        amount = deal.get('properties', {}).get('amount', 'N/A')
        stage = deal.get('properties', {}).get('dealstage', 'N/A')
        
        print(f"✓ Deal retrieved successfully")
        print(f"  Name: {deal_name}")
        print(f"  Amount: ${amount}")
        print(f"  Stage: {stage}")
        
        logger.info("Single deal fetched", extra={'example': 'get_deal', 'deal_id': deal_id})
        service.close()
        
    except HubSpotAPIError as e:
        print(f"✗ Failed to fetch single deal: {e}")
        logger.error(f"Single deal fetch failed: {e}", extra={'example': 'get_deal'})


def example_error_handling():
    """Example: Error handling"""
    print("\n" + "="*60)
    print("EXAMPLE 5: Error Handling")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        service = HubSpotAPIService()
        
        print("Testing error handling with invalid deal ID...")
        try:
            deal = service.get_deal("999999999")
        except Exception as e:
            print(f"✓ Expected error caught: {type(e).__name__}: {e}")
            logger.info("Error handling verified", extra={'example': 'error_handling'})
        
        print("\nTesting validation error with invalid limit...")
        try:
            data = service.get_deals(limit=1000)
        except Exception as e:
            print(f"✓ Expected error caught: {type(e).__name__}: {e}")
            logger.info("Validation error caught", extra={'example': 'error_handling'})
        
        service.close()
        
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}", extra={'example': 'error_handling'})


def example_using_context_manager():
    """Example: Using the service as a context manager"""
    print("\n" + "="*60)
    print("EXAMPLE 6: Using Context Manager")
    print("="*60)
    
    logger = get_logger(__name__)
    
    try:
        print("Using HubSpot service with context manager...")
        
        with HubSpotAPIService() as service:
            # Validate credentials
            service.validate_credentials()
            print("✓ Credentials validated")
            
            # Fetch deals
            data = service.get_deals(limit=3, properties=['dealname'])
            print(f"✓ Retrieved {len(data['results'])} deals")
        
        print("✓ Service closed automatically")
        logger.info("Context manager usage successful", extra={'example': 'context_manager'})
        
    except HubSpotAPIError as e:
        print(f"✗ Context manager example failed: {e}")
        logger.error(f"Context manager failed: {e}", extra={'example': 'context_manager'})


def main():
    """Run all examples"""
    print("\n" + "="*60)
    print("HubSpot API Service Examples")
    print("="*60)
    
    config = get_config()
    
    print(f"\nConfiguration:")
    print(f"  HubSpot API Base URL: {config.HUBSPOT_API_BASE_URL}")
    print(f"  HubSpot Pipeline: {config.HUBSPOT_PIPELINE_NAME}")
    print(f"  Database Schema: {config.DB_SCHEMA}")
    print(f"  Rate Limit: {config.HUBSPOT_RATE_LIMIT} requests per {config.HUBSPOT_RATE_LIMIT_WINDOW}s")
    
    # Check if token is configured
    if not config.HUBSPOT_PRIVATE_APP_TOKEN:
        print("\n⚠ WARNING: HUBSPOT_PRIVATE_APP_TOKEN not configured in .env")
        print("Please set HUBSPOT_PRIVATE_APP_TOKEN in your .env file to run examples.")
        return
    
    # Run examples
    example_validate_credentials()
    example_get_deals_single_page()
    example_get_deals_paginated()
    example_get_single_deal()
    example_error_handling()
    example_using_context_manager()
    
    print("\n" + "="*60)
    print("All examples completed!")
    print("="*60 + "\n")


if __name__ == '__main__':
    main()
