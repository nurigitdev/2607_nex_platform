from pathlib import Path

from run_migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database/nex-ae-api/migrations"


def test_agent_context_migration_is_generation_based_and_lineage_scoped() -> None:
    sql = (MIGRATIONS / "2102_ae_agent_context.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_agent_context" in sql
    assert "ux_ae_agent_context_generation" in sql
    assert "fk_ae_agent_context_execution" in sql
    assert "fk_ae_agent_context_intent" in sql
    assert "context_json JSONB NOT NULL" in sql
    assert "context_hash ~ '^sha256:[0-9a-f]{64}$'" in sql
    assert "UPDATE ae_agent_context" not in sql


def test_agent_context_table_and_constraint_names_fit_postgres_limit() -> None:
    sql = (MIGRATIONS / "2102_ae_agent_context.sql").read_text(encoding="utf-8")
    names = [
        "ae_agent_context",
        "ux_ae_agent_context_generation",
        "fk_ae_agent_context_execution",
        "fk_ae_agent_context_intent",
        "ck_ae_agent_context_json_object",
        "ck_ae_agent_context_json_identity",
        "idx_ae_agent_context_execution",
        "idx_ae_agent_context_intent",
    ]

    assert all(name in sql for name in names)
    assert all(len(name) <= 63 for name in names)


def test_ae_migration_inventory_contains_ordered_p5_s2_context() -> None:
    versions = [item.version for item in load_migrations("nex-ae-api")]
    intent_index = versions.index("2101_ae_work_intent")

    assert versions[intent_index + 1] == "2102_ae_agent_context"
