BEGIN;

CREATE OR REPLACE FUNCTION eos_reject_accounting_period_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Serialize date-range decisions for one tenant/company. A hash collision
    -- only over-serializes unrelated companies and cannot weaken the invariant.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':' || NEW.company_id::TEXT, 0)
    );
    IF EXISTS (
        SELECT 1
        FROM eos_accounting_period existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.company_id = NEW.company_id
          AND existing.period_id <> NEW.period_id
          AND existing.end_date >= NEW.start_date
          AND existing.start_date <= NEW.end_date
    ) THEN
        RAISE EXCEPTION 'overlapping AccountingPeriod'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION eos_guard_accounting_period_state()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'OPEN' OR NEW.version <> 1
           OR NEW.close_proof_ref IS NOT NULL OR NEW.closed_at IS NOT NULL
           OR NEW.ledger_cutoff_watermark IS NOT NULL THEN
            RAISE EXCEPTION 'AccountingPeriod must start OPEN at version 1'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.company_id IS DISTINCT FROM OLD.company_id
       OR NEW.period_id IS DISTINCT FROM OLD.period_id
       OR NEW.fiscal_year IS DISTINCT FROM OLD.fiscal_year
       OR NEW.period_no IS DISTINCT FROM OLD.period_no
       OR NEW.start_date IS DISTINCT FROM OLD.start_date
       OR NEW.end_date IS DISTINCT FROM OLD.end_date
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'AccountingPeriod identity and range are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.state = OLD.state THEN
        IF NEW.version IS DISTINCT FROM OLD.version
           OR NEW.close_proof_ref IS DISTINCT FROM OLD.close_proof_ref
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.ledger_cutoff_watermark
                IS DISTINCT FROM OLD.ledger_cutoff_watermark THEN
            RAISE EXCEPTION 'AccountingPeriod state evidence is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.state = 'OPEN' AND NEW.state = 'CLOSING')
        OR (OLD.state = 'CLOSING' AND NEW.state = 'CLOSED')
    ) OR NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'invalid AccountingPeriod state transition'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.state = 'CLOSING' AND (
        NEW.close_proof_ref IS NOT NULL OR NEW.closed_at IS NOT NULL
        OR NEW.ledger_cutoff_watermark IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'CLOSING AccountingPeriod cannot carry final evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.state = 'CLOSED' AND (
        NEW.close_proof_ref IS NULL
        OR NEW.close_proof_ref !~ '^sha256:[0-9a-f]{64}$'
        OR NEW.closed_at IS NULL
        OR NULLIF(BTRIM(NEW.ledger_cutoff_watermark), '') IS NULL
    ) THEN
        RAISE EXCEPTION 'CLOSED AccountingPeriod requires final evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_accounting_period_state
    ON eos_accounting_period;

CREATE TRIGGER trg_eos_accounting_period_state
BEFORE INSERT OR UPDATE
ON eos_accounting_period
FOR EACH ROW
EXECUTE FUNCTION eos_guard_accounting_period_state();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2521_eos_accounting_period_runtime',
    'Activate immutable AccountingPeriod state transitions and serialized ranges'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
