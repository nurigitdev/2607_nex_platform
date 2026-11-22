from __future__ import annotations

import re
from pathlib import Path

from run_migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / (
    "database/nex-ae-api/migrations/"
    "2517_ae_product_preparation_resume.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_generalizes_existing_wait_without_weakening_step_paths() -> None:
    sql = _sql()

    for required in (
        "resume_target_kind",
        "wait_contract_ref",
        "ALTER COLUMN executable_step_id DROP NOT NULL",
        "WORK_RESULT",
        "NSL_APPROVAL",
        "PRODUCT_PREPARATION",
        "EXECUTABLE_STEP",
        "PRODUCT_COORDINATOR",
        "ck_ae_wait_resume_target",
        "ck_ae_wait_contract_compat",
        "ck_ae_wait_nsl_approval_lineage",
    ):
        assert required in sql

    assert "SET resume_target_kind = 'EXECUTABLE_STEP'" in sql
    assert "wait_contract_ref = result_contract_ref" in sql
    assert "CREATE OR REPLACE FUNCTION ae_fill_wait_resume_projection()" in sql
    assert "BEFORE INSERT ON ae_wait_registration" in sql
    assert "NEW.wait_type IN ('WORK_RESULT', 'NSL_APPROVAL')" in sql
    assert "AND executable_step_id IS NOT NULL" in sql
    assert "AND executable_step_id IS NULL" in sql


def test_migration_generalizes_the_existing_event_inbox() -> None:
    sql = _sql()

    for required in (
        "ALTER TABLE ae_external_event_inbox",
        "event_family",
        "WORK_RESULT_SUBMITTED",
        "NSL_APPROVAL_DECIDED",
        "BUSINESS_APPROVAL_CHANGED",
        "ACCOUNTING_APPROVAL_CHANGED",
        "PRODUCT_PREPARATION",
        "ck_ae_external_event_family",
        "ck_ae_external_event_shape",
    ):
        assert required in sql

    assert "CREATE OR REPLACE FUNCTION ae_fill_event_family_projection()" in sql
    assert "BEFORE INSERT ON ae_external_event_inbox" in sql
    assert "WHEN 'WORK_RESULT_SUBMITTED' THEN 'WORK_RESULT'" in sql
    assert "WHEN 'NSL_APPROVAL_DECIDED' THEN 'NSL_APPROVAL'" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_product_prep_event_inbox" not in sql
    assert "CREATE TABLE IF NOT EXISTS ae_product_prep_job" not in sql


def test_migration_adds_only_checkpoint_and_typed_product_bindings() -> None:
    sql = _sql()
    created_tables = re.findall(
        r"CREATE TABLE IF NOT EXISTS\s+([a-z][a-z0-9_]*)", sql
    )

    assert created_tables == [
        "ae_product_prep_checkpoint",
        "ae_product_prep_wait_binding",
        "ae_product_prep_event_binding",
    ]
    assert "ae_product_prep_checkpoint_guard" in sql
    assert "Product Preparation checkpoints are append-only" in sql
    assert "Product Preparation wait bindings are immutable" in sql
    assert "Product Preparation event bindings are immutable" in sql
    assert "Product Preparation wait requires a typed binding" in sql
    assert "Product Preparation event requires a typed binding" in sql


def test_checkpoint_contract_is_hash_bound_and_version_chained() -> None:
    sql = _sql()

    for required in (
        "previous_checkpoint_id",
        "previous_checkpoint_hash",
        "work_intent_hash",
        "context_hash",
        "business_context_hash",
        "capability_registration_hash",
        "coordinator_registration_hash",
        "preparation_adapter_source_identity",
        "materializer_source_identity",
        "authority_refs JSONB",
        "checkpoint_projection JSONB",
        "checkpoint_hash",
        "ux_ae_product_prep_checkpoint_version",
        "ux_ae_product_prep_checkpoint_idempotency",
        "Product Preparation checkpoint lineage is invalid",
    ):
        assert required in sql

    assert "checkpoint_version + 1" in sql
    assert "checkpoint_projection ->> 'checkpoint_hash' = checkpoint_hash" in sql


def test_typed_binding_contracts_are_tenant_and_lineage_scoped() -> None:
    sql = _sql()

    for required in (
        "fk_ae_product_prep_wait_wait",
        "fk_ae_product_prep_wait_checkpoint",
        "fk_ae_product_prep_event_inbox",
        "fk_ae_product_prep_event_wait",
        "fk_ae_product_prep_event_checkpoint",
        "authority_kind IN ('BUSINESS_FORMAL', 'ACCOUNTING_REVIEW')",
        "event_row.event_type <> wait_binding_row.expected_event_type",
        "event_row.external_ref <> wait_binding_row.authority_ref",
        "checkpoint_row.stage_kind <> 'WAITING'",
    ):
        assert required in sql

    assert "DEFERRABLE INITIALLY DEFERRED" in sql


def test_new_postgresql_identifiers_fit_the_63_byte_limit() -> None:
    sql = _sql()
    identifiers = re.findall(
        r"(?:TABLE IF NOT EXISTS|CONSTRAINT|INDEX IF NOT EXISTS|"
        r"FUNCTION|TRIGGER)\s+([a-z][a-z0-9_]*)",
        sql,
        flags=re.IGNORECASE,
    )

    assert identifiers
    assert max(len(value.encode("utf-8")) for value in identifiers) <= 63


def test_migration_inventory_admits_2517_after_2516() -> None:
    versions = [item.version for item in load_migrations("nex-ae-api")]
    previous = versions.index("2516_ae_m1_work_intent")

    assert versions[previous + 1] == "2517_ae_product_preparation_resume"
    assert versions == sorted(versions)
    assert _sql().strip().endswith("COMMIT;")
