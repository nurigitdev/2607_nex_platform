BEGIN;

CREATE OR REPLACE FUNCTION eos_validate_coa_adoption()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    global_release eos_coa_definition_release%ROWTYPE;
    extension_release eos_coa_definition_release%ROWTYPE;
BEGIN
    -- Serialize adoption interval decisions for one tenant/company. A hash
    -- collision only over-serializes unrelated companies; it cannot weaken
    -- the overlap invariant.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':' || NEW.company_id::TEXT, 0)
    );

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

INSERT INTO schema_migrations (version, description)
VALUES (
    '2520_eos_coa_adoption_concurrency',
    'Serialize tenant-company COA adoption overlap decisions'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
