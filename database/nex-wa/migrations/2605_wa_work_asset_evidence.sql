BEGIN;

CREATE TABLE IF NOT EXISTS wa_work_asset_evidence (
    tenant_id TEXT NOT NULL,
    work_asset_id UUID NOT NULL,
    work_evidence_id UUID NOT NULL,
    binding_role TEXT NOT NULL CHECK (binding_role IN ('PRIMARY', 'SUPPORTING')),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, work_asset_id, work_evidence_id),
    CONSTRAINT fk_wa_asset_evidence_asset
        FOREIGN KEY (tenant_id, work_asset_id)
        REFERENCES wa_work_asset (tenant_id, work_asset_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_wa_asset_evidence_evidence
        FOREIGN KEY (tenant_id, work_evidence_id)
        REFERENCES wa_work_evidence (tenant_id, work_evidence_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wa_asset_evidence_one_primary
    ON wa_work_asset_evidence (tenant_id, work_asset_id)
    WHERE binding_role = 'PRIMARY';

CREATE INDEX IF NOT EXISTS ix_wa_asset_evidence_evidence
    ON wa_work_asset_evidence (tenant_id, work_evidence_id);

INSERT INTO schema_migrations (version, description)
VALUES ('2605_wa_work_asset_evidence', 'WA WorkAsset evidence binding')
ON CONFLICT (version) DO NOTHING;

COMMIT;
