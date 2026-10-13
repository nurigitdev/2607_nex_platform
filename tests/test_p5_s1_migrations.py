from __future__ import annotations

import re
from pathlib import Path

from run_migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = ROOT / "database/nex-ae-api/migrations"


def _sql(name: str) -> str:
    return (MIGRATION_ROOT / name).read_text(encoding="utf-8")


def test_prompt_hardening_migration_has_atomic_history_constraints() -> None:
    sql = _sql("2100_ae_prompt_registry_hardening.sql")

    assert "CREATE TABLE IF NOT EXISTS ae_prompt_binding_history" in sql
    assert "old_prompt_template_version_id" in sql
    assert "new_prompt_template_version_id" in sql
    assert "ux_ae_prompt_binding_history_correlation" in sql
    assert "idx_ae_prompt_binding_history_key_time" in sql
    assert "old_prompt_template_version_id <> new_prompt_template_version_id" in sql
    assert "2100_ae_prompt_registry_hardening" in sql


def test_work_intent_migration_is_immutable_revisioned_and_execution_scoped() -> None:
    sql = _sql("2101_ae_work_intent.sql")

    assert "CREATE TABLE IF NOT EXISTS ae_work_intent" in sql
    assert "ux_ae_work_intent_execution_revision" in sql
    assert "fk_ae_work_intent_execution" in sql
    assert "fk_ae_work_intent_supersedes" in sql
    assert "intent_hash ~ '^sha256:[0-9a-f]{64}$'" in sql
    assert "jsonb_typeof(intent_json) = 'object'" in sql
    assert "2101_ae_work_intent" in sql
    assert "UPDATE ae_work_intent" not in sql


def test_new_database_identifiers_remain_below_postgresql_limit() -> None:
    identifiers = re.findall(
        r"(?:CONSTRAINT|INDEX IF NOT EXISTS)\s+([a-z][a-z0-9_]*)",
        _sql("2100_ae_prompt_registry_hardening.sql")
        + _sql("2101_ae_work_intent.sql"),
        flags=re.IGNORECASE,
    )

    assert identifiers
    assert max(map(len, identifiers)) < 63


def test_ae_migration_inventory_ends_with_p5_s1_work_intent() -> None:
    migrations = load_migrations("nex-ae-api")

    assert migrations[-2].version == "2100_ae_prompt_registry_hardening"
    assert migrations[-1].version == "2101_ae_work_intent"
