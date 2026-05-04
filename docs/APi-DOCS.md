# HubSpot Deals API Documentation

## Table of Contents
1. Overview
2. Authentication
3. Base URLs
4. Deals Endpoint
5. Query Parameters
6. Response Examples
7. Rate Limits
8. Error Handling
9. Deal Properties

## Overview

This generated service syncs deal data from HubSpot CRM using the Deals v3 API. The core object being extracted is the deal record exposed by HubSpot at `/crm/v3/objects/deals`.

### API Version
- Version: CRM API v3
- Content Type: `application/json`
- Base object path: `/crm/v3/objects/deals`

### What This Integration Does
- Reads deal records from HubSpot CRM
- Supports pagination using HubSpot cursor-based paging
- Pulls selected deal properties for downstream ETL processing
- Preserves HubSpot record identifiers for incremental syncs

## Authentication

This integration uses a HubSpot private app access token.

### Authentication Method
- Authorization header with Bearer token
- Token value comes from a HubSpot private app

### Required Permissions
Grant the private app the CRM scopes needed to read deals and deal properties, typically:
- `crm.objects.deals.read`
- `crm.schemas.deals.read` if property metadata is needed

### Authentication Headers
```http
Authorization: Bearer <PRIVATE_APP_ACCESS_TOKEN>
Content-Type: application/json
```

## Base URLs

### HubSpot API Base
```text
https://api.hubapi.com
```

### Deals Endpoint
```text
GET https://api.hubapi.com/crm/v3/objects/deals
```

## Deals Endpoint

### Retrieve Deals

**GET** `/crm/v3/objects/deals`

Returns a paginated list of deal records.

### Retrieve a Single Deal

**GET** `/crm/v3/objects/deals/{dealId}`

Returns a single deal by record ID.

### Endpoint Notes
- `archived=false` is the default behavior unless you explicitly request archived records.
- `after` is the HubSpot paging cursor returned in the `paging.next.after` field.
- `properties` controls which deal fields are returned.

## Query Parameters

The following query parameters are supported for list retrieval.

| Parameter | Type | Description |
|---|---|---|
| `limit` | integer | Maximum number of records to return in one page. |
| `after` | string | Paging cursor for the next page of results. |
| `properties` | string | Comma-separated list of deal properties to include in the response. |
| `archived` | boolean | When `true`, returns archived deal records. Defaults to `false`. |

### Example Request
```http
GET /crm/v3/objects/deals?limit=100&after=12345&properties=dealname,dealstage,pipeline,amount,closedate&archived=false
Authorization: Bearer <PRIVATE_APP_ACCESS_TOKEN>
```

## Response Examples

### Success Response
```json
{
  "results": [
    {
      "id": "123456789",
      "properties": {
        "dealname": "Acme Renewal",
        "dealstage": "contractsent",
        "pipeline": "default",
        "amount": "1500.00",
        "closedate": "2026-05-31T00:00:00Z",
        "hs_lastmodifieddate": "2026-05-04T10:30:00Z"
      },
      "createdAt": "2026-05-01T09:00:00Z",
      "updatedAt": "2026-05-04T10:30:00Z",
      "archived": false
    }
  ],
  "paging": {
    "next": {
      "after": "123456790"
    }
  }
}
```

### Empty Page Response
```json
{
  "results": [],
  "paging": null
}
```

### Common Response Fields
- `results`: array of deal records
- `id`: HubSpot record ID
- `properties`: selected property values for each deal
- `createdAt`: record creation timestamp
- `updatedAt`: record update timestamp
- `archived`: archive state of the record
- `paging.next.after`: cursor for the next page

## Rate Limits

HubSpot enforces app-level limits. For privately distributed apps and private app access, the commonly documented limits are:
- Free and Starter: 100 requests per 10 seconds per app
- Professional: 190 requests per 10 seconds per app
- Enterprise: 190 requests per 10 seconds per app

Daily limits also apply at the HubSpot account level, and the exact cap depends on the subscription tier.

### Rate Limit Headers
- `X-HubSpot-RateLimit-Daily`
- `X-HubSpot-RateLimit-Daily-Remaining`
- `X-HubSpot-RateLimit-Interval-Milliseconds`
- `X-HubSpot-RateLimit-Max`
- `X-HubSpot-RateLimit-Remaining`

### Rate Limit Behavior
- `429` is returned when the app exceeds the allowed rate.
- Search endpoints do not include the standard rate limit headers.
- A burst of requests can also trigger transient `5xx` errors, which should be retried with backoff.

## Error Handling

Handle HubSpot responses by status code and body content.

### Typical Error Codes
- `400 Bad Request`: invalid query parameters or malformed request
- `401 Unauthorized`: missing, expired, or invalid access token
- `403 Forbidden`: token lacks required CRM scopes
- `404 Not Found`: requested deal ID does not exist
- `429 Too Many Requests`: rate limit exceeded
- `5xx Server Error`: transient HubSpot service issue

### Example Error Response
```json
{
  "status": "error",
  "message": "You have reached your daily limit.",
  "errorType": "RATE_LIMIT",
  "correlationId": "c033cdaa-2c40-4a64-ae48-b4cec88dad24",
  "policyName": "DAILY",
  "requestId": "3d3e35b7-0dae-4b9f-a6e3-9c230cbcf8dd"
}
```

### Recommended Handling
- Retry `429` and `5xx` responses with exponential backoff.
- Refresh or replace the private app token if `401` responses start appearing.
- Log the `correlationId` and `requestId` for HubSpot support debugging.

## Deal Properties

HubSpot exposes many default deal properties. The list below is organized by the categories shown in HubSpot’s default deal properties documentation.

### Analytics History
- Latest Traffic Source
- Latest Traffic Source drill-down 1
- Latest Traffic Source drill-down 2
- Latest Traffic Source Date
- Original Traffic Source drill-down 1
- Original Traffic Source drill-down 2
- Original Traffic Source

### Calculated Deal Information
- Average Deal Owner Duration In Current Stage
- Is Stalled After Timestamp

### Deal Activity
- Campaign of last booking in meetings tool
- Closed lost reason
- Closed won reason
- Date of last meeting booked in meetings tool
- Deal stage
- Is closed lost
- Is Closed Won
- Last activity date
- Last contacted
- Last modified date
- Latest Approval Status
- Medium of last booking in meetings tool
- Next activity date
- Number of Sales Activities
- Number of times contacted
- Owner assigned date
- Pipeline
- Source of last booking in meetings tool

### Deal Information
- Brands
- Close date
- Create date
- Created by user ID
- Deal collaborator
- Deal description
- Deal name
- Deal owner
- Deal probability
- Deal score
- Deal split added
- Deal tags
- Deal type
- Forecast amount
- Forecast category
- Forecast probability
- HubSpot team
- Merged Deal IDs
- Next Meeting ID
- Next Meeting Name
- Next Meeting Start Time
- Next step
- Number of associated contacts
- Priority
- Record ID
- Record Source
- Record Source Detail 1
- Record Source Detail 2
- Record Source Detail 3
- Shared teams
- Shared users
- Updated by user ID
- Weighted amount

### Deal Revenue
- Amount
- Amount in company currency
- Annual contract value (ACV)
- Annual recurring revenue (ARR)
- Currency
- Exchange rate
- Monthly recurring revenue (MRR)
- Total contract value (TCV)

### Deal Stage Properties
- Date entered current stage
- Date entered [stage ID]
- Date exited [stage ID]
- Latest time in [stage ID]
- Cumulative time in [stage ID]
- Time in current stage

### Recurring Revenue Information
- Recurring revenue amount
- Recurring revenue deal type
- Recurring revenue date
- Recurring revenue inactive reason

### Custom Report Deal Properties
- Deal Status
- Closed amount
- Days to close

## Notes

- When you need the full, account-specific property list, call the properties endpoint at `/crm/v3/properties/deals`.
- When retrieving deal data in ETL jobs, always request only the properties you need.
- Use the `after` cursor for incremental pagination instead of offset-based paging.
