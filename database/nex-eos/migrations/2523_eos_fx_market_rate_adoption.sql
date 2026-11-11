BEGIN;

CREATE TABLE IF NOT EXISTS eos_fx_market_rate (
    market_rate_id UUID NOT NULL,
    source_provider_id VARCHAR(128) NOT NULL,
    source_record_id VARCHAR(256) NOT NULL,
    publication_issue VARCHAR(64) NOT NULL,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    quote_unit NUMERIC(18,6) NOT NULL,
    published_rate NUMERIC(28,12) NOT NULL,
    rate_date DATE NOT NULL,
    rate_as_of TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    is_final BOOLEAN NOT NULL,
    source_uri VARCHAR(2048) NOT NULL,
    source_sha256 VARCHAR(71) NOT NULL,
    source_timezone VARCHAR(64) NOT NULL,
    provenance_json JSONB NOT NULL,
    market_rate_hash VARCHAR(71) NOT NULL,
    market_admitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_fx_market_rate PRIMARY KEY (market_rate_id),
    CONSTRAINT ux_eos_fx_market_rate_source UNIQUE (
        source_provider_id, source_record_id, publication_issue,
        base_currency, quote_currency, rate_date
    ),
    CONSTRAINT ux_eos_fx_market_rate_hash UNIQUE (market_rate_hash),
    CONSTRAINT ck_eos_fx_market_rate_pair CHECK (
        base_currency = UPPER(base_currency)
        AND quote_currency = UPPER(quote_currency)
        AND base_currency <> quote_currency
    ),
    CONSTRAINT ck_eos_fx_market_rate_values CHECK (
        quote_unit > 0 AND published_rate > 0
    ),
    CONSTRAINT ck_eos_fx_market_rate_hashes CHECK (
        source_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND market_rate_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_fx_market_rate_provenance CHECK (
        jsonb_typeof(provenance_json) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_fx_market_rate_lookup
    ON eos_fx_market_rate (
        source_provider_id, base_currency, quote_currency,
        rate_date DESC, published_at DESC
    );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM eos_fx_rate_snapshot
        GROUP BY
            source_provider_id, source_record_id, publication_issue,
            base_currency, quote_currency, rate_date
        HAVING COUNT(DISTINCT jsonb_build_array(
            quote_unit::TEXT,
            published_rate::TEXT,
            rate_as_of::TEXT,
            published_at::TEXT,
            is_final,
            source_uri,
            source_sha256,
            source_timezone
        )) > 1
    ) THEN
        RAISE EXCEPTION
            'conflicting tenant FX source observations prevent global promotion'
            USING ERRCODE = '23505';
    END IF;
END;
$$;

INSERT INTO eos_fx_market_rate (
    market_rate_id,
    source_provider_id,
    source_record_id,
    publication_issue,
    base_currency,
    quote_currency,
    quote_unit,
    published_rate,
    rate_date,
    rate_as_of,
    published_at,
    is_final,
    source_uri,
    source_sha256,
    source_timezone,
    provenance_json,
    market_rate_hash,
    market_admitted_at
)
SELECT DISTINCT ON (
    source_provider_id, source_record_id, publication_issue,
    base_currency, quote_currency, rate_date
)
    rate_snapshot_id,
    source_provider_id,
    source_record_id,
    publication_issue,
    base_currency,
    quote_currency,
    quote_unit,
    published_rate,
    rate_date,
    rate_as_of,
    published_at,
    is_final,
    source_uri,
    source_sha256,
    source_timezone,
    provenance_json,
    snapshot_hash,
    imported_at
FROM eos_fx_rate_snapshot
ORDER BY
    source_provider_id, source_record_id, publication_issue,
    base_currency, quote_currency, rate_date,
    imported_at, tenant_id, rate_snapshot_id
ON CONFLICT DO NOTHING;

DROP TRIGGER IF EXISTS trg_eos_fx_rate_snapshot_admission
    ON eos_fx_rate_snapshot;
DROP TRIGGER IF EXISTS trg_eos_fx_rate_snapshot_immutable
    ON eos_fx_rate_snapshot;
DROP INDEX IF EXISTS ix_eos_fx_rate_snapshot_resolve;

ALTER TABLE eos_fx_rate_snapshot
    ADD COLUMN IF NOT EXISTS market_rate_id UUID NULL;

UPDATE eos_fx_rate_snapshot snapshot
SET market_rate_id = market.market_rate_id
FROM eos_fx_market_rate market
WHERE snapshot.market_rate_id IS NULL
  AND market.source_provider_id = snapshot.source_provider_id
  AND market.source_record_id = snapshot.source_record_id
  AND market.publication_issue = snapshot.publication_issue
  AND market.base_currency = snapshot.base_currency
  AND market.quote_currency = snapshot.quote_currency
  AND market.rate_date = snapshot.rate_date;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM eos_fx_rate_snapshot WHERE market_rate_id IS NULL
    ) THEN
        RAISE EXCEPTION 'FX snapshot market-rate backfill is incomplete'
            USING ERRCODE = '23503';
    END IF;
END;
$$;

ALTER TABLE eos_fx_rate_snapshot
    DROP CONSTRAINT IF EXISTS ux_eos_fx_rate_snapshot_source,
    DROP CONSTRAINT IF EXISTS ck_eos_fx_rate_snapshot_pair,
    DROP CONSTRAINT IF EXISTS ck_eos_fx_rate_snapshot_values,
    DROP CONSTRAINT IF EXISTS ck_eos_fx_rate_snapshot_dates,
    DROP CONSTRAINT IF EXISTS ck_eos_fx_rate_snapshot_hashes,
    DROP CONSTRAINT IF EXISTS ck_eos_fx_rate_snapshot_provenance;

ALTER TABLE eos_fx_rate_snapshot
    ALTER COLUMN market_rate_id SET NOT NULL,
    ADD CONSTRAINT fk_eos_fx_rate_snapshot_market
        FOREIGN KEY (market_rate_id)
        REFERENCES eos_fx_market_rate (market_rate_id),
    ADD CONSTRAINT ux_eos_fx_rate_snapshot_adoption UNIQUE (
        tenant_id, company_id, rate_policy_id,
        rate_policy_version, market_rate_id
    ),
    ADD CONSTRAINT ck_eos_fx_rate_snapshot_normalized_rate
        CHECK (normalized_rate > 0),
    ADD CONSTRAINT ck_eos_fx_rate_snapshot_hash
        CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$');

ALTER TABLE eos_fx_rate_snapshot
    DROP COLUMN source_provider_id,
    DROP COLUMN base_currency,
    DROP COLUMN quote_currency,
    DROP COLUMN quote_unit,
    DROP COLUMN published_rate,
    DROP COLUMN rate_date,
    DROP COLUMN rate_as_of,
    DROP COLUMN published_at,
    DROP COLUMN publication_issue,
    DROP COLUMN is_final,
    DROP COLUMN source_record_id,
    DROP COLUMN source_uri,
    DROP COLUMN source_sha256,
    DROP COLUMN source_timezone,
    DROP COLUMN provenance_json;

CREATE INDEX IF NOT EXISTS ix_eos_fx_rate_snapshot_resolve
    ON eos_fx_rate_snapshot (
        tenant_id, company_id, rate_policy_id, market_rate_id,
        approved_state, effective_business_date DESC
    );

CREATE OR REPLACE FUNCTION eos_guard_fx_snapshot_admission()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    selected_policy eos_fx_rate_policy%ROWTYPE;
    selected_market eos_fx_market_rate%ROWTYPE;
BEGIN
    SELECT * INTO selected_policy
    FROM eos_fx_rate_policy policy
    WHERE policy.tenant_id = NEW.tenant_id
      AND policy.company_id = NEW.company_id
      AND policy.policy_id = NEW.rate_policy_id
      AND policy.version = NEW.rate_policy_version
      AND policy.status = 'APPROVED';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'approved FX policy was not found'
            USING ERRCODE = '23503';
    END IF;

    SELECT * INTO selected_market
    FROM eos_fx_market_rate market
    WHERE market.market_rate_id = NEW.market_rate_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'global FX market observation was not found'
            USING ERRCODE = '23503';
    END IF;

    IF selected_policy.source_provider_id <> selected_market.source_provider_id
       OR selected_policy.base_currency <> selected_market.base_currency
       OR selected_policy.quote_currency <> selected_market.quote_currency
       OR selected_market.rate_date < selected_policy.effective_from
       OR (selected_policy.effective_to IS NOT NULL
           AND selected_market.rate_date >= selected_policy.effective_to) THEN
        RAISE EXCEPTION 'FX RateSnapshot does not match approved policy'
            USING ERRCODE = '23514';
    END IF;
    IF (selected_policy.publication_selector = 'FIRST'
        AND selected_market.is_final)
       OR (selected_policy.publication_selector = 'FINAL'
           AND NOT selected_market.is_final) THEN
        RAISE EXCEPTION 'FX publication selector mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.effective_business_date <> selected_market.rate_date THEN
        RAISE EXCEPTION 'FX effective date does not match market observation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.normalized_rate <>
       ROUND(selected_market.published_rate / selected_market.quote_unit,
             selected_policy.rate_decimal_scale) THEN
        RAISE EXCEPTION 'FX normalized rate does not match quote unit'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_fx_market_rate_immutable ON eos_fx_market_rate;
CREATE TRIGGER trg_eos_fx_market_rate_immutable
BEFORE UPDATE OR DELETE ON eos_fx_market_rate
FOR EACH ROW EXECUTE FUNCTION eos_reject_fx_immutable_mutation();

CREATE TRIGGER trg_eos_fx_rate_snapshot_admission
BEFORE INSERT ON eos_fx_rate_snapshot
FOR EACH ROW EXECUTE FUNCTION eos_guard_fx_snapshot_admission();

CREATE TRIGGER trg_eos_fx_rate_snapshot_immutable
BEFORE UPDATE OR DELETE ON eos_fx_rate_snapshot
FOR EACH ROW EXECUTE FUNCTION eos_reject_fx_immutable_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2523_eos_fx_market_rate_adoption',
    'Global FX market observation and tenant company adoption boundary'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
