BEGIN;

CREATE TABLE IF NOT EXISTS eos_fx_rate_policy (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    policy_id UUID NOT NULL,
    version INTEGER NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    rate_kind VARCHAR(32) NOT NULL,
    source_provider_id VARCHAR(128) NOT NULL,
    publication_selector VARCHAR(32) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    allow_previous_business_day BOOLEAN NOT NULL,
    max_staleness_business_days INTEGER NOT NULL,
    rounding_mode VARCHAR(32) NOT NULL,
    rate_decimal_scale INTEGER NOT NULL,
    approved_by VARCHAR(128) NOT NULL,
    approval_proof_hash VARCHAR(71) NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_fx_rate_policy
        PRIMARY KEY (tenant_id, company_id, policy_id, version),
    CONSTRAINT fk_eos_fx_rate_policy_company
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT ux_eos_fx_rate_policy_hash
        UNIQUE (tenant_id, policy_hash),
    CONSTRAINT ck_eos_fx_rate_policy_purpose CHECK (
        purpose IN (
            'TRANSACTION_SPOT', 'MONETARY_CLOSE',
            'SETTLEMENT_REFERENCE', 'TAX_VALUATION'
        )
    ),
    CONSTRAINT ck_eos_fx_rate_policy_kind CHECK (
        rate_kind IN ('MARKET_BASE', 'DERIVED_CROSS', 'APPROVED_EXCEPTION')
    ),
    CONSTRAINT ck_eos_fx_rate_policy_publication CHECK (
        publication_selector IN ('FIRST', 'FINAL', 'AS_OF_TIMESTAMP')
    ),
    CONSTRAINT ck_eos_fx_rate_policy_dates CHECK (
        effective_to IS NULL OR effective_to > effective_from
    ),
    CONSTRAINT ck_eos_fx_rate_policy_pair CHECK (
        base_currency = UPPER(base_currency)
        AND quote_currency = UPPER(quote_currency)
        AND base_currency <> quote_currency
    ),
    CONSTRAINT ck_eos_fx_rate_policy_staleness CHECK (
        max_staleness_business_days BETWEEN 0 AND 366
        AND (
            allow_previous_business_day
            OR max_staleness_business_days = 0
        )
    ),
    CONSTRAINT ck_eos_fx_rate_policy_scale CHECK (
        rate_decimal_scale BETWEEN 0 AND 12
    ),
    CONSTRAINT ck_eos_fx_rate_policy_rounding CHECK (
        rounding_mode = 'HALF_EVEN'
    ),
    CONSTRAINT ck_eos_fx_rate_policy_hashes CHECK (
        approval_proof_hash ~ '^sha256:[0-9a-f]{64}$'
        AND policy_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_fx_rate_policy_status CHECK (status = 'APPROVED')
);

CREATE INDEX IF NOT EXISTS ix_eos_fx_rate_policy_resolve
    ON eos_fx_rate_policy (
        tenant_id, company_id, purpose, base_currency, quote_currency,
        status, effective_from, effective_to
    );

CREATE TABLE IF NOT EXISTS eos_fx_rate_snapshot (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    rate_snapshot_id UUID NOT NULL,
    source_provider_id VARCHAR(128) NOT NULL,
    rate_policy_id UUID NOT NULL,
    rate_policy_version INTEGER NOT NULL,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    quote_unit NUMERIC(18,6) NOT NULL,
    published_rate NUMERIC(28,12) NOT NULL,
    normalized_rate NUMERIC(28,12) NOT NULL,
    desired_rate_date DATE NOT NULL,
    rate_date DATE NOT NULL,
    rate_as_of TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    publication_issue VARCHAR(64) NOT NULL,
    is_final BOOLEAN NOT NULL,
    effective_business_date DATE NOT NULL,
    source_record_id VARCHAR(256) NOT NULL,
    source_uri VARCHAR(2048) NOT NULL,
    source_sha256 VARCHAR(71) NOT NULL,
    calendar_ref VARCHAR(128) NOT NULL,
    source_timezone VARCHAR(64) NOT NULL,
    provenance_json JSONB NOT NULL,
    snapshot_hash VARCHAR(71) NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL,
    approved_state VARCHAR(16) NOT NULL,
    CONSTRAINT pk_eos_fx_rate_snapshot
        PRIMARY KEY (tenant_id, rate_snapshot_id),
    CONSTRAINT fk_eos_fx_rate_snapshot_policy
        FOREIGN KEY (
            tenant_id, company_id, rate_policy_id, rate_policy_version
        ) REFERENCES eos_fx_rate_policy (
            tenant_id, company_id, policy_id, version
        ),
    CONSTRAINT ux_eos_fx_rate_snapshot_source
        UNIQUE (
            tenant_id, source_provider_id, source_record_id,
            publication_issue, base_currency, quote_currency, rate_date
        ),
    CONSTRAINT ux_eos_fx_rate_snapshot_hash
        UNIQUE (tenant_id, snapshot_hash),
    CONSTRAINT ck_eos_fx_rate_snapshot_pair CHECK (
        base_currency = UPPER(base_currency)
        AND quote_currency = UPPER(quote_currency)
        AND base_currency <> quote_currency
    ),
    CONSTRAINT ck_eos_fx_rate_snapshot_values CHECK (
        quote_unit > 0 AND published_rate > 0 AND normalized_rate > 0
    ),
    CONSTRAINT ck_eos_fx_rate_snapshot_dates CHECK (
        effective_business_date = rate_date
    ),
    CONSTRAINT ck_eos_fx_rate_snapshot_hashes CHECK (
        source_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND snapshot_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_fx_rate_snapshot_provenance CHECK (
        jsonb_typeof(provenance_json) = 'object'
    ),
    CONSTRAINT ck_eos_fx_rate_snapshot_state CHECK (
        approved_state = 'APPROVED'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_fx_rate_snapshot_resolve
    ON eos_fx_rate_snapshot (
        tenant_id, company_id, base_currency, quote_currency,
        approved_state, effective_business_date DESC, published_at DESC
    );

CREATE OR REPLACE FUNCTION eos_reject_fx_policy_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.tenant_id || ':' || NEW.company_id::TEXT || ':' ||
            NEW.purpose || ':' || NEW.base_currency || ':' || NEW.quote_currency,
            0
        )
    );
    IF EXISTS (
        SELECT 1
        FROM eos_fx_rate_policy existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.company_id = NEW.company_id
          AND existing.purpose = NEW.purpose
          AND existing.base_currency = NEW.base_currency
          AND existing.quote_currency = NEW.quote_currency
          AND existing.status = 'APPROVED'
          AND (existing.policy_id, existing.version)
              <> (NEW.policy_id, NEW.version)
          AND (existing.effective_to IS NULL
               OR existing.effective_to > NEW.effective_from)
          AND (NEW.effective_to IS NULL
               OR existing.effective_from < NEW.effective_to)
    ) THEN
        RAISE EXCEPTION 'overlapping approved FX rate policy'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION eos_reject_fx_immutable_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is immutable after admission', TG_TABLE_NAME
        USING ERRCODE = '23514';
END;
$$;

CREATE OR REPLACE FUNCTION eos_guard_fx_snapshot_admission()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    selected_policy eos_fx_rate_policy%ROWTYPE;
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
    IF selected_policy.source_provider_id <> NEW.source_provider_id
       OR selected_policy.base_currency <> NEW.base_currency
       OR selected_policy.quote_currency <> NEW.quote_currency
       OR NEW.rate_date < selected_policy.effective_from
       OR (selected_policy.effective_to IS NOT NULL
           AND NEW.rate_date >= selected_policy.effective_to) THEN
        RAISE EXCEPTION 'FX RateSnapshot does not match approved policy'
            USING ERRCODE = '23514';
    END IF;
    IF (selected_policy.publication_selector = 'FIRST' AND NEW.is_final)
       OR (selected_policy.publication_selector = 'FINAL' AND NOT NEW.is_final) THEN
        RAISE EXCEPTION 'FX publication selector mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.normalized_rate <>
       ROUND(NEW.published_rate / NEW.quote_unit,
             selected_policy.rate_decimal_scale) THEN
        RAISE EXCEPTION 'FX normalized rate does not match quote unit'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_fx_rate_policy_overlap ON eos_fx_rate_policy;
CREATE TRIGGER trg_eos_fx_rate_policy_overlap
BEFORE INSERT ON eos_fx_rate_policy
FOR EACH ROW EXECUTE FUNCTION eos_reject_fx_policy_overlap();

DROP TRIGGER IF EXISTS trg_eos_fx_rate_policy_immutable ON eos_fx_rate_policy;
CREATE TRIGGER trg_eos_fx_rate_policy_immutable
BEFORE UPDATE OR DELETE ON eos_fx_rate_policy
FOR EACH ROW EXECUTE FUNCTION eos_reject_fx_immutable_mutation();

DROP TRIGGER IF EXISTS trg_eos_fx_rate_snapshot_admission
    ON eos_fx_rate_snapshot;
CREATE TRIGGER trg_eos_fx_rate_snapshot_admission
BEFORE INSERT ON eos_fx_rate_snapshot
FOR EACH ROW EXECUTE FUNCTION eos_guard_fx_snapshot_admission();

DROP TRIGGER IF EXISTS trg_eos_fx_rate_snapshot_immutable ON eos_fx_rate_snapshot;
CREATE TRIGGER trg_eos_fx_rate_snapshot_immutable
BEFORE UPDATE OR DELETE ON eos_fx_rate_snapshot
FOR EACH ROW EXECUTE FUNCTION eos_reject_fx_immutable_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2522_eos_fx_rate_policy_snapshot',
    'Approved FX policy and immutable source-lineage RateSnapshot foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
