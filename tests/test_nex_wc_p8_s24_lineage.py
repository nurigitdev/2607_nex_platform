from __future__ import annotations

from pathlib import Path

import pytest
from nex_wc.delegation_lineage import (
    DelegationLineageError,
    InMemoryDelegationLineageRepository,
    SqlAlchemyDelegationLineageRepository,
    initial_delegation_policy,
    validate_delegation_lineage,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]

WORK_ID = "23000000-0000-4000-8000-000000000001"
CHILD_ID = "23000000-0000-4000-8000-000000000002"
CLAIM_ID = "24000000-0000-4000-8000-000000000001"
AGENT_ID = "25000000-0000-4000-8000-000000000001"


def _lineage(*, nested: bool = False) -> dict[str, object]:
    policy = initial_delegation_policy()
    return {
        "schema_version": "wc_delegation_lineage.v1",
        "tenant_id": "tenant-p8",
        "work_item_id": CHILD_ID if nested else WORK_ID,
        "root_work_item_id": WORK_ID,
        "parent_work_item_id": WORK_ID if nested else None,
        "parent_claim_ref": CLAIM_ID if nested else None,
        "parent_claim_generation": 1 if nested else None,
        "delegating_agent_ref": {"agent_id": AGENT_ID, "agent_type": "PA"},
        "parent_agent_execution_id": "agent-execution-p8-parent-001",
        "delegation_depth": 2 if nested else 1,
        "policy_ref": policy["policy_ref"],
        "policy_hash": policy["policy_hash"],
        "created_at": "2026-10-21T12:00:00Z",
    }


def test_s24_policy_is_deterministic_and_governance_controlled():
    first = initial_delegation_policy()
    second = initial_delegation_policy()
    assert first == second
    assert first["max_delegation_depth"] == 10
    assert first["max_children_per_work_item"] == 5
    assert first["max_descendants_per_root"] == 50
    assert first["cycle_detection"] is True
    assert first["llm_overridable"] is False
    assert first["policy_hash"].startswith("sha256:")


def test_s24_in_memory_repository_is_immutable_and_historical_rows_are_valid():
    repository = InMemoryDelegationLineageRepository()
    assert repository.get(tenant_id="tenant-p8", work_item_id=WORK_ID) is None

    saved, created = repository.create(_lineage())
    replayed, replay_created = repository.create(_lineage())
    assert created is True
    assert replay_created is False
    assert saved == replayed == repository.get(
        tenant_id="tenant-p8", work_item_id=WORK_ID
    )

    changed = _lineage()
    changed["parent_agent_execution_id"] = "different-execution"
    with pytest.raises(DelegationLineageError) as conflict:
        repository.create(changed)
    assert conflict.value.error_code == "wc.delegation_lineage_conflict"
    assert conflict.value.status_code == 409
    assert str(conflict.value).startswith("Delegation lineage is immutable")


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(extra=True),
        lambda value: value.pop("tenant_id"),
        lambda value: value.update(schema_version="v2"),
        lambda value: value.update(work_item_id="not-a-uuid"),
        lambda value: value.update(tenant_id=""),
        lambda value: value.update(parent_agent_execution_id=""),
        lambda value: value.update(delegating_agent_ref={"agent_id": AGENT_ID}),
        lambda value: value.update(delegating_agent_ref={"agent_id": AGENT_ID, "agent_type": "XX"}),
        lambda value: value.update(delegation_depth=True),
        lambda value: value.update(parent_claim_ref=CLAIM_ID),
        lambda value: value.update(root_work_item_id=CHILD_ID),
        lambda value: value.update(policy_ref="wc.delegation.guard.unknown"),
        lambda value: value.update(policy_hash="bad"),
        lambda value: value.update(created_at=""),
    ),
)
def test_s24_invalid_lineage_fails_closed(mutate):
    lineage = _lineage()
    mutate(lineage)
    with pytest.raises(DelegationLineageError) as invalid:
        validate_delegation_lineage(lineage)
    assert invalid.value.error_code == "wc.delegation_lineage_invalid"


def test_s24_non_mapping_lineage_fails_closed():
    with pytest.raises(DelegationLineageError):
        validate_delegation_lineage(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(parent_claim_ref=None),
        lambda value: value.update(parent_claim_generation=0),
        lambda value: value.update(delegation_depth=1),
        lambda value: value.update(root_work_item_id=CHILD_ID),
    ),
)
def test_s24_nested_lineage_requires_complete_parent_authority(mutate):
    lineage = _lineage(nested=True)
    mutate(lineage)
    with pytest.raises(DelegationLineageError):
        validate_delegation_lineage(lineage)


def test_s24_sqlalchemy_repository_round_trip_and_conflict():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE wc_delegation_lineage (
                tenant_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL,
                root_work_item_id TEXT NOT NULL,
                parent_work_item_id TEXT NULL,
                parent_claim_ref TEXT NULL,
                parent_claim_generation INTEGER NULL,
                delegating_agent_id TEXT NOT NULL,
                delegating_agent_type TEXT NOT NULL,
                parent_agent_execution_id TEXT NOT NULL,
                delegation_depth INTEGER NOT NULL,
                policy_ref TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, work_item_id)
            )
        """))
    repository = SqlAlchemyDelegationLineageRepository(sessions)
    try:
        assert repository.get(tenant_id="tenant-p8", work_item_id=WORK_ID) is None
        saved, created = repository.create(_lineage(nested=True))
        replayed, replay_created = repository.create(_lineage(nested=True))
        assert created is True
        assert replay_created is False
        assert saved == replayed
        assert saved["delegation_depth"] == 2

        changed = _lineage(nested=True)
        changed["policy_hash"] = "sha256:" + "f" * 64
        with pytest.raises(DelegationLineageError) as conflict:
            repository.create(changed)
        assert conflict.value.error_code == "wc.delegation_lineage_conflict"
    finally:
        engine.dispose()


def test_s24_sqlalchemy_repository_rejects_missing_reload():
    class Result:
        rowcount = 1

        def mappings(self):
            return self

        def first(self):
            return None

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

        def commit(self):
            raise AssertionError("missing reload must fail before commit")

    repository = SqlAlchemyDelegationLineageRepository(lambda: Session())
    with pytest.raises(DelegationLineageError) as conflict:
        repository.create(_lineage())
    assert conflict.value.error_code == "wc.delegation_lineage_write_conflict"
    assert conflict.value.retryable is True


def test_s24_sqlalchemy_repository_maps_store_failures():
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("offline"))

    repository = SqlAlchemyDelegationLineageRepository(lambda: BrokenSession())
    with pytest.raises(DelegationLineageError) as create_error:
        repository.create(_lineage())
    assert create_error.value.status_code == 503
    assert create_error.value.retryable is True

    with pytest.raises(DelegationLineageError) as get_error:
        repository.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    assert get_error.value.error_code == "wc.delegation_lineage_store_unavailable"


def test_s24_migration_is_current_and_preserves_existing_wc_tables():
    migrations = load_migrations("nex-wc")
    inventory = sorted(
        path.stem for path in (ROOT / "database/nex-wc/migrations").glob("*.sql")
    )
    assert [migration.version for migration in migrations] == inventory
    sql = next(
        migration.sql
        for migration in migrations
        if migration.version == "1004_wc_delegation_lineage"
    )
    assert "CREATE TABLE IF NOT EXISTS wc_delegation_lineage" in sql
    assert "ALTER TABLE wc_work_item" not in sql
    assert "ALTER TABLE wc_claim" not in sql
    assert "ALTER TABLE wc_assignment" not in sql
    assert "ck_wc_dl_parent_shape" in sql
    assert max(
        len(name)
        for name in (
            "wc_delegation_lineage",
            "fk_wc_dl_parent_claim",
            "ix_wc_dl_root_depth",
            "ix_wc_dl_parent",
        )
    ) < 63
