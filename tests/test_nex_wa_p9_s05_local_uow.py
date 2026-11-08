from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nex_wa import (
    WaEvidenceAdmissionService,
    WorkAdmissionError,
    WorkAssetBindingInput,
    WorkAssetError,
    WorkAssetInput,
    WorkEvidenceError,
    WorkEvidenceInput,
    deterministic_work_evidence_id,
)
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 27, 5, 0, tzinfo=UTC)
PROJECT_REF = "8b90b317-d783-4782-b0af-2a7c47bad5e4"


def _evidence(**overrides: object) -> WorkEvidenceInput:
    values: dict[str, object] = {
        "tenant_id": "VO00",
        "source_owner": "nex-ae-api",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "execution-500",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "5" * 64,
        "evidence_kind": "AGENT_EXECUTION_RESULT",
        "actor_type": "AGENT",
        "actor_ref": "agent-500",
        "agent_type_snapshot": "IA",
        "project_ref": PROJECT_REF,
        "occurred_at": NOW,
        "observed_at": NOW + timedelta(seconds=1),
        "classification": "CONFIDENTIAL",
    }
    values.update(overrides)
    return WorkEvidenceInput(**values)  # type: ignore[arg-type]


def _evidence_id(candidate: WorkEvidenceInput) -> str:
    return deterministic_work_evidence_id(
        tenant_id=candidate.tenant_id,
        source_type=candidate.source_type,
        source_ref=candidate.source_ref,
        source_revision_ref=candidate.source_revision_ref,
    )


def _asset(
    evidence_id: str,
    *,
    tenant_id: str = "VO00",
    supporting_id: str | None = None,
) -> WorkAssetInput:
    bindings = [WorkAssetBindingInput(evidence_id, "PRIMARY")]
    if supporting_id is not None:
        bindings.append(WorkAssetBindingInput(supporting_id, "SUPPORTING"))
    return WorkAssetInput(
        tenant_id=tenant_id,
        asset_type="AGENT_EXECUTION_RESULT",
        agent_execution_id="execution-500",
        actor_type="AGENT",
        actor_ref="agent-500",
        agent_type_snapshot="IA",
        project_ref=PROJECT_REF,
        occurred_at=NOW,
        classification="CONFIDENTIAL",
        bindings=tuple(bindings),
    )


@pytest.fixture
def local_runtime():
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
                    source_owner TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_revision_ref TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    agent_type_snapshot TEXT,
                    project_ref TEXT,
                    occurred_at TIMESTAMP NOT NULL,
                    observed_at TIMESTAMP NOT NULL,
                    classification TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    supersedes_evidence_id TEXT,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (tenant_id, work_evidence_id),
                    UNIQUE (tenant_id, source_type, source_ref, source_revision_ref),
                    FOREIGN KEY (tenant_id, supersedes_evidence_id)
                        REFERENCES wa_work_evidence (tenant_id, work_evidence_id)
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
                "CREATE UNIQUE INDEX ux_wa_asset_evidence_one_primary "
                "ON wa_work_asset_evidence (tenant_id, work_asset_id) "
                "WHERE binding_role='PRIMARY'"
            )
        )
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return (
        WaEvidenceAdmissionService(sessions, clock=lambda: NOW + timedelta(seconds=2)),
        sessions,
    )


def test_admission_is_atomic_and_exact_replay_is_stable(local_runtime) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))

    first = service.admit_normalized_evidence(evidence, asset)
    replay = service.admit_normalized_evidence(
        _evidence(observed_at=NOW + timedelta(days=1)),
        asset,
    )

    assert replay == first
    assert first.asset.version == 1
    with sessions() as session:
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_evidence")).scalar_one()
            == 1
        )
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_asset")).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM wa_work_asset_evidence")
            ).scalar_one()
            == 1
        )


def test_evidence_set_admission_is_atomic_and_does_not_double_count(local_runtime) -> None:
    service, sessions = local_runtime
    primary = _evidence()
    supporting = _evidence(
        source_owner="nex-wc",
        source_type="WC_WORK_RESULT",
        source_ref="wc-result-500",
        source_revision_ref="1",
        source_hash="sha256:" + "6" * 64,
        evidence_kind="WORK_COORDINATION_RESULT",
    )
    asset = _asset(_evidence_id(primary), supporting_id=_evidence_id(supporting))

    first = service.admit_normalized_evidence_set((primary, supporting), asset)
    replay = service.admit_normalized_evidence_set((primary, supporting), asset)
    assert first == replay
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM wa_work_asset")).scalar_one() == 1
        assert session.execute(text("SELECT count(*) FROM wa_work_evidence")).scalar_one() == 2
        roles = session.execute(
            text("SELECT binding_role FROM wa_work_asset_evidence ORDER BY binding_role")
        ).scalars().all()
    assert roles == ["PRIMARY", "SUPPORTING"]


def test_evidence_set_requires_items_and_same_asset_lineage(local_runtime) -> None:
    service, _sessions = local_runtime
    primary = _evidence()
    asset = _asset(_evidence_id(primary))
    with pytest.raises(WorkAdmissionError, match="must not be empty"):
        service.admit_normalized_evidence_set((), asset)
    unbound = _evidence(source_ref="other-execution")
    with pytest.raises(WorkAdmissionError, match="must be bound"):
        service.admit_normalized_evidence_set((primary, unbound), asset)


def test_failure_after_commit_replay_does_not_duplicate(local_runtime) -> None:
    service, _sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))

    committed = service.admit_normalized_evidence(evidence, asset)
    with pytest.raises(RuntimeError, match="simulated crash"):
        raise RuntimeError("simulated crash after local commit")
    recovered = service.admit_normalized_evidence(evidence, asset)

    assert recovered == committed


def test_asset_failure_rolls_back_new_evidence(local_runtime) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    missing = "70a75434-52a1-4fe2-b81c-11e42d69721c"
    asset = _asset(_evidence_id(evidence), supporting_id=missing)

    with pytest.raises(WorkAssetError) as error:
        service.admit_normalized_evidence(evidence, asset)
    assert error.value.error_code == "WA_ASSET_EVIDENCE_INVALID"
    with sessions() as session:
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_evidence")).scalar_one()
            == 0
        )
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_asset")).scalar_one()
            == 0
        )


def test_multiple_primary_bindings_roll_back_new_evidence(local_runtime) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    evidence_id = _evidence_id(evidence)
    invalid_asset = WorkAssetInput(
        tenant_id="VO00",
        asset_type="AGENT_EXECUTION_RESULT",
        agent_execution_id="execution-500",
        actor_type="AGENT",
        actor_ref="agent-500",
        agent_type_snapshot="IA",
        project_ref=PROJECT_REF,
        occurred_at=NOW,
        classification="CONFIDENTIAL",
        bindings=(
            WorkAssetBindingInput(evidence_id, "PRIMARY"),
            WorkAssetBindingInput(
                "70a75434-52a1-4fe2-b81c-11e42d69721c",
                "PRIMARY",
            ),
        ),
    )

    with pytest.raises(WorkAssetError) as error:
        service.admit_normalized_evidence(evidence, invalid_asset)

    assert error.value.error_code == "WA_ASSET_PRIMARY_INVALID"
    with sessions() as session:
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_evidence")).scalar_one()
            == 0
        )
        assert (
            session.execute(text("SELECT count(*) FROM wa_work_asset")).scalar_one()
            == 0
        )


def test_source_conflict_is_typed_and_does_not_change_asset(local_runtime) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))
    service.admit_normalized_evidence(evidence, asset)

    with pytest.raises(WorkEvidenceError) as conflict:
        service.admit_normalized_evidence(
            _evidence(source_hash="sha256:" + "6" * 64),
            asset,
        )
    assert conflict.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    with sessions() as session:
        assert (
            session.execute(text("SELECT version FROM wa_work_asset")).scalar_one() == 1
        )


def test_admission_lineage_and_retry_configuration_fail_closed(local_runtime) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    with pytest.raises(WorkAdmissionError) as tenant:
        service.admit_normalized_evidence(
            evidence,
            _asset(_evidence_id(evidence), tenant_id="OTHER"),
        )
    assert tenant.value.error_code == "WA_ADMISSION_LINEAGE_INVALID"

    with pytest.raises(WorkAdmissionError) as binding:
        service.admit_normalized_evidence(
            evidence,
            _asset("60e0e936-85e9-41cb-a9ba-49e64a39e2eb"),
        )
    assert binding.value.error_code == "WA_ADMISSION_LINEAGE_INVALID"

    with pytest.raises(ValueError, match="concurrency_retries"):
        WaEvidenceAdmissionService(sessions, concurrency_retries=0)


def test_concurrency_retry_paths_are_bounded(
    local_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))
    expected = service.admit_normalized_evidence(evidence, asset)

    calls = iter(
        (
            IntegrityError("insert", {}, Exception("race")),
            expected,
        )
    )

    def integrity_then_success(*_args):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(service, "_admit_once", integrity_then_success)
    assert service.admit_normalized_evidence(evidence, asset) == expected

    update_calls = iter(
        (
            WorkAssetError("WA_ASSET_CONCURRENT_UPDATE", "race", 409),
            expected,
        )
    )

    def update_then_success(*_args):
        result = next(update_calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(service, "_admit_once", update_then_success)
    assert service.admit_normalized_evidence(evidence, asset) == expected

    exhausted = WaEvidenceAdmissionService(sessions, concurrency_retries=1)
    monkeypatch.setattr(
        exhausted,
        "_admit_once",
        lambda *_args: (_ for _ in ()).throw(
            IntegrityError("insert", {}, Exception("race"))
        ),
    )
    with pytest.raises(WorkAdmissionError) as conflict:
        exhausted.admit_normalized_evidence(evidence, asset)
    assert conflict.value.error_code == "WA_ADMISSION_INTEGRITY_CONFLICT"

    exhausted_update = WaEvidenceAdmissionService(sessions, concurrency_retries=1)
    monkeypatch.setattr(
        exhausted_update,
        "_admit_once",
        lambda *_args: (_ for _ in ()).throw(
            WorkAssetError("WA_ASSET_CONCURRENT_UPDATE", "race", 409)
        ),
    )
    with pytest.raises(WorkAssetError) as update_conflict:
        exhausted_update.admit_normalized_evidence(evidence, asset)
    assert update_conflict.value.error_code == "WA_ASSET_CONCURRENT_UPDATE"


def test_repository_integrity_failure_is_retried_and_typed(
    local_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))
    monkeypatch.setattr(
        service._evidence_repository,
        "create_or_get_in_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            IntegrityError("insert", {}, Exception("race"))
        ),
    )

    with pytest.raises(WorkAdmissionError) as conflict:
        service.admit_normalized_evidence(evidence, asset)

    assert conflict.value.error_code == "WA_ADMISSION_INTEGRITY_CONFLICT"


def test_database_failure_is_redacted_and_typed(
    local_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _sessions = local_runtime
    evidence = _evidence()
    asset = _asset(_evidence_id(evidence))
    monkeypatch.setattr(
        service._evidence_repository,
        "create_or_get_in_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SQLAlchemyError("private database detail")
        ),
    )

    with pytest.raises(WorkAdmissionError) as unavailable:
        service.admit_normalized_evidence(evidence, asset)
    assert unavailable.value.error_code == "WA_ADMISSION_STORE_UNAVAILABLE"
    assert "private" not in str(unavailable.value)
