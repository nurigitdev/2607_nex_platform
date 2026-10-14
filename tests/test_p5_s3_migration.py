from pathlib import Path

from run_migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "database/nex-ae-api/migrations/2103_ae_capability_plan_validation.sql"
)


def test_p5_s3_migration_has_exact_version_and_immutable_plan_storage() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_capability_snapshot" in sql
    assert "UNIQUE (tenant_id, snapshot_version)" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_agent_plan" in sql
    assert "UNIQUE (tenant_id, agent_execution_id, agent_plan_version)" in sql
    assert "REFERENCES ae_work_intent" in sql
    assert "REFERENCES ae_agent_context" in sql
    assert "REFERENCES ae_capability_snapshot" in sql
    assert "UPDATE ae_capability_snapshot" not in sql
    assert "UPDATE ae_agent_plan" not in sql


def test_p5_s3_migration_reserves_exact_validation_mapping_for_s4() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    statuses = {
        "VALID": "PROCEED_TO_COMPILE",
        "CLARIFICATION_REQUIRED": "WAIT_FOR_INPUT",
        "REPLAN_REQUIRED": "BLOCK_REPLAN_REQUIRED",
        "CONTEXT_REFRESH_REQUIRED": "BLOCK_CONTEXT_REFRESH_REQUIRED",
        "BLOCKED": "BLOCK_EXECUTION",
        "INVALID_TERMINAL": "FAIL_VALIDATION",
        "RETRYABLE_VALIDATION_FAILURE": "RETRY_VALIDATION_BOUNDED",
    }

    assert "CREATE TABLE IF NOT EXISTS ae_plan_validation" in sql
    for status, directive in statuses.items():
        assert status in sql
        assert directive in sql


def test_p5_s3_names_fit_postgres_and_migration_is_ordered() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    names = [
        "ae_capability_snapshot",
        "ux_ae_cap_snapshot_version",
        "ck_ae_cap_snapshot_json_identity",
        "ae_agent_plan",
        "ux_ae_agent_plan_execution_version",
        "fk_ae_agent_plan_execution",
        "fk_ae_agent_plan_intent",
        "fk_ae_agent_plan_context",
        "fk_ae_agent_plan_snapshot",
        "ck_ae_agent_plan_json_identity",
        "idx_ae_agent_plan_execution",
        "ae_plan_validation",
        "fk_ae_plan_validation_plan",
        "ck_ae_plan_validation_mapping",
        "ck_ae_plan_validation_json_identity",
        "idx_ae_plan_validation_plan_time",
    ]

    assert all(name in sql for name in names)
    assert all(len(name) <= 63 for name in names)
    versions = [migration.version for migration in load_migrations("nex-ae-api")]
    target = "2103_ae_capability_plan_validation"
    target_index = versions.index(target)

    assert versions == sorted(versions)
    assert target_index > 0
    assert target_index < len(versions) - 1
