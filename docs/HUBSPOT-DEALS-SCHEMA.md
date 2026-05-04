HubSpot Deals — PostgreSQL Schema

Purpose
- Store HubSpot `deals` for ETL and analytics in a multi-tenant Postgres schema.

Type mapping
- string/text → TEXT
- enum/dropdown → VARCHAR(255)
- number/decimal → NUMERIC(18,4)
- integer → INTEGER
- boolean → BOOLEAN
- date/datetime → TIMESTAMP WITH TIME ZONE
- currency → NUMERIC(18,2)
- object/array → JSONB

ETL metadata (required)
- _extracted_at TIMESTAMPTZ NOT NULL
- _scan_id UUID
- _tenant_id UUID NOT NULL
- _ingested_at TIMESTAMPTZ DEFAULT now()
- _etl_status VARCHAR(32)

CREATE TABLE (recommended)
```sql
CREATE TABLE hubspot_deals (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hubspot_id        VARCHAR NOT NULL,
  _tenant_id        UUID NOT NULL,
  dealname          TEXT,
  dealstage         VARCHAR(128),
  pipeline          VARCHAR(128),
  amount            NUMERIC(18,2),
  closedate         TIMESTAMPTZ,
  created_at        TIMESTAMPTZ,
  updated_at        TIMESTAMPTZ,
  archived          BOOLEAN DEFAULT FALSE,
  properties        JSONB DEFAULT '{}'::JSONB,
  _extracted_at     TIMESTAMPTZ NOT NULL,
  _scan_id          UUID,
  _ingested_at      TIMESTAMPTZ DEFAULT now(),
  _etl_status       VARCHAR(32),
  CONSTRAINT uk_tenant_hs UNIQUE (_tenant_id, hubspot_id)
);
```

Indexes
```sql
CREATE INDEX idx_deals_tenant_created ON hubspot_deals (_tenant_id, created_at DESC);
CREATE INDEX idx_deals_tenant_stage ON hubspot_deals (_tenant_id, dealstage);
CREATE INDEX idx_deals_tenant_hsid ON hubspot_deals (_tenant_id, hubspot_id);
CREATE INDEX idx_deals_tenant_closedate ON hubspot_deals (_tenant_id, closedate);
CREATE INDEX idx_deals_properties_gin ON hubspot_deals USING GIN (properties jsonb_path_ops);
CREATE INDEX idx_deals_active_tenant_stage ON hubspot_deals (_tenant_id, dealstage) WHERE archived = false;
```

Upsert pattern
```sql
INSERT INTO hubspot_deals (hubspot_id, _tenant_id, dealname, dealstage, pipeline, amount, closedate, created_at, updated_at, archived, properties, _extracted_at, _scan_id)
VALUES (...) 
ON CONFLICT (hubspot_id) DO UPDATE
SET dealname = EXCLUDED.dealname,
    dealstage = EXCLUDED.dealstage,
    pipeline = EXCLUDED.pipeline,
    amount = EXCLUDED.amount,
    closedate = EXCLUDED.closedate,
    updated_at = EXCLUDED.updated_at,
    archived = EXCLUDED.archived,
    properties = EXCLUDED.properties || hubspot_deals.properties,
    _extracted_at = EXCLUDED._extracted_at,
    _ingested_at = now();
```

Multi-tenant isolation
- Row-level (recommended): single table + `_tenant_id` column. Enforce in app queries or enable RLS.
- Schema-per-tenant: separate schemas per tenant (operational overhead).
- DB-per-tenant: full isolation for strict compliance.

RLS example
```sql
ALTER TABLE hubspot_deals ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON hubspot_deals
  USING (_tenant_id = current_setting('app.current_tenant')::UUID);
```
Set `app.current_tenant` in session (connection) before queries.

Staging + bulk load pattern
1. COPY to `hubspot_deals_staging` (same columns, no indexes)
2. Run single transaction: upsert from staging to `hubspot_deals` using `ON CONFLICT` or `MERGE` (PG15+)
3. Truncate staging

Property metadata
- Optional table `hubspot_deal_properties` to store definitions from `/crm/v3/properties/deals`.

Best practices
- Flatten only frequently queried properties; keep the rest in `properties` JSONB.
- Always include `_tenant_id` in WHERE clauses or enable RLS.
- Use GIN indexes for JSONB queries.
- Batch and upsert in transactions; use COPY for high volume.

Next steps (optional)
- Generate mapping SQL for a chosen subset of HubSpot properties (e.g., dealname, amount, pipeline, dealstage, closedate).
- Provide a sample staging-to-target upsert script.
- Add `CREATE SCHEMA` + `GRANT` for tenant bootstrap.
