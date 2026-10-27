from __future__ import annotations

from datetime import UTC, datetime, timedelta

import nex_wa.work_assets as asset_module
import pytest
from nex_wa import (
    SqlAlchemyWorkAssetRepository,
    WorkAssetBindingInput,
    WorkAssetError,
    WorkAssetInput,
    build_work_asset,
    deterministic_work_asset_id,
)
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
PROJECT_REF = "31a501cb-ff0d-472a-97f0-8d6424178b55"
PRIMARY_ID = "3e8f73dc-af9e-4d5d-b17f-a11785fb7770"
SUPPORTING_ID = "f20212b9-2711-49aa-bfd8-874fc1a0777a"


def _binding(evidence_id: str, role: str) -> WorkAssetBindingInput:
    return WorkAssetBindingInput(evidence_id, role)


def _agent_candidate(**overrides: object) -> WorkAssetInput:
    values: dict[str, object] = {
        "tenant_id": "VO00",
        "asset_type": "AGENT_EXECUTION_RESULT",
        "agent_execution_id": "execution-100",
        "actor_type": "AGENT",
        "actor_ref": "agent-100",
        "agent_type_snapshot": "CA",
        "project_ref": PROJECT_REF,
        "occurred_at": NOW,
        "classification": "CONFIDENTIAL",
        "bindings": (_binding(PRIMARY_ID, "PRIMARY"),),
    }
    values.update(overrides)
    return WorkAssetInput(**values)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SqlAlchemyWorkAssetRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE wa_work_evidence (
                    tenant_id TEXT NOT NULL,
                    work_evidence_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, work_evidence_id)
                );
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE wa_work_asset (
                    tenant_id TEXT NOT NULL,
                    work_asset_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    agent_type_snapshot TEXT,
                    project_ref TEXT,
                    occurred_at TIMESTAMP NOT NULL,
                    classification TEXT NOT NULL,
                    asset_status TEXT NOT NULL,
                    asset_hash TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (tenant_id, work_asset_id)
                );
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE wa_work_asset_evidence (
                    tenant_id TEXT NOT NULL,
                    work_asset_id TEXT NOT NULL,
                    work_evidence_id TEXT NOT NULL,
                    binding_role TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (tenant_id, work_asset_id, work_evidence_id),
                    FOREIGN KEY (tenant_id, work_asset_id)
                        REFERENCES wa_work_asset (tenant_id, work_asset_id),
                    FOREIGN KEY (tenant_id, work_evidence_id)
                        REFERENCES wa_work_evidence (tenant_id, work_evidence_id)
                );
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO wa_work_evidence (tenant_id, work_evidence_id) "
                "VALUES ('VO00', :primary), ('VO00', :supporting), "
                "('OTHER', :primary)"
            ),
            {"primary": PRIMARY_ID, "supporting": SUPPORTING_ID},
        )
    return SqlAlchemyWorkAssetRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
        clock=lambda: NOW + timedelta(seconds=1),
    )


def test_agent_and_human_asset_identity_are_type_specific_and_deterministic() -> None:
    agent = _agent_candidate()
    human = WorkAssetInput(
        tenant_id="VO00",
        asset_type="HUMAN_OWNED_ARTIFACT",
        artifact_id="artifact-1",
        artifact_version_id="version-1",
        actor_type="HUMAN",
        actor_ref="subject-1",
        occurred_at=NOW,
        classification="CONFIDENTIAL",
        bindings=(_binding(PRIMARY_ID, "PRIMARY"),),
    )

    assert deterministic_work_asset_id(agent) == deterministic_work_asset_id(agent)
    assert deterministic_work_asset_id(agent) != deterministic_work_asset_id(human)
    assert deterministic_work_asset_id(human) == deterministic_work_asset_id(human)


def test_asset_hash_is_binding_order_independent_and_excludes_runtime_fields() -> None:
    bindings = (
        _binding(SUPPORTING_ID, "SUPPORTING"),
        _binding(PRIMARY_ID, "PRIMARY"),
    )
    first = build_work_asset(
        _agent_candidate(bindings=bindings),
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    replay = build_work_asset(
        _agent_candidate(bindings=tuple(reversed(bindings))),
        version=9,
        created_at=NOW + timedelta(days=1),
        updated_at=NOW + timedelta(days=2),
    )

    assert first.asset_hash == replay.asset_hash
    assert first.work_asset_id == replay.work_asset_id
    assert [item.binding_role for item in first.bindings] == ["PRIMARY", "SUPPORTING"]
    assert first.version != replay.version


@pytest.mark.parametrize("version", (0, -1, True))
def test_asset_version_must_be_a_positive_integer(version: object) -> None:
    with pytest.raises(WorkAssetError) as error:
        build_work_asset(_agent_candidate(), version=version)  # type: ignore[arg-type]
    assert error.value.error_code == "WA_ASSET_INVALID"


@pytest.mark.parametrize(
    ("candidate", "error_code"),
    (
        (_agent_candidate(agent_execution_id=None), "WA_ASSET_INVALID"),
        (_agent_candidate(artifact_id="wrong"), "WA_ASSET_INVALID"),
        (_agent_candidate(asset_type="UNKNOWN"), "WA_ASSET_INVALID"),
        (_agent_candidate(bindings=()), "WA_ASSET_PRIMARY_INVALID"),
        (
            _agent_candidate(
                bindings=(
                    _binding(PRIMARY_ID, "PRIMARY"),
                    _binding(SUPPORTING_ID, "PRIMARY"),
                )
            ),
            "WA_ASSET_PRIMARY_INVALID",
        ),
        (
            _agent_candidate(
                bindings=(
                    _binding(PRIMARY_ID, "PRIMARY"),
                    _binding(PRIMARY_ID, "SUPPORTING"),
                )
            ),
            "WA_ASSET_INVALID",
        ),
        (_agent_candidate(project_ref="bad"), "WA_ASSET_INVALID"),
        (_agent_candidate(occurred_at=NOW.replace(tzinfo=None)), "WA_ASSET_INVALID"),
        (_agent_candidate(classification="PUBLIC"), "WA_ASSET_INVALID"),
        (_agent_candidate(asset_status="DELETED"), "WA_ASSET_INVALID"),
    ),
)
def test_asset_validation_fails_closed(
    candidate: WorkAssetInput,
    error_code: str,
) -> None:
    with pytest.raises(WorkAssetError) as error:
        build_work_asset(candidate)
    assert error.value.error_code == error_code


def test_human_asset_rejects_agent_identity() -> None:
    candidate = WorkAssetInput(
        tenant_id="VO00",
        asset_type="HUMAN_OWNED_ARTIFACT",
        artifact_id="artifact-1",
        artifact_version_id="version-1",
        agent_execution_id="wrong",
        actor_type="HUMAN",
        actor_ref="subject-1",
        occurred_at=NOW,
        classification="CONFIDENTIAL",
        bindings=(_binding(PRIMARY_ID, "PRIMARY"),),
    )
    with pytest.raises(WorkAssetError, match="cannot carry agent identity"):
        build_work_asset(candidate)


def test_repository_exact_replay_and_material_change_versioning(
    repository: SqlAlchemyWorkAssetRepository,
) -> None:
    first = repository.create_or_update(_agent_candidate())
    replay = repository.create_or_update(_agent_candidate())
    changed = repository.create_or_update(
        _agent_candidate(
            bindings=(
                _binding(PRIMARY_ID, "PRIMARY"),
                _binding(SUPPORTING_ID, "SUPPORTING"),
            )
        )
    )
    repeated_change = repository.create_or_update(
        _agent_candidate(
            bindings=(
                _binding(SUPPORTING_ID, "SUPPORTING"),
                _binding(PRIMARY_ID, "PRIMARY"),
            )
        )
    )

    assert first.version == 1
    assert replay == first
    assert changed.version == 2
    assert changed.asset_hash != first.asset_hash
    assert repeated_change == changed
    assert repository.get("VO00", first.work_asset_id) == changed


def test_evidence_is_asset_relative_and_tenant_aligned(
    repository: SqlAlchemyWorkAssetRepository,
) -> None:
    agent_asset = repository.create_or_update(
        _agent_candidate(
            bindings=(
                _binding(PRIMARY_ID, "PRIMARY"),
                _binding(SUPPORTING_ID, "SUPPORTING"),
            )
        )
    )
    human_asset = repository.create_or_update(
        WorkAssetInput(
            tenant_id="VO00",
            asset_type="HUMAN_OWNED_ARTIFACT",
            artifact_id="artifact-1",
            artifact_version_id="version-1",
            actor_type="HUMAN",
            actor_ref="subject-1",
            occurred_at=NOW,
            classification="CONFIDENTIAL",
            bindings=(_binding(SUPPORTING_ID, "PRIMARY"),),
        )
    )
    assert agent_asset.bindings[1].binding_role == "SUPPORTING"
    assert human_asset.bindings[0].binding_role == "PRIMARY"

    with pytest.raises(WorkAssetError) as mismatch:
        repository.create_or_update(
            _agent_candidate(
                tenant_id="OTHER",
                agent_execution_id="execution-other",
                bindings=(_binding(SUPPORTING_ID, "PRIMARY"),),
            )
        )
    assert mismatch.value.error_code == "WA_ASSET_EVIDENCE_INVALID"


def test_inactive_asset_may_have_no_primary_but_never_multiple_primary() -> None:
    inactive = build_work_asset(
        _agent_candidate(asset_status="INVALIDATED", bindings=()),
        created_at=NOW,
        updated_at=NOW,
    )
    assert inactive.bindings == ()
    with pytest.raises(WorkAssetError) as error:
        build_work_asset(
            _agent_candidate(
                asset_status="INVALIDATED",
                bindings=(
                    _binding(PRIMARY_ID, "PRIMARY"),
                    _binding(SUPPORTING_ID, "PRIMARY"),
                ),
            )
        )
    assert error.value.error_code == "WA_ASSET_PRIMARY_INVALID"


def test_repository_failure_modes_are_typed_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.rolled_back = False
            self.closed = False

        def execute(self, *_args, **_kwargs):
            return type("Result", (), {"rowcount": 0})()

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

        def get_bind(self):
            return None

    session = Session()
    repository = SqlAlchemyWorkAssetRepository(  # type: ignore[arg-type]
        lambda: session,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(repository, "_require_evidence", lambda *_args: None)

    stale = build_work_asset(
        _agent_candidate(classification="INTERNAL"),
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(repository, "_select_asset", lambda *_args: stale)
    with pytest.raises(WorkAssetError) as concurrent:
        repository.create_or_update(_agent_candidate())
    assert concurrent.value.error_code == "WA_ASSET_CONCURRENT_UPDATE"
    assert session.rolled_back and session.closed

    for failure, expected_code in (
        (IntegrityError("insert", {}, Exception("constraint")), "WA_ASSET_INTEGRITY_CONFLICT"),
        (SQLAlchemyError("offline"), "WA_ASSET_STORE_UNAVAILABLE"),
    ):
        current = Session()
        failing_repository = SqlAlchemyWorkAssetRepository(  # type: ignore[arg-type]
            lambda value=current: value,
            clock=lambda: NOW,
        )
        monkeypatch.setattr(
            failing_repository,
            "_require_evidence",
            lambda *_args, value=failure: (_ for _ in ()).throw(value),
        )
        with pytest.raises(WorkAssetError) as mapped:
            failing_repository.create_or_update(_agent_candidate())
        assert mapped.value.error_code == expected_code
        assert current.rolled_back and current.closed


def test_missing_post_commit_readback_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    repository = SqlAlchemyWorkAssetRepository(  # type: ignore[arg-type]
        lambda: Session(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(repository, "_require_evidence", lambda *_args: None)
    monkeypatch.setattr(repository, "_select_asset", lambda *_args: None)
    monkeypatch.setattr(repository, "_insert_asset", lambda *_args: None)
    monkeypatch.setattr(repository, "_replace_bindings", lambda *_args: None)

    with pytest.raises(WorkAssetError) as error:
        repository.create_or_update(_agent_candidate())
    assert error.value.error_code == "WA_ASSET_STORE_UNAVAILABLE"


def test_stored_timestamp_variants_and_corruption_fail_closed(
    repository: SqlAlchemyWorkAssetRepository,
) -> None:
    stored = repository.create_or_update(_agent_candidate())
    session_factory = repository._session_factory
    with session_factory.begin() as session:
        session.execute(
            text(
                "UPDATE wa_work_asset SET occurred_at='invalid' "
                "WHERE tenant_id='VO00' AND work_asset_id=:work_asset_id"
            ),
            {"work_asset_id": stored.work_asset_id},
        )
    with pytest.raises(WorkAssetError) as corrupted:
        repository.get("VO00", stored.work_asset_id)
    assert corrupted.value.error_code == "WA_ASSET_STORE_UNAVAILABLE"

    assert asset_module._row_timestamp(NOW.replace(tzinfo=None)).endswith("Z")
    with pytest.raises(WorkAssetError) as invalid_type:
        asset_module._row_timestamp(7)
    assert invalid_type.value.error_code == "WA_ASSET_STORE_UNAVAILABLE"
