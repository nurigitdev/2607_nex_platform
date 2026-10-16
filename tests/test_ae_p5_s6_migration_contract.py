from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2106_ae_step_result.sql"


def test_step_result_migration_enforces_lineage_and_null_write_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_step_result" in sql
    assert "UNIQUE (tenant_id, executable_step_id)" in sql
    assert "FOREIGN KEY (tenant_id, executable_plan_id)" in sql
    assert "FOREIGN KEY (tenant_id, executable_step_id)" in sql
    assert "business_operation_id IS NULL" in sql
    assert "operation_fingerprint IS NULL" in sql
    assert "result_json -> 'business_operation_id' = 'null'::jsonb" in sql
    assert "2106_ae_step_result" in sql


def test_step_result_table_and_constraints_use_short_names() -> None:
    names = (
        "ae_step_result",
        "ux_ae_step_result_step",
        "fk_ae_step_result_execution",
        "fk_ae_step_result_plan",
        "fk_ae_step_result_step",
        "ck_ae_step_result_json_identity",
    )

    assert all(len(name) <= 32 for name in names)
