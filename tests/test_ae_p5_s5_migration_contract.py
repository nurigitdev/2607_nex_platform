from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "database/nex-ae-api/migrations/2104_ae_executable_plan.sql"
STEPS = (
    ROOT / "database/nex-ae-api/migrations/2105_ae_executable_step_generalization.sql"
)


def test_executable_plan_migration_persists_semantic_envelope_and_lineage() -> None:
    sql = PLAN.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_executable_plan" in sql
    assert "UNIQUE (tenant_id, agent_execution_id, executable_plan_version)" in sql
    assert "FOREIGN KEY (tenant_id, agent_plan_id)" in sql
    assert "FOREIGN KEY (tenant_id, validation_result_id)" in sql
    assert "plan_json JSONB NOT NULL" in sql
    assert "plan_json ->> 'executable_plan_hash' = plan_hash" in sql
    assert "2104_ae_executable_plan" in sql


def test_step_generalization_preserves_p4_rows_and_adds_s_e_uuid_lineage() -> None:
    sql = STEPS.read_text(encoding="utf-8")

    assert "DROP CONSTRAINT IF EXISTS ux_ae_step_execution_kind" in sql
    assert "ADD COLUMN IF NOT EXISTS executable_plan_id UUID NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS logical_step_id TEXT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS compiled_step_key TEXT NULL" in sql
    assert "UNIQUE (tenant_id, executable_plan_id, compiled_step_key)" in sql
    assert "logical_step_id ~ '^S[0-9]{1,3}$'" in sql
    assert "compiled_step_key ~ '^E[0-9]{1,3}$'" in sql
    assert "executable_plan_id IS NULL" in sql
    assert "required_capability IS NULL" in sql
    assert "2105_ae_executable_step_generalization" in sql


def test_p5_s5_table_and_constraint_names_remain_operationally_short() -> None:
    names = (
        "ae_executable_plan",
        "ae_executable_step",
        "ux_ae_exec_plan_version",
        "fk_ae_exec_plan_execution",
        "fk_ae_exec_plan_agent_plan",
        "fk_ae_exec_plan_validation",
        "ck_ae_exec_plan_json_identity",
        "ck_ae_step_p5_shape",
        "ux_ae_step_plan_key",
    )

    assert all(len(name) <= 30 for name in names)
