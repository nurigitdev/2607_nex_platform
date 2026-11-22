BEGIN;

CREATE TABLE IF NOT EXISTS eos_coa_definition_release (
    definition_release_id UUID PRIMARY KEY,
    scope_type VARCHAR(8) NOT NULL,
    owner_tenant_id VARCHAR(128) NULL,
    base_global_release_id UUID NULL,
    chart_profile VARCHAR(64) NOT NULL,
    release_version VARCHAR(64) NOT NULL,
    effective_from DATE NOT NULL,
    source_reference VARCHAR(512) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_eos_coa_release_base
        FOREIGN KEY (base_global_release_id)
        REFERENCES eos_coa_definition_release (definition_release_id),
    CONSTRAINT ck_eos_coa_release_scope CHECK (
        (scope_type = 'GLOBAL'
         AND owner_tenant_id IS NULL
         AND base_global_release_id IS NULL)
        OR
        (scope_type = 'TENANT'
         AND owner_tenant_id IS NOT NULL
         AND base_global_release_id IS NOT NULL)
    ),
    CONSTRAINT ck_eos_coa_release_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
        AND content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_coa_release_status CHECK (
        status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')
    ),
    CONSTRAINT ck_eos_coa_release_published_at CHECK (
        (status = 'DRAFT' AND published_at IS NULL)
        OR (status IN ('PUBLISHED', 'SUPERSEDED') AND published_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_global_release_version
    ON eos_coa_definition_release (chart_profile, release_version)
    WHERE scope_type = 'GLOBAL';

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_tenant_release_version
    ON eos_coa_definition_release (
        owner_tenant_id, chart_profile, release_version
    )
    WHERE scope_type = 'TENANT';

CREATE INDEX IF NOT EXISTS ix_eos_coa_release_effective
    ON eos_coa_definition_release (
        scope_type, owner_tenant_id, status, effective_from
    );

CREATE TABLE IF NOT EXISTS eos_coa_entry (
    entry_id UUID PRIMARY KEY,
    definition_release_id UUID NOT NULL,
    scope_type VARCHAR(8) NOT NULL,
    owner_tenant_id VARCHAR(128) NULL,
    account_code VARCHAR(8) NOT NULL,
    semantic_key VARCHAR(128) NOT NULL,
    account_name VARCHAR(256) NOT NULL,
    parent_entry_id UUID NULL,
    hierarchy_level INTEGER NOT NULL,
    category VARCHAR(16) NOT NULL,
    account_type VARCHAR(32) NOT NULL,
    normal_balance VARCHAR(2) NOT NULL,
    is_contra BOOLEAN NOT NULL,
    is_postable BOOLEAN NOT NULL,
    is_monetary_default BOOLEAN NOT NULL,
    reporting_mapping_status VARCHAR(32) NOT NULL,
    source_lineage VARCHAR(128) NOT NULL,
    source_row_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_eos_coa_entry_release
        FOREIGN KEY (definition_release_id)
        REFERENCES eos_coa_definition_release (definition_release_id),
    CONSTRAINT fk_eos_coa_entry_parent
        FOREIGN KEY (parent_entry_id)
        REFERENCES eos_coa_entry (entry_id),
    CONSTRAINT ux_eos_coa_entry_code
        UNIQUE (definition_release_id, account_code),
    CONSTRAINT ux_eos_coa_entry_semantic
        UNIQUE (definition_release_id, semantic_key),
    CONSTRAINT ck_eos_coa_entry_scope CHECK (
        (scope_type = 'GLOBAL' AND owner_tenant_id IS NULL)
        OR (scope_type = 'TENANT' AND owner_tenant_id IS NOT NULL)
    ),
    CONSTRAINT ck_eos_coa_entry_code CHECK (
        account_code ~ '^[1-9][0-9]{7}$'
    ),
    CONSTRAINT ck_eos_coa_entry_semantic CHECK (
        semantic_key ~ '^MB-COA-[A-Z0-9]+(-[A-Z0-9]+)*$'
    ),
    CONSTRAINT ck_eos_coa_entry_level CHECK (hierarchy_level BETWEEN 1 AND 4),
    CONSTRAINT ck_eos_coa_entry_category CHECK (
        category IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')
    ),
    CONSTRAINT ck_eos_coa_entry_balance CHECK (normal_balance IN ('DR', 'CR')),
    CONSTRAINT ck_eos_coa_entry_mapping CHECK (
        reporting_mapping_status IN ('MAPPING_PENDING', 'RESOLVED', 'NOT_APPLICABLE')
    ),
    CONSTRAINT ck_eos_coa_entry_hash CHECK (
        source_row_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_coa_entry_release
    ON eos_coa_entry (definition_release_id, hierarchy_level, account_code);

CREATE INDEX IF NOT EXISTS ix_eos_coa_entry_semantic
    ON eos_coa_entry (semantic_key, scope_type, owner_tenant_id);

CREATE TABLE IF NOT EXISTS eos_coa_code_identity (
    identity_id UUID PRIMARY KEY,
    scope_type VARCHAR(8) NOT NULL,
    owner_tenant_id VARCHAR(128) NULL,
    chart_profile VARCHAR(64) NOT NULL,
    account_code VARCHAR(8) NOT NULL,
    semantic_key VARCHAR(128) NOT NULL,
    first_release_id UUID NOT NULL,
    state VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_eos_coa_identity_release
        FOREIGN KEY (first_release_id)
        REFERENCES eos_coa_definition_release (definition_release_id),
    CONSTRAINT ck_eos_coa_identity_scope CHECK (
        (scope_type = 'GLOBAL' AND owner_tenant_id IS NULL)
        OR (scope_type = 'TENANT' AND owner_tenant_id IS NOT NULL)
    ),
    CONSTRAINT ck_eos_coa_identity_code CHECK (
        account_code ~ '^[1-9][0-9]{7}$'
    ),
    CONSTRAINT ck_eos_coa_identity_state CHECK (
        state IN ('ACTIVE', 'RETIRED')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_global_identity_code
    ON eos_coa_code_identity (chart_profile, account_code)
    WHERE scope_type = 'GLOBAL';

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_global_identity_semantic
    ON eos_coa_code_identity (chart_profile, semantic_key)
    WHERE scope_type = 'GLOBAL';

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_tenant_identity_code
    ON eos_coa_code_identity (owner_tenant_id, chart_profile, account_code)
    WHERE scope_type = 'TENANT';

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_coa_tenant_identity_semantic
    ON eos_coa_code_identity (owner_tenant_id, chart_profile, semantic_key)
    WHERE scope_type = 'TENANT';

CREATE TABLE IF NOT EXISTS eos_coa_company_adoption (
    tenant_id VARCHAR(128) NOT NULL,
    adoption_id UUID NOT NULL,
    company_id UUID NOT NULL,
    global_release_id UUID NOT NULL,
    extension_release_id UUID NULL,
    effective_from DATE NOT NULL,
    effective_until DATE NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_coa_company_adoption PRIMARY KEY (tenant_id, adoption_id),
    CONSTRAINT fk_eos_coa_adoption_company
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_coa_adoption_global
        FOREIGN KEY (global_release_id)
        REFERENCES eos_coa_definition_release (definition_release_id),
    CONSTRAINT fk_eos_coa_adoption_extension
        FOREIGN KEY (extension_release_id)
        REFERENCES eos_coa_definition_release (definition_release_id),
    CONSTRAINT ck_eos_coa_adoption_period CHECK (
        effective_until IS NULL OR effective_until > effective_from
    ),
    CONSTRAINT ck_eos_coa_adoption_proof CHECK (
        approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_coa_adoption_state CHECK (
        state IN ('APPROVED', 'REVOKED', 'SUPERSEDED')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_coa_adoption_effective
    ON eos_coa_company_adoption (
        tenant_id, company_id, state, effective_from, effective_until
    );

CREATE TABLE IF NOT EXISTS eos_coa_account_binding (
    tenant_id VARCHAR(128) NOT NULL,
    binding_id UUID NOT NULL,
    adoption_id UUID NOT NULL,
    entry_id UUID NOT NULL,
    account_id UUID NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_coa_account_binding PRIMARY KEY (tenant_id, binding_id),
    CONSTRAINT fk_eos_coa_binding_adoption
        FOREIGN KEY (tenant_id, adoption_id)
        REFERENCES eos_coa_company_adoption (tenant_id, adoption_id),
    CONSTRAINT fk_eos_coa_binding_entry
        FOREIGN KEY (entry_id)
        REFERENCES eos_coa_entry (entry_id),
    CONSTRAINT fk_eos_coa_binding_account
        FOREIGN KEY (tenant_id, account_id)
        REFERENCES eos_account (tenant_id, account_id),
    CONSTRAINT ux_eos_coa_binding_entry
        UNIQUE (tenant_id, adoption_id, entry_id),
    CONSTRAINT ux_eos_coa_binding_account
        UNIQUE (tenant_id, adoption_id, account_id),
    CONSTRAINT ck_eos_coa_binding_proof CHECK (
        approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_coa_binding_account
    ON eos_coa_account_binding (tenant_id, account_id);

CREATE OR REPLACE FUNCTION eos_validate_coa_release_base()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    base_release eos_coa_definition_release%ROWTYPE;
BEGIN
    IF NEW.scope_type = 'TENANT' THEN
        SELECT * INTO base_release
        FROM eos_coa_definition_release
        WHERE definition_release_id = NEW.base_global_release_id;
        IF NOT FOUND
           OR base_release.scope_type <> 'GLOBAL'
           OR base_release.status <> 'PUBLISHED'
           OR base_release.chart_profile <> NEW.chart_profile THEN
            RAISE EXCEPTION 'invalid tenant COA base release'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_coa_release_base
    ON eos_coa_definition_release;
CREATE TRIGGER trg_eos_coa_release_base
BEFORE INSERT OR UPDATE OF scope_type, owner_tenant_id, base_global_release_id
ON eos_coa_definition_release
FOR EACH ROW
EXECUTE FUNCTION eos_validate_coa_release_base();

CREATE OR REPLACE FUNCTION eos_validate_coa_entry()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    release_row eos_coa_definition_release%ROWTYPE;
    parent_row eos_coa_entry%ROWTYPE;
    leaf_suffix INTEGER;
BEGIN
    SELECT * INTO release_row
    FROM eos_coa_definition_release
    WHERE definition_release_id = NEW.definition_release_id
    FOR UPDATE;
    IF NOT FOUND OR release_row.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'COA entries require a DRAFT release'
            USING ERRCODE = '23514';
    END IF;
    IF release_row.scope_type <> NEW.scope_type
       OR release_row.owner_tenant_id IS DISTINCT FROM NEW.owner_tenant_id THEN
        RAISE EXCEPTION 'COA entry scope differs from release'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.hierarchy_level = 1 THEN
        IF NEW.account_code !~ '^[1-9]0000000$'
           OR NEW.parent_entry_id IS NOT NULL OR NEW.is_postable THEN
            RAISE EXCEPTION 'invalid COA root' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.hierarchy_level = 2 THEN
        IF NEW.account_code !~ '^[1-9][0-9]{2}00000$'
           OR substring(NEW.account_code FROM 2 FOR 2) = '00' THEN
            RAISE EXCEPTION 'invalid COA group' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.hierarchy_level = 3 THEN
        IF NEW.account_code !~ '^[1-9][0-9]{4}000$'
           OR substring(NEW.account_code FROM 2 FOR 2) = '00'
           OR substring(NEW.account_code FROM 4 FOR 2) = '00' THEN
            RAISE EXCEPTION 'invalid COA family' USING ERRCODE = '23514';
        END IF;
    ELSE
        leaf_suffix := right(NEW.account_code, 3)::INTEGER;
        IF substring(NEW.account_code FROM 2 FOR 2) = '00'
           OR substring(NEW.account_code FROM 4 FOR 2) = '00'
           OR leaf_suffix = 0 THEN
            RAISE EXCEPTION 'invalid COA leaf' USING ERRCODE = '23514';
        END IF;
        IF NEW.scope_type = 'GLOBAL' AND leaf_suffix NOT BETWEEN 1 AND 699 THEN
            RAISE EXCEPTION 'GLOBAL COA leaf suffix is reserved'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.scope_type = 'TENANT' AND leaf_suffix NOT BETWEEN 800 AND 999 THEN
            RAISE EXCEPTION 'TENANT COA leaf suffix must be 800..999'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.hierarchy_level < 4 AND NEW.is_postable THEN
        RAISE EXCEPTION 'non-leaf COA entry cannot be postable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.hierarchy_level < 4 AND NEW.account_type <> 'ACCOUNT_GROUP' THEN
        RAISE EXCEPTION 'non-leaf COA entry must use ACCOUNT_GROUP'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.hierarchy_level = 4 AND NEW.account_type = 'ACCOUNT_GROUP' THEN
        RAISE EXCEPTION 'leaf COA entry cannot use ACCOUNT_GROUP'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.parent_entry_id IS NOT NULL THEN
        SELECT * INTO parent_row FROM eos_coa_entry
        WHERE entry_id = NEW.parent_entry_id;
        IF NOT FOUND OR parent_row.hierarchy_level <> NEW.hierarchy_level - 1
           OR parent_row.category <> NEW.category
           OR parent_row.account_code <> (CASE NEW.hierarchy_level
               WHEN 2 THEN left(NEW.account_code, 1) || '0000000'
               WHEN 3 THEN left(NEW.account_code, 3) || '00000'
               ELSE left(NEW.account_code, 5) || '000'
           END) THEN
            RAISE EXCEPTION 'invalid COA parent entry'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.scope_type = 'GLOBAL' AND
           parent_row.definition_release_id <> NEW.definition_release_id THEN
            RAISE EXCEPTION 'GLOBAL parent must belong to the same release'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.scope_type = 'TENANT' AND
           (parent_row.definition_release_id <> release_row.base_global_release_id
            OR parent_row.scope_type <> 'GLOBAL'
            OR parent_row.hierarchy_level <> 3
            OR left(parent_row.account_code, 5) <> left(NEW.account_code, 5)) THEN
            RAISE EXCEPTION 'TENANT parent must be a base GLOBAL family'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.hierarchy_level <> 1 THEN
        RAISE EXCEPTION 'non-root COA entry requires a parent'
            USING ERRCODE = '23514';
    END IF;

    IF (
        (NEW.category IN ('ASSET', 'EXPENSE') AND NOT NEW.is_contra
         AND NEW.normal_balance <> 'DR')
        OR (NEW.category IN ('ASSET', 'EXPENSE') AND NEW.is_contra
            AND NEW.normal_balance <> 'CR')
        OR (NEW.category IN ('LIABILITY', 'EQUITY', 'REVENUE')
            AND NOT NEW.is_contra AND NEW.normal_balance <> 'CR')
        OR (NEW.category IN ('LIABILITY', 'EQUITY', 'REVENUE')
            AND NEW.is_contra AND NEW.normal_balance <> 'DR')
    ) THEN
        RAISE EXCEPTION 'invalid COA category normal balance'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_coa_entry_validate ON eos_coa_entry;
CREATE TRIGGER trg_eos_coa_entry_validate
BEFORE INSERT OR UPDATE ON eos_coa_entry
FOR EACH ROW
EXECUTE FUNCTION eos_validate_coa_entry();

CREATE OR REPLACE FUNCTION eos_protect_published_coa_entry()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    release_status VARCHAR(16);
BEGIN
    SELECT status INTO release_status FROM eos_coa_definition_release
    WHERE definition_release_id = OLD.definition_release_id;
    IF release_status IN ('PUBLISHED', 'SUPERSEDED') THEN
        RAISE EXCEPTION 'published COA entry is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_coa_entry_immutable ON eos_coa_entry;
CREATE TRIGGER trg_eos_coa_entry_immutable
BEFORE UPDATE OR DELETE ON eos_coa_entry
FOR EACH ROW
EXECUTE FUNCTION eos_protect_published_coa_entry();

CREATE OR REPLACE FUNCTION eos_validate_coa_adoption()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    global_release eos_coa_definition_release%ROWTYPE;
    extension_release eos_coa_definition_release%ROWTYPE;
BEGIN
    SELECT * INTO global_release FROM eos_coa_definition_release
    WHERE definition_release_id = NEW.global_release_id;
    IF NOT FOUND OR global_release.scope_type <> 'GLOBAL'
       OR global_release.status <> 'PUBLISHED' THEN
        RAISE EXCEPTION 'adoption requires a published GLOBAL release'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.extension_release_id IS NOT NULL THEN
        SELECT * INTO extension_release FROM eos_coa_definition_release
        WHERE definition_release_id = NEW.extension_release_id;
        IF NOT FOUND OR extension_release.scope_type <> 'TENANT'
           OR extension_release.status <> 'PUBLISHED'
           OR extension_release.owner_tenant_id <> NEW.tenant_id
           OR extension_release.base_global_release_id <> NEW.global_release_id THEN
            RAISE EXCEPTION 'invalid tenant extension adoption'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.state = 'APPROVED' AND EXISTS (
        SELECT 1 FROM eos_coa_company_adoption existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.company_id = NEW.company_id
          AND existing.adoption_id <> NEW.adoption_id
          AND existing.state = 'APPROVED'
          AND (existing.effective_until IS NULL
               OR existing.effective_until > NEW.effective_from)
          AND (NEW.effective_until IS NULL
               OR existing.effective_from < NEW.effective_until)
    ) THEN
        RAISE EXCEPTION 'overlapping COA company adoption'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_coa_adoption_validate
    ON eos_coa_company_adoption;
CREATE TRIGGER trg_eos_coa_adoption_validate
BEFORE INSERT OR UPDATE ON eos_coa_company_adoption
FOR EACH ROW
EXECUTE FUNCTION eos_validate_coa_adoption();

CREATE OR REPLACE FUNCTION eos_validate_coa_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    adoption_row eos_coa_company_adoption%ROWTYPE;
    entry_row eos_coa_entry%ROWTYPE;
BEGIN
    SELECT * INTO adoption_row FROM eos_coa_company_adoption
    WHERE tenant_id = NEW.tenant_id AND adoption_id = NEW.adoption_id;
    SELECT * INTO entry_row FROM eos_coa_entry WHERE entry_id = NEW.entry_id;
    IF adoption_row.adoption_id IS NULL
       OR adoption_row.state <> 'APPROVED' THEN
        RAISE EXCEPTION 'binding requires approved adoption'
            USING ERRCODE = '23514';
    END IF;
    IF entry_row.entry_id IS NULL THEN
        RAISE EXCEPTION 'binding requires an existing COA entry'
            USING ERRCODE = '23514';
    END IF;
    IF entry_row.definition_release_id <> adoption_row.global_release_id
       AND entry_row.definition_release_id IS DISTINCT FROM
           adoption_row.extension_release_id THEN
        RAISE EXCEPTION 'binding entry is outside adoption releases'
            USING ERRCODE = '23514';
    END IF;
    IF entry_row.scope_type = 'TENANT'
       AND entry_row.owner_tenant_id <> NEW.tenant_id THEN
        RAISE EXCEPTION 'cross-tenant COA binding denied'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_coa_binding_validate
    ON eos_coa_account_binding;
CREATE TRIGGER trg_eos_coa_binding_validate
BEFORE INSERT OR UPDATE ON eos_coa_account_binding
FOR EACH ROW
EXECUTE FUNCTION eos_validate_coa_binding();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2518_eos_unified_coa',
    'EOS unified GLOBAL/TENANT COA definition, identity, adoption, and account binding foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
