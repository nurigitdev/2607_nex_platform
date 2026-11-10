from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path

import psycopg
import pytest
from nex_eos import (
    EOS_COA_ACCOUNT_BINDING_TABLE,
    EOS_COA_CODE_IDENTITY_TABLE,
    EOS_COA_COMPANY_ADOPTION_TABLE,
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_ENTRY_TABLE,
    EOS_METADATA,
    CoaDefinitionReleaseInput,
    CoaEntryInput,
    EosUnifiedCoaError,
    SqlAlchemyEosUnifiedCoaRepository,
    build_eos_database_runtime,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "database/nex-eos/migrations/2518_eos_unified_coa.sql"
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_COA_02_POSTGRES_SMOKE") == "1"

RELEASE_ID = "c2000000-0000-4000-8000-000000000001"
ROOT_ID = "c3000000-0000-4000-8000-000000000001"
GROUP_ID = "c3000000-0000-4000-8000-000000000002"
FAMILY_ID = "c3000000-0000-4000-8000-000000000003"
LEAF_ID = "c3000000-0000-4000-8000-000000000004"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield engine, SqlAlchemyEosUnifiedCoaRepository(factory)
    engine.dispose()


def _release(**changes: object) -> CoaDefinitionReleaseInput:
    values: dict[str, object] = {
        "definition_release_id": RELEASE_ID,
        "scope_type": "GLOBAL",
        "chart_profile": "MYBEE-KIFRS",
        "release_version": "2026.01",
        "effective_from": date(2026, 1, 1),
        "source_reference": "domains/mybee/config/coa/codebook_candidate.v0.1.json",
        "source_hash": HASH_A,
        "approved_proof_ref": HASH_B,
        "content_hash": HASH_C,
        "created_by": "product-accounting-owner",
    }
    values.update(changes)
    return CoaDefinitionReleaseInput(**values)  # type: ignore[arg-type]


def _entries() -> list[CoaEntryInput]:
    common = {
        "category": "ASSET",
        "normal_balance": "DR",
        "is_contra": False,
        "is_monetary_default": True,
        "source_lineage": "codebook_candidate.v0.1",
        "source_row_hash": HASH_A,
    }
    return [
        CoaEntryInput(
            ROOT_ID,
            "10000000",
            "MB-COA-ASSET",
            "Assets",
            1,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            **common,
        ),
        CoaEntryInput(
            GROUP_ID,
            "10100000",
            "MB-COA-CURRENT-ASSET",
            "Current assets",
            2,
            parent_entry_id=ROOT_ID,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            **common,
        ),
        CoaEntryInput(
            FAMILY_ID,
            "10101000",
            "MB-COA-CASH-FAMILY",
            "Cash family",
            3,
            parent_entry_id=GROUP_ID,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            **common,
        ),
        CoaEntryInput(
            LEAF_ID,
            "10101001",
            "MB-COA-CASH",
            "Cash",
            4,
            parent_entry_id=FAMILY_ID,
            account_type="CASH",
            is_postable=True,
            **common,
        ),
    ]


def test_coa_02_migration_and_metadata_inventory_are_additive() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    expected = {
        "eos_coa_definition_release",
        "eos_coa_entry",
        "eos_coa_code_identity",
        "eos_coa_company_adoption",
        "eos_coa_account_binding",
    }
    assert expected <= set(EOS_METADATA.tables)
    for table_name in expected:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in migration
        assert len(table_name) <= 63
    assert "2518_eos_unified_coa" in migration
    assert "eos_account" in EOS_METADATA.tables
    assert EOS_COA_DEFINITION_RELEASE_TABLE.name in expected
    assert EOS_COA_ENTRY_TABLE.name in expected
    assert EOS_COA_CODE_IDENTITY_TABLE.name in expected
    assert EOS_COA_COMPANY_ADOPTION_TABLE.name in expected
    assert EOS_COA_ACCOUNT_BINDING_TABLE.name in expected


def test_coa_02_global_draft_persistence_read_and_exact_replay(repository) -> None:
    _engine, store = repository
    created = store.create_draft_release(release=_release(), entries=_entries())
    replayed = store.create_draft_release(release=_release(), entries=_entries())
    loaded = store.get_release(definition_release_id=RELEASE_ID)

    assert created["release"]["scope_type"] == "GLOBAL"
    assert [item["account_code"] for item in created["entries"]] == [
        "10000000",
        "10100000",
        "10101000",
        "10101001",
    ]
    assert replayed["release"]["definition_release_id"] == RELEASE_ID
    assert loaded is not None
    assert loaded["entries"][-1]["semantic_key"] == "MB-COA-CASH"
    assert store.get_release(definition_release_id=str(uuid.uuid4())) is None


def test_coa_02_replay_with_different_semantics_is_rejected(repository) -> None:
    _engine, store = repository
    store.create_draft_release(release=_release(), entries=_entries())
    changed = _entries()
    changed[-1] = replace(changed[-1], account_name="Changed cash")
    with pytest.raises(EosUnifiedCoaError) as raised:
        store.create_draft_release(release=_release(), entries=changed)
    assert raised.value.error_code == "EOS_COA_CONFLICT"
    assert raised.value.status_code == 409


def test_coa_02_replay_with_different_entry_count_is_rejected(repository) -> None:
    _engine, store = repository
    store.create_draft_release(release=_release(), entries=_entries())
    with pytest.raises(EosUnifiedCoaError, match="different entry count"):
        store.create_draft_release(release=_release(), entries=_entries()[:3])


def test_coa_02_database_identity_conflict_is_redacted(repository) -> None:
    _engine, store = repository
    store.create_draft_release(release=_release(), entries=_entries())
    with pytest.raises(EosUnifiedCoaError) as raised:
        store.create_draft_release(
            release=_release(
                definition_release_id=str(uuid.uuid4()),
                release_version="2026.02",
            ),
            entries=_entries(),
        )
    assert raised.value.error_code == "EOS_COA_CONFLICT"
    assert "identity already exists" in raised.value.detail


def test_coa_02_duplicate_entry_identity_is_rejected(repository) -> None:
    _engine, store = repository
    rows = _entries()
    rows.append(
        replace(
            rows[-1],
            account_code="10101002",
            semantic_key="MB-COA-CASH-SECONDARY",
        )
    )
    with pytest.raises(EosUnifiedCoaError, match="identity or code is duplicated"):
        store.create_draft_release(release=_release(), entries=rows)


def test_coa_02_persistence_failures_are_redacted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = SqlAlchemyEosUnifiedCoaRepository(sessionmaker(bind=engine))
    with pytest.raises(EosUnifiedCoaError) as create_error:
        store.create_draft_release(release=_release(), entries=_entries())
    assert create_error.value.error_code == "EOS_COA_PERSISTENCE_FAILED"
    with pytest.raises(EosUnifiedCoaError) as read_error:
        store.get_release(definition_release_id=RELEASE_ID)
    assert read_error.value.status_code == 503
    engine.dispose()


@pytest.mark.parametrize(
    ("release", "entries", "detail"),
    [
        (_release(status="PUBLISHED"), _entries(), "only admits DRAFT"),
        (_release(owner_tenant_id="tenant-a"), _entries(), "cannot have"),
        (
            _release(scope_type="TENANT", owner_tenant_id="tenant-a"),
            _entries(),
            "requires owner",
        ),
        (_release(source_hash="bad"), _entries(), "SHA-256"),
        (_release(definition_release_id="bad"), _entries(), "UUID"),
        (_release(created_by="bad id"), _entries(), "stable-reference"),
        (_release(chart_profile=""), _entries(), "1..64"),
        (_release(scope_type="UNKNOWN"), _entries(), "must be one of"),
        (_release(effective_from="2026-01-01"), _entries(), "must be a date"),
        (_release(), [], "must not be empty"),
    ],
)
def test_coa_02_release_boundary_rejections(release, entries, detail) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    store = SqlAlchemyEosUnifiedCoaRepository(sessionmaker(bind=engine))
    with pytest.raises(EosUnifiedCoaError, match=detail):
        store.create_draft_release(release=release, entries=entries)
    engine.dispose()


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (
            lambda rows: replace(rows[-1], semantic_key=rows[-2].semantic_key),
            "duplicated",
        ),
        (lambda rows: replace(rows[-1], semantic_key="bad"), "semantic-key"),
        (lambda rows: replace(rows[-1], account_code="bad"), "eight governed"),
        (lambda rows: replace(rows[-1], account_code="10101800"), "001..699"),
        (lambda rows: replace(rows[-1], hierarchy_level=3), "does not match"),
        (lambda rows: replace(rows[-1], hierarchy_level=True), "positive integer"),
        (lambda rows: replace(rows[-1], normal_balance="CR"), "must be DR"),
        (lambda rows: replace(rows[-1], is_contra="no"), "must be boolean"),
        (lambda rows: replace(rows[-1], is_postable=False), "true only"),
        (lambda rows: replace(rows[-1], account_type="ACCOUNT_GROUP"), "distinguish"),
        (lambda rows: replace(rows[0], parent_entry_id=GROUP_ID), "root"),
        (lambda rows: replace(rows[1], parent_entry_id=LEAF_ID), "must precede"),
        (lambda rows: replace(rows[-1], category="EXPENSE"), "hierarchy"),
    ],
)
def test_coa_02_entry_boundary_rejections(repository, mutate, detail) -> None:
    _engine, store = repository
    rows = _entries()
    target = mutate(rows)
    rows[target.hierarchy_level - 1 if target.hierarchy_level <= 4 else -1] = target
    if target.entry_id == LEAF_ID:
        rows[-1] = target
    elif target.entry_id == ROOT_ID:
        rows[0] = target
    elif target.entry_id == GROUP_ID:
        rows[1] = target
    with pytest.raises(EosUnifiedCoaError, match=detail):
        store.create_draft_release(release=_release(), entries=rows)


def test_coa_02_tenant_leaf_requires_a_global_parent(repository) -> None:
    _engine, store = repository
    tenant_release = _release(
        scope_type="TENANT",
        owner_tenant_id="tenant-a",
        base_global_release_id=str(uuid.uuid4()),
    )
    tenant_leaf = replace(
        _entries()[-1],
        account_code="10101800",
        semantic_key="MB-COA-TENANT-CASH",
        parent_entry_id=None,
    )
    with pytest.raises(EosUnifiedCoaError, match="requires GLOBAL family"):
        store.create_draft_release(release=tenant_release, entries=[tenant_leaf])


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected COA-02 EOS PostgreSQL smoke is disabled",
)
def test_coa_02_actual_postgres_migration_triggers_and_zero_residue() -> None:
    schema_name = f"mybee_coa02_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))

    scoped_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    )
    scoped_url = scoped_url.render_as_string(hide_password=False)
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2518_eos_unified_coa" in result.applied
        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        store = SqlAlchemyEosUnifiedCoaRepository(runtime.session_factory)
        stored = store.create_draft_release(release=_release(), entries=_entries())
        assert len(stored["entries"]) == 4

        with (
            pytest.raises(DBAPIError, match="scope differs from release"),
            runtime.engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "UPDATE eos_coa_entry SET scope_type = 'TENANT', "
                    "owner_tenant_id = 'tenant-a' WHERE entry_id = :entry_id"
                ),
                {"entry_id": LEAF_ID},
            )
        with (
            pytest.raises(DBAPIError, match="invalid COA parent entry"),
            runtime.engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "UPDATE eos_coa_entry SET account_code = '10201001' "
                    "WHERE entry_id = :entry_id"
                ),
                {"entry_id": LEAF_ID},
            )
        with runtime.engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM eos_coa_definition_release")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM eos_coa_entry")
            ).scalar_one() == 4
        runtime.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
