from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2103_ae_capability_plan_validation.sql"


def test_plan_validation_persistence_has_exact_lineage_and_runtime_mapping() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "agent_plan_version INTEGER NOT NULL" in sql
    assert "agent_execution_id UUID NOT NULL" in sql
    assert "runtime_directive TEXT NOT NULL" in sql
    assert "fk_ae_plan_validation_plan" in sql
    assert "ck_ae_plan_validation_mapping" in sql
    assert "ck_ae_plan_validation_json_identity" in sql
    assert "UPDATE ae_plan_validation" not in sql


def test_plan_validation_migration_contains_all_seven_exact_pairs() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    pairs = {
        "VALID": "PROCEED_TO_COMPILE",
        "CLARIFICATION_REQUIRED": "WAIT_FOR_INPUT",
        "REPLAN_REQUIRED": "BLOCK_REPLAN_REQUIRED",
        "CONTEXT_REFRESH_REQUIRED": "BLOCK_CONTEXT_REFRESH_REQUIRED",
        "BLOCKED": "BLOCK_EXECUTION",
        "INVALID_TERMINAL": "FAIL_VALIDATION",
        "RETRYABLE_VALIDATION_FAILURE": "RETRY_VALIDATION_BOUNDED",
    }

    for status, directive in pairs.items():
        assert f"status = '{status}'" in sql
        assert f"runtime_directive = '{directive}'" in sql
