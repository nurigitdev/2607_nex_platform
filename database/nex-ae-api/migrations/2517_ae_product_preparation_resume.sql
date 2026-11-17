BEGIN;

ALTER TABLE ae_wait_registration
    ADD COLUMN IF NOT EXISTS resume_target_kind TEXT NULL,
    ADD COLUMN IF NOT EXISTS wait_contract_ref TEXT NULL;

UPDATE ae_wait_registration
SET resume_target_kind = 'EXECUTABLE_STEP',
    wait_contract_ref = result_contract_ref
WHERE resume_target_kind IS NULL OR wait_contract_ref IS NULL;

ALTER TABLE ae_wait_registration
    ALTER COLUMN resume_target_kind SET NOT NULL,
    ALTER COLUMN wait_contract_ref SET NOT NULL,
    ALTER COLUMN executable_step_id DROP NOT NULL,
    ALTER COLUMN result_contract_ref DROP NOT NULL;

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ck_ae_wait_registration_type,
    DROP CONSTRAINT IF EXISTS ck_ae_wait_nsl_approval_lineage,
    DROP CONSTRAINT IF EXISTS ck_ae_wait_resume_target,
    DROP CONSTRAINT IF EXISTS ck_ae_wait_contract_compat;

ALTER TABLE ae_wait_registration
    ADD CONSTRAINT ck_ae_wait_registration_type CHECK (
        wait_type IN ('WORK_RESULT', 'NSL_APPROVAL', 'PRODUCT_PREPARATION')
    ),
    ADD CONSTRAINT ck_ae_wait_resume_target CHECK (
        (
            wait_type IN ('WORK_RESULT', 'NSL_APPROVAL')
            AND resume_target_kind = 'EXECUTABLE_STEP'
            AND executable_step_id IS NOT NULL
        )
        OR
        (
            wait_type = 'PRODUCT_PREPARATION'
            AND resume_target_kind = 'PRODUCT_COORDINATOR'
            AND executable_step_id IS NULL
        )
    ),
    ADD CONSTRAINT ck_ae_wait_contract_compat CHECK (
        char_length(wait_contract_ref) BETWEEN 1 AND 512
        AND (
            (
                wait_type IN ('WORK_RESULT', 'NSL_APPROVAL')
                AND result_contract_ref IS NOT NULL
                AND wait_contract_ref = result_contract_ref
            )
            OR
            (
                wait_type = 'PRODUCT_PREPARATION'
                AND result_contract_ref IS NULL
            )
        )
    ),
    ADD CONSTRAINT ck_ae_wait_nsl_approval_lineage CHECK (
        (
            wait_type IN ('WORK_RESULT', 'PRODUCT_PREPARATION')
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
            AND approval_request_id IS NULL
            AND checkpoint_version IS NULL
        )
        OR
        (
            wait_type = 'NSL_APPROVAL'
            AND nsl_execution_id IS NOT NULL
            AND char_length(nsl_execution_id) BETWEEN 1 AND 256
            AND business_operation_id IS NOT NULL
            AND char_length(business_operation_id) BETWEEN 1 AND 256
            AND approval_request_id IS NOT NULL
            AND char_length(approval_request_id) BETWEEN 1 AND 256
            AND external_ref = approval_request_id
            AND checkpoint_version >= 1
        )
    );

CREATE OR REPLACE FUNCTION ae_fill_wait_resume_projection()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.wait_type IN ('WORK_RESULT', 'NSL_APPROVAL') THEN
        IF NEW.resume_target_kind IS NULL THEN
            NEW.resume_target_kind := 'EXECUTABLE_STEP';
        END IF;
        IF NEW.wait_contract_ref IS NULL THEN
            NEW.wait_contract_ref := NEW.result_contract_ref;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_wait_resume_projection
    ON ae_wait_registration;
CREATE TRIGGER trg_ae_wait_resume_projection
BEFORE INSERT ON ae_wait_registration
FOR EACH ROW EXECUTE FUNCTION ae_fill_wait_resume_projection();

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_wait_product_external
    ON ae_wait_registration (
        tenant_id, agent_execution_id, external_ref, wait_type
    )
    WHERE wait_type = 'PRODUCT_PREPARATION';

ALTER TABLE ae_external_event_inbox
    ADD COLUMN IF NOT EXISTS event_family TEXT NULL;

UPDATE ae_external_event_inbox
SET event_family = CASE event_type
    WHEN 'WORK_RESULT_SUBMITTED' THEN 'WORK_RESULT'
    WHEN 'NSL_APPROVAL_DECIDED' THEN 'NSL_APPROVAL'
    ELSE event_family
END
WHERE event_family IS NULL;

ALTER TABLE ae_external_event_inbox
    ALTER COLUMN event_family SET NOT NULL;

ALTER TABLE ae_external_event_inbox
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_type,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_shape,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_family;

ALTER TABLE ae_external_event_inbox
    ADD CONSTRAINT ck_ae_external_event_type CHECK (
        event_type IN (
            'WORK_RESULT_SUBMITTED',
            'NSL_APPROVAL_DECIDED',
            'BUSINESS_APPROVAL_CHANGED',
            'ACCOUNTING_APPROVAL_CHANGED'
        )
    ),
    ADD CONSTRAINT ck_ae_external_event_family CHECK (
        (
            event_type = 'WORK_RESULT_SUBMITTED'
            AND event_family = 'WORK_RESULT'
        )
        OR
        (
            event_type = 'NSL_APPROVAL_DECIDED'
            AND event_family = 'NSL_APPROVAL'
        )
        OR
        (
            event_type IN (
                'BUSINESS_APPROVAL_CHANGED',
                'ACCOUNTING_APPROVAL_CHANGED'
            )
            AND event_family = 'PRODUCT_PREPARATION'
        )
    ),
    ADD CONSTRAINT ck_ae_external_event_shape CHECK (
        (
            event_type = 'WORK_RESULT_SUBMITTED'
            AND result_id IS NOT NULL
            AND approval_request_id IS NULL
            AND approval_work_item_ref IS NULL
            AND approval_evidence_ref IS NULL
            AND evidence_integrity IS NULL
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
        )
        OR
        (
            event_type = 'NSL_APPROVAL_DECIDED'
            AND result_id IS NULL
            AND result_contract_ref IS NULL
            AND approval_request_id IS NOT NULL
            AND char_length(approval_request_id) BETWEEN 1 AND 256
            AND external_ref = approval_request_id
            AND approval_work_item_ref IS NOT NULL
            AND char_length(approval_work_item_ref) BETWEEN 1 AND 128
            AND approval_evidence_ref IS NOT NULL
            AND char_length(approval_evidence_ref) BETWEEN 1 AND 512
            AND evidence_integrity ~ '^sha256:[0-9a-f]{64}$'
            AND nsl_execution_id IS NOT NULL
            AND char_length(nsl_execution_id) BETWEEN 1 AND 256
            AND business_operation_id IS NOT NULL
            AND char_length(business_operation_id) BETWEEN 1 AND 256
        )
        OR
        (
            event_type IN (
                'BUSINESS_APPROVAL_CHANGED',
                'ACCOUNTING_APPROVAL_CHANGED'
            )
            AND result_id IS NULL
            AND result_contract_ref IS NULL
            AND approval_request_id IS NULL
            AND approval_work_item_ref IS NULL
            AND approval_evidence_ref IS NULL
            AND evidence_integrity IS NULL
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
            AND jsonb_typeof(event_payload) = 'object'
        )
    );

CREATE OR REPLACE FUNCTION ae_fill_event_family_projection()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_family IS NULL THEN
        NEW.event_family := CASE NEW.event_type
            WHEN 'WORK_RESULT_SUBMITTED' THEN 'WORK_RESULT'
            WHEN 'NSL_APPROVAL_DECIDED' THEN 'NSL_APPROVAL'
            WHEN 'BUSINESS_APPROVAL_CHANGED' THEN 'PRODUCT_PREPARATION'
            WHEN 'ACCOUNTING_APPROVAL_CHANGED' THEN 'PRODUCT_PREPARATION'
            ELSE NULL
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_event_family_projection
    ON ae_external_event_inbox;
CREATE TRIGGER trg_ae_event_family_projection
BEFORE INSERT ON ae_external_event_inbox
FOR EACH ROW EXECUTE FUNCTION ae_fill_event_family_projection();

CREATE INDEX IF NOT EXISTS ix_ae_event_product_received
    ON ae_external_event_inbox (tenant_id, external_ref, received_at, event_id)
    WHERE event_family = 'PRODUCT_PREPARATION' AND state = 'RECEIVED';

CREATE TABLE IF NOT EXISTS ae_product_prep_checkpoint (
    tenant_id TEXT NOT NULL,
    checkpoint_id UUID NOT NULL,
    checkpoint_schema_version TEXT NOT NULL
        CHECK (char_length(checkpoint_schema_version) BETWEEN 1 AND 64),
    checkpoint_version INTEGER NOT NULL CHECK (checkpoint_version >= 1),
    previous_checkpoint_id UUID NULL,
    previous_checkpoint_hash TEXT NULL
        CHECK (
            previous_checkpoint_hash IS NULL
            OR previous_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
    agent_execution_id UUID NOT NULL,
    requester_ref TEXT NOT NULL
        CHECK (char_length(requester_ref) BETWEEN 1 AND 200),
    work_intent_id UUID NOT NULL,
    work_intent_revision INTEGER NOT NULL CHECK (work_intent_revision >= 1),
    work_intent_hash TEXT NOT NULL
        CHECK (work_intent_hash ~ '^sha256:[0-9a-f]{64}$'),
    agent_context_id UUID NOT NULL,
    context_generation INTEGER NOT NULL CHECK (context_generation >= 1),
    context_hash TEXT NOT NULL
        CHECK (context_hash ~ '^sha256:[0-9a-f]{64}$'),
    business_context_hash TEXT NOT NULL
        CHECK (business_context_hash ~ '^sha256:[0-9a-f]{64}$'),
    capability_id TEXT NOT NULL
        CHECK (char_length(capability_id) BETWEEN 1 AND 160),
    capability_version TEXT NOT NULL
        CHECK (char_length(capability_version) BETWEEN 1 AND 64),
    capability_release_ref TEXT NOT NULL
        CHECK (char_length(capability_release_ref) BETWEEN 1 AND 512),
    capability_registration_hash TEXT NOT NULL
        CHECK (capability_registration_hash ~ '^sha256:[0-9a-f]{64}$'),
    coordinator_id TEXT NOT NULL
        CHECK (char_length(coordinator_id) BETWEEN 1 AND 160),
    coordinator_version TEXT NOT NULL
        CHECK (char_length(coordinator_version) BETWEEN 1 AND 64),
    coordinator_registration_hash TEXT NOT NULL
        CHECK (coordinator_registration_hash ~ '^sha256:[0-9a-f]{64}$'),
    preparation_adapter_source_identity TEXT NOT NULL
        CHECK (char_length(preparation_adapter_source_identity) BETWEEN 1 AND 512),
    materializer_source_identity TEXT NOT NULL
        CHECK (char_length(materializer_source_identity) BETWEEN 1 AND 512),
    stage TEXT NOT NULL CHECK (char_length(stage) BETWEEN 1 AND 64),
    stage_kind TEXT NOT NULL
        CHECK (stage_kind IN ('INITIAL', 'WAITING', 'READY', 'TERMINAL')),
    authority_refs JSONB NOT NULL,
    idempotency_key TEXT NOT NULL
        CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
    correlation_id TEXT NOT NULL
        CHECK (char_length(correlation_id) BETWEEN 1 AND 256),
    causation_id TEXT NULL
        CHECK (causation_id IS NULL OR char_length(causation_id) BETWEEN 1 AND 256),
    checkpoint_projection JSONB NOT NULL,
    checkpoint_hash TEXT NOT NULL
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, checkpoint_id),
    CONSTRAINT ux_ae_product_prep_checkpoint_version UNIQUE (
        tenant_id,
        agent_execution_id,
        coordinator_id,
        coordinator_version,
        checkpoint_version
    ),
    CONSTRAINT ux_ae_product_prep_checkpoint_hash UNIQUE (
        tenant_id, checkpoint_hash
    ),
    CONSTRAINT ux_ae_product_prep_checkpoint_idempotency UNIQUE (
        tenant_id, idempotency_key
    ),
    CONSTRAINT fk_ae_product_prep_checkpoint_previous FOREIGN KEY (
        tenant_id, previous_checkpoint_id
    ) REFERENCES ae_product_prep_checkpoint (tenant_id, checkpoint_id),
    CONSTRAINT fk_ae_product_prep_checkpoint_execution FOREIGN KEY (
        tenant_id, agent_execution_id
    ) REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_product_prep_checkpoint_intent FOREIGN KEY (
        tenant_id, work_intent_id
    ) REFERENCES ae_work_intent (tenant_id, work_intent_id),
    CONSTRAINT fk_ae_product_prep_checkpoint_context FOREIGN KEY (
        tenant_id, agent_context_id
    ) REFERENCES ae_agent_context (tenant_id, context_id),
    CONSTRAINT ck_ae_product_prep_checkpoint_chain CHECK (
        (
            checkpoint_version = 1
            AND previous_checkpoint_id IS NULL
            AND previous_checkpoint_hash IS NULL
        )
        OR
        (
            checkpoint_version > 1
            AND previous_checkpoint_id IS NOT NULL
            AND previous_checkpoint_hash IS NOT NULL
        )
    ),
    CONSTRAINT ck_ae_product_prep_checkpoint_authorities CHECK (
        jsonb_typeof(authority_refs) = 'array'
        AND jsonb_array_length(authority_refs) <= 32
    ),
    CONSTRAINT ck_ae_product_prep_checkpoint_projection CHECK (
        jsonb_typeof(checkpoint_projection) = 'object'
        AND checkpoint_projection ->> 'schema_version' = checkpoint_schema_version
        AND checkpoint_projection ->> 'checkpoint_id' = checkpoint_id::TEXT
        AND (checkpoint_projection ->> 'checkpoint_version')::INTEGER
            = checkpoint_version
        AND checkpoint_projection ->> 'agent_execution_id'
            = agent_execution_id::TEXT
        AND checkpoint_projection ->> 'work_intent_id' = work_intent_id::TEXT
        AND checkpoint_projection ->> 'agent_context_id' = agent_context_id::TEXT
        AND checkpoint_projection ->> 'stage' = stage
        AND checkpoint_projection ->> 'stage_kind' = stage_kind
        AND checkpoint_projection ->> 'checkpoint_hash' = checkpoint_hash
    )
);

CREATE INDEX IF NOT EXISTS ix_ae_product_prep_checkpoint_execution
    ON ae_product_prep_checkpoint (
        tenant_id, agent_execution_id, checkpoint_version DESC
    );

CREATE OR REPLACE FUNCTION ae_guard_product_prep_checkpoint()
RETURNS TRIGGER AS $$
DECLARE
    previous_row ae_product_prep_checkpoint%ROWTYPE;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'Product Preparation checkpoints are append-only';
    END IF;
    IF NEW.checkpoint_version = 1 THEN
        RETURN NEW;
    END IF;
    SELECT * INTO previous_row
    FROM ae_product_prep_checkpoint
    WHERE tenant_id = NEW.tenant_id
      AND checkpoint_id = NEW.previous_checkpoint_id;
    IF NOT FOUND
       OR previous_row.checkpoint_hash <> NEW.previous_checkpoint_hash
       OR previous_row.checkpoint_version + 1 <> NEW.checkpoint_version
       OR previous_row.agent_execution_id <> NEW.agent_execution_id
       OR previous_row.work_intent_id <> NEW.work_intent_id
       OR previous_row.agent_context_id <> NEW.agent_context_id
       OR previous_row.coordinator_id <> NEW.coordinator_id
       OR previous_row.coordinator_version <> NEW.coordinator_version
       OR previous_row.coordinator_registration_hash
            <> NEW.coordinator_registration_hash THEN
        RAISE EXCEPTION 'Product Preparation checkpoint lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_product_prep_checkpoint_guard
    ON ae_product_prep_checkpoint;
CREATE TRIGGER trg_ae_product_prep_checkpoint_guard
BEFORE INSERT OR UPDATE OR DELETE ON ae_product_prep_checkpoint
FOR EACH ROW EXECUTE FUNCTION ae_guard_product_prep_checkpoint();

CREATE TABLE IF NOT EXISTS ae_product_prep_wait_binding (
    tenant_id TEXT NOT NULL,
    wait_id UUID NOT NULL,
    checkpoint_id UUID NOT NULL,
    checkpoint_hash TEXT NOT NULL
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
    coordinator_id TEXT NOT NULL
        CHECK (char_length(coordinator_id) BETWEEN 1 AND 160),
    coordinator_version TEXT NOT NULL
        CHECK (char_length(coordinator_version) BETWEEN 1 AND 64),
    coordinator_registration_hash TEXT NOT NULL
        CHECK (coordinator_registration_hash ~ '^sha256:[0-9a-f]{64}$'),
    expected_event_type TEXT NOT NULL CHECK (
        expected_event_type IN (
            'BUSINESS_APPROVAL_CHANGED',
            'ACCOUNTING_APPROVAL_CHANGED'
        )
    ),
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('BUSINESS_FORMAL', 'ACCOUNTING_REVIEW')
    ),
    authority_ref TEXT NOT NULL
        CHECK (char_length(authority_ref) BETWEEN 1 AND 512),
    agent_execution_id UUID NOT NULL,
    work_intent_id UUID NOT NULL,
    binding_hash TEXT NOT NULL
        CHECK (binding_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, wait_id),
    CONSTRAINT ux_ae_product_prep_wait_checkpoint UNIQUE (
        tenant_id, checkpoint_id
    ),
    CONSTRAINT fk_ae_product_prep_wait_wait FOREIGN KEY (
        tenant_id, wait_id
    ) REFERENCES ae_wait_registration (tenant_id, wait_id),
    CONSTRAINT fk_ae_product_prep_wait_checkpoint FOREIGN KEY (
        tenant_id, checkpoint_id
    ) REFERENCES ae_product_prep_checkpoint (tenant_id, checkpoint_id),
    CONSTRAINT fk_ae_product_prep_wait_execution FOREIGN KEY (
        tenant_id, agent_execution_id
    ) REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_product_prep_wait_intent FOREIGN KEY (
        tenant_id, work_intent_id
    ) REFERENCES ae_work_intent (tenant_id, work_intent_id),
    CONSTRAINT ck_ae_product_prep_wait_authority CHECK (
        (
            authority_kind = 'BUSINESS_FORMAL'
            AND expected_event_type = 'BUSINESS_APPROVAL_CHANGED'
        )
        OR
        (
            authority_kind = 'ACCOUNTING_REVIEW'
            AND expected_event_type = 'ACCOUNTING_APPROVAL_CHANGED'
        )
    )
);

CREATE OR REPLACE FUNCTION ae_guard_product_prep_wait_binding()
RETURNS TRIGGER AS $$
DECLARE
    wait_row ae_wait_registration%ROWTYPE;
    checkpoint_row ae_product_prep_checkpoint%ROWTYPE;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'Product Preparation wait bindings are immutable';
    END IF;
    SELECT * INTO wait_row
    FROM ae_wait_registration
    WHERE tenant_id = NEW.tenant_id AND wait_id = NEW.wait_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product Preparation wait is unavailable';
    END IF;
    SELECT * INTO checkpoint_row
    FROM ae_product_prep_checkpoint
    WHERE tenant_id = NEW.tenant_id AND checkpoint_id = NEW.checkpoint_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product Preparation checkpoint is unavailable';
    END IF;
    IF wait_row.wait_type <> 'PRODUCT_PREPARATION'
       OR wait_row.resume_target_kind <> 'PRODUCT_COORDINATOR'
       OR wait_row.executable_step_id IS NOT NULL
       OR wait_row.agent_execution_id <> NEW.agent_execution_id
       OR wait_row.external_ref <> NEW.authority_ref
       OR checkpoint_row.stage_kind <> 'WAITING'
       OR checkpoint_row.checkpoint_hash <> NEW.checkpoint_hash
       OR checkpoint_row.agent_execution_id <> NEW.agent_execution_id
       OR checkpoint_row.work_intent_id <> NEW.work_intent_id
       OR checkpoint_row.coordinator_id <> NEW.coordinator_id
       OR checkpoint_row.coordinator_version <> NEW.coordinator_version
       OR checkpoint_row.coordinator_registration_hash
            <> NEW.coordinator_registration_hash THEN
        RAISE EXCEPTION 'Product Preparation wait binding lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_product_prep_wait_binding_guard
    ON ae_product_prep_wait_binding;
CREATE TRIGGER trg_ae_product_prep_wait_binding_guard
BEFORE INSERT OR UPDATE OR DELETE ON ae_product_prep_wait_binding
FOR EACH ROW EXECUTE FUNCTION ae_guard_product_prep_wait_binding();

CREATE TABLE IF NOT EXISTS ae_product_prep_event_binding (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    wait_id UUID NOT NULL,
    checkpoint_id UUID NOT NULL,
    checkpoint_hash TEXT NOT NULL
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
    coordinator_id TEXT NOT NULL
        CHECK (char_length(coordinator_id) BETWEEN 1 AND 160),
    coordinator_version TEXT NOT NULL
        CHECK (char_length(coordinator_version) BETWEEN 1 AND 64),
    coordinator_registration_hash TEXT NOT NULL
        CHECK (coordinator_registration_hash ~ '^sha256:[0-9a-f]{64}$'),
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('BUSINESS_FORMAL', 'ACCOUNTING_REVIEW')
    ),
    notification_ref TEXT NOT NULL
        CHECK (char_length(notification_ref) BETWEEN 1 AND 512),
    agent_execution_id UUID NOT NULL,
    work_intent_id UUID NOT NULL,
    binding_hash TEXT NOT NULL
        CHECK (binding_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT fk_ae_product_prep_event_inbox FOREIGN KEY (
        tenant_id, event_id
    ) REFERENCES ae_external_event_inbox (tenant_id, event_id),
    CONSTRAINT fk_ae_product_prep_event_wait FOREIGN KEY (
        tenant_id, wait_id
    ) REFERENCES ae_product_prep_wait_binding (tenant_id, wait_id),
    CONSTRAINT fk_ae_product_prep_event_checkpoint FOREIGN KEY (
        tenant_id, checkpoint_id
    ) REFERENCES ae_product_prep_checkpoint (tenant_id, checkpoint_id),
    CONSTRAINT fk_ae_product_prep_event_execution FOREIGN KEY (
        tenant_id, agent_execution_id
    ) REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_product_prep_event_intent FOREIGN KEY (
        tenant_id, work_intent_id
    ) REFERENCES ae_work_intent (tenant_id, work_intent_id)
);

CREATE INDEX IF NOT EXISTS ix_ae_product_prep_event_wait
    ON ae_product_prep_event_binding (tenant_id, wait_id, created_at, event_id);

CREATE OR REPLACE FUNCTION ae_guard_product_prep_event_binding()
RETURNS TRIGGER AS $$
DECLARE
    event_row ae_external_event_inbox%ROWTYPE;
    wait_binding_row ae_product_prep_wait_binding%ROWTYPE;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'Product Preparation event bindings are immutable';
    END IF;
    SELECT * INTO event_row
    FROM ae_external_event_inbox
    WHERE tenant_id = NEW.tenant_id AND event_id = NEW.event_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product Preparation event is unavailable';
    END IF;
    SELECT * INTO wait_binding_row
    FROM ae_product_prep_wait_binding
    WHERE tenant_id = NEW.tenant_id AND wait_id = NEW.wait_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product Preparation wait binding is unavailable';
    END IF;
    IF event_row.event_family <> 'PRODUCT_PREPARATION'
       OR event_row.event_type <> wait_binding_row.expected_event_type
       OR event_row.external_ref <> wait_binding_row.authority_ref
       OR NEW.checkpoint_id <> wait_binding_row.checkpoint_id
       OR NEW.checkpoint_hash <> wait_binding_row.checkpoint_hash
       OR NEW.coordinator_id <> wait_binding_row.coordinator_id
       OR NEW.coordinator_version <> wait_binding_row.coordinator_version
       OR NEW.coordinator_registration_hash
            <> wait_binding_row.coordinator_registration_hash
       OR NEW.authority_kind <> wait_binding_row.authority_kind
       OR NEW.agent_execution_id <> wait_binding_row.agent_execution_id
       OR NEW.work_intent_id <> wait_binding_row.work_intent_id THEN
        RAISE EXCEPTION 'Product Preparation event binding lineage is invalid';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_product_prep_event_binding_guard
    ON ae_product_prep_event_binding;
CREATE TRIGGER trg_ae_product_prep_event_binding_guard
BEFORE INSERT OR UPDATE OR DELETE ON ae_product_prep_event_binding
FOR EACH ROW EXECUTE FUNCTION ae_guard_product_prep_event_binding();

CREATE OR REPLACE FUNCTION ae_require_product_prep_wait_binding()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.wait_type = 'PRODUCT_PREPARATION'
       AND NOT EXISTS (
           SELECT 1
           FROM ae_product_prep_wait_binding
           WHERE tenant_id = NEW.tenant_id AND wait_id = NEW.wait_id
       ) THEN
        RAISE EXCEPTION 'Product Preparation wait requires a typed binding';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_product_prep_wait_binding_required
    ON ae_wait_registration;
CREATE CONSTRAINT TRIGGER trg_ae_product_prep_wait_binding_required
AFTER INSERT OR UPDATE ON ae_wait_registration
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION ae_require_product_prep_wait_binding();

CREATE OR REPLACE FUNCTION ae_require_product_prep_event_binding()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_family = 'PRODUCT_PREPARATION'
       AND NOT EXISTS (
           SELECT 1
           FROM ae_product_prep_event_binding
           WHERE tenant_id = NEW.tenant_id AND event_id = NEW.event_id
       ) THEN
        RAISE EXCEPTION 'Product Preparation event requires a typed binding';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ae_product_prep_event_binding_required
    ON ae_external_event_inbox;
CREATE CONSTRAINT TRIGGER trg_ae_product_prep_event_binding_required
AFTER INSERT OR UPDATE ON ae_external_event_inbox
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION ae_require_product_prep_event_binding();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2517_ae_product_preparation_resume',
    'Generalized wait/event resume envelopes and immutable Product Preparation bindings'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
