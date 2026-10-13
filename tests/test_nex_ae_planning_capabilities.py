from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.planning_capabilities as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.planning_capabilities import (
    DEFAULT_P5_CAPABILITIES,
    CapabilitySnapshotError,
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
    capability_by_exact_version,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "docs/transition/P5/contracts/p5-capability-snapshot-v1.1.schema.json"
)
TENANT = "tenant-p5"
SNAPSHOT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
NOW = "2026-10-13T09:00:00Z"


def _snapshot(**overrides):
    values = {
        "tenant_id": TENANT,
        "capability_snapshot_id": SNAPSHOT_ID,
        "snapshot_version": 1,
        "created_at": NOW,
    }
    return build_capability_snapshot(**{**values, **overrides})


def _factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_capability_snapshot (
                    tenant_id TEXT NOT NULL,
                    capability_snapshot_id TEXT NOT NULL,
                    snapshot_version INTEGER NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, capability_snapshot_id),
                    UNIQUE (tenant_id, snapshot_version)
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _rehash(snapshot):
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )
    return snapshot


def test_builder_is_canonical_contract_valid_and_exact_versioned() -> None:
    snapshot = _snapshot(capabilities=tuple(reversed(DEFAULT_P5_CAPABILITIES)))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(snapshot)

    assert [item["capability_id"] for item in snapshot["capabilities"]] == [
        "AE.CHAT.COMPATIBILITY",
        "AE.RESULT.REPORT",
    ]
    assert snapshot["created_at"] == NOW
    assert capability_by_exact_version(
        snapshot, "AE.CHAT.COMPATIBILITY", "p5.1"
    )["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY"
    with pytest.raises(CapabilitySnapshotError) as exc_info:
        capability_by_exact_version(snapshot, "AE.CHAT.COMPATIBILITY", "latest")
    assert exc_info.value.error_code == "ae.capability_exact_version_unavailable"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda caps: [],
        lambda caps: list(caps) * 33,
        lambda caps: [caps[0], caps[0]],
        lambda caps: [{**caps[0], "unexpected": True}],
        lambda caps: [{**caps[0], "capability_id": "bad"}],
        lambda caps: [{**caps[0], "status": "DISABLED"}],
        lambda caps: [{**caps[0], "allowed_logical_step_types": []}],
        lambda caps: [
            {**caps[0], "allowed_logical_step_types": ["LOCAL_CAPABILITY"] * 2}
        ],
        lambda caps: [
            {**caps[0], "allowed_logical_step_types": ["DELEGATE_WORK"]}
        ],
        lambda caps: [{**caps[0], "executable_step_type": "UNKNOWN"}],
        lambda caps: [{**caps[0], "executor_kind": "UNKNOWN"}],
        lambda caps: [{**caps[0], "operation_semantics": "WRITE"}],
    ],
)
def test_builder_rejects_invalid_capability_catalog(mutator) -> None:
    with pytest.raises(CapabilitySnapshotError) as exc_info:
        _snapshot(capabilities=mutator(copy.deepcopy(DEFAULT_P5_CAPABILITIES)))
    assert exc_info.value.error_code == "ae.capability_snapshot_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1.0"),
        ("tenant_id", ""),
        ("capability_snapshot_id", "bad"),
        ("snapshot_version", True),
        ("created_at", "2026-10-13"),
        ("snapshot_hash", "sha256:bad"),
    ],
)
def test_repository_rejects_invalid_snapshot_fields(field, value) -> None:
    snapshot = _snapshot()
    snapshot[field] = value
    if field not in {"snapshot_hash", "schema_version"}:
        _rehash(snapshot)

    with pytest.raises(CapabilitySnapshotError):
        SqlAlchemyCapabilitySnapshotRepository(_factory()).save(snapshot)


def test_repository_rejects_noncanonical_fields_order_and_hash_mismatch() -> None:
    repository = SqlAlchemyCapabilitySnapshotRepository(_factory())
    extra = {**_snapshot(), "private": "forbidden"}
    unordered = _snapshot()
    unordered["capabilities"] = list(reversed(unordered["capabilities"]))
    _rehash(unordered)
    mismatched = _snapshot()
    mismatched["tenant_id"] = "other"

    for value in (extra, unordered, mismatched):
        with pytest.raises(CapabilitySnapshotError):
            repository.save(value)


def test_repository_is_idempotent_immutable_versioned_and_restart_safe() -> None:
    factory = _factory()
    repository = SqlAlchemyCapabilitySnapshotRepository(factory)
    snapshot = _snapshot()

    assert repository.get(tenant_id=TENANT, capability_snapshot_id=SNAPSHOT_ID) is None
    assert repository.save(snapshot) == snapshot
    assert repository.save(snapshot) == snapshot
    assert (
        SqlAlchemyCapabilitySnapshotRepository(factory).get(
            tenant_id=TENANT, capability_snapshot_id=SNAPSHOT_ID
        )
        == snapshot
    )

    changed = _snapshot(
        capabilities=[
            {**DEFAULT_P5_CAPABILITIES[0], "operation_semantics": "READ"},
            DEFAULT_P5_CAPABILITIES[1],
        ]
    )
    with pytest.raises(CapabilitySnapshotError) as immutable:
        repository.save(changed)
    assert immutable.value.error_code == "ae.capability_snapshot_immutable_conflict"

    with pytest.raises(CapabilitySnapshotError) as version:
        repository.save(_snapshot(capability_snapshot_id=OTHER_ID))
    assert version.value.error_code == "ae.capability_snapshot_version_conflict"


def test_repository_wraps_store_failures_and_validates_lookup_identity() -> None:
    repository = SqlAlchemyCapabilitySnapshotRepository(_factory(with_schema=False))

    with pytest.raises(CapabilitySnapshotError) as save_error:
        repository.save(_snapshot())
    assert save_error.value.error_code == "ae.capability_snapshot_store_unavailable"
    assert save_error.value.retryable is True

    with pytest.raises(CapabilitySnapshotError) as get_error:
        repository.get(tenant_id=TENANT, capability_snapshot_id=SNAPSHOT_ID)
    assert get_error.value.error_code == "ae.capability_snapshot_store_unavailable"

    with pytest.raises(CapabilitySnapshotError):
        repository.get(tenant_id="", capability_snapshot_id=SNAPSHOT_ID)
    assert str(get_error.value) == "AE capability snapshot store is unavailable."


def test_repository_surfaces_unreloadable_write_conflict(monkeypatch) -> None:
    monkeypatch.setattr(module, "_load_snapshot", lambda *args: None)
    monkeypatch.setattr(module, "_load_snapshot_by_version", lambda *args: None)

    with pytest.raises(CapabilitySnapshotError) as exc_info:
        SqlAlchemyCapabilitySnapshotRepository(_factory()).save(_snapshot())

    assert exc_info.value.error_code == "ae.capability_snapshot_write_conflict"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(capabilities="bad"),
        lambda value: value.update(
            capabilities=[value["capabilities"][0], value["capabilities"][0]]
        ),
        lambda value: value.update(capability_snapshot_id=None),
        lambda value: value.update(created_at=None),
        lambda value: value.update(created_at="not-a-date"),
        lambda value: value.update(tenant_id=float("nan")),
    ],
)
def test_internal_snapshot_validator_fail_closes_contract_families(mutator) -> None:
    snapshot = _snapshot()
    mutator(snapshot)
    try:
        _rehash(snapshot)
    except ValueError:
        pass
    with pytest.raises(CapabilitySnapshotError):
        module._validate_snapshot(snapshot)
