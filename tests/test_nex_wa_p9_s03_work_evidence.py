from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import nex_wa.work_evidence as evidence_module
import pytest
from nex_wa import (
    SqlAlchemyWorkEvidenceRepository,
    WorkEvidenceError,
    WorkEvidenceInput,
    build_work_evidence,
    deterministic_work_evidence_id,
)
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
SOURCE_HASH = "sha256:" + "a" * 64
PROJECT_REF = "6ef92c72-bca8-48cc-bddd-220db25d9ce7"


def _candidate(**overrides: object) -> WorkEvidenceInput:
    values: dict[str, object] = {
        "tenant_id": "VO00",
        "source_owner": "nex-ae-api",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "execution-100",
        "source_revision_ref": "result-1",
        "source_hash": SOURCE_HASH,
        "evidence_kind": "AGENT_EXECUTION_RESULT",
        "actor_type": "AGENT",
        "actor_ref": "agent-100",
        "agent_type_snapshot": "IA",
        "project_ref": PROJECT_REF,
        "occurred_at": NOW,
        "observed_at": NOW + timedelta(seconds=2),
        "classification": "CONFIDENTIAL",
    }
    values.update(overrides)
    return WorkEvidenceInput(**values)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SqlAlchemyWorkEvidenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record) -> None:
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
                )
                """
            )
        )
    return SqlAlchemyWorkEvidenceRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
        clock=lambda: NOW + timedelta(seconds=3),
    )


def test_deterministic_identity_and_semantic_hash_exclude_observation_metadata() -> None:
    first = build_work_evidence(_candidate(), created_at=NOW + timedelta(seconds=3))
    replay = build_work_evidence(
        _candidate(observed_at=NOW + timedelta(days=1)),
        created_at=NOW + timedelta(days=2),
    )

    assert first.work_evidence_id == deterministic_work_evidence_id(
        tenant_id="VO00",
        source_type="AE_AGENT_RESULT",
        source_ref="execution-100",
        source_revision_ref="result-1",
    )
    assert first.work_evidence_id == replay.work_evidence_id
    assert first.evidence_hash == replay.evidence_hash
    assert first.created_at != replay.created_at
    assert first.observed_at != replay.observed_at
    assert first.evidence_hash.startswith("sha256:")
    assert len(first.evidence_hash) == 71


def test_hash_binds_semantic_fields_but_identity_only_binds_source_identity() -> None:
    baseline = build_work_evidence(_candidate(), created_at=NOW)
    changed = build_work_evidence(
        _candidate(
            source_owner="nex-wc",
            evidence_kind="DELIVERY_EVIDENCE",
            actor_ref="agent-200",
            classification="RESTRICTED",
            occurred_at=NOW + timedelta(minutes=1),
        ),
        created_at=NOW,
    )

    assert changed.work_evidence_id == baseline.work_evidence_id
    assert changed.evidence_hash != baseline.evidence_hash


@pytest.mark.parametrize(
    ("overrides", "detail"),
    (
        ({"tenant_id": ""}, "tenant_id"),
        ({"tenant_id": 3}, "tenant_id"),
        ({"source_owner": " nex-ae-api"}, "source_owner"),
        ({"source_type": "UNKNOWN"}, "source_type"),
        ({"source_hash": "bad"}, "source_hash"),
        ({"actor_type": "SERVICE"}, "actor_type"),
        ({"agent_type_snapshot": "WA"}, "agent_type_snapshot"),
        ({"project_ref": "not-a-uuid"}, "project_ref"),
        ({"occurred_at": NOW.replace(tzinfo=None)}, "occurred_at"),
        ({"classification": "PUBLIC"}, "classification"),
        ({"evidence_status": "DELETED"}, "evidence_status"),
        ({"supersedes_evidence_id": "not-a-uuid"}, "supersedes_evidence_id"),
    ),
)
def test_candidate_validation_fails_closed(
    overrides: dict[str, object],
    detail: str,
) -> None:
    with pytest.raises(WorkEvidenceError, match=detail) as error:
        build_work_evidence(_candidate(**overrides))
    assert error.value.error_code == "WA_EVIDENCE_INVALID"


def test_repository_reuses_exact_source_hash_and_rejects_conflict(
    repository: SqlAlchemyWorkEvidenceRepository,
) -> None:
    stored = repository.create_or_get(_candidate())
    replay = repository.create_or_get(
        _candidate(observed_at=NOW + timedelta(hours=1))
    )

    assert replay == stored
    assert repository.get("VO00", stored.work_evidence_id) == stored
    with pytest.raises(WorkEvidenceError) as error:
        repository.create_or_get(_candidate(source_hash="sha256:" + "b" * 64))
    assert error.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    assert error.value.status_code == 409


def test_source_revision_and_same_tenant_supersession_create_new_evidence(
    repository: SqlAlchemyWorkEvidenceRepository,
) -> None:
    first = repository.create_or_get(_candidate())
    correction = repository.create_or_get(
        _candidate(
            source_revision_ref="result-2",
            source_hash="sha256:" + "c" * 64,
            supersedes_evidence_id=first.work_evidence_id,
        )
    )

    assert correction.work_evidence_id != first.work_evidence_id
    assert correction.supersedes_evidence_id == first.work_evidence_id
    assert repository.get("VO00", first.work_evidence_id).evidence_status == "SUPERSEDED"
    assert [item.work_evidence_id for item in repository.list_source_lineage(
        "VO00", correction.work_evidence_id
    )] == [first.work_evidence_id, correction.work_evidence_id]


def test_cross_tenant_and_self_supersession_fail_closed(
    repository: SqlAlchemyWorkEvidenceRepository,
) -> None:
    first = repository.create_or_get(_candidate())
    with pytest.raises(WorkEvidenceError) as cross_tenant:
        repository.create_or_get(
            _candidate(
                tenant_id="OTHER",
                source_revision_ref="result-2",
                supersedes_evidence_id=first.work_evidence_id,
            )
        )
    assert cross_tenant.value.error_code == "WA_SUPERSESSION_INVALID"

    own_id = deterministic_work_evidence_id(
        tenant_id="VO00",
        source_type="AE_AGENT_RESULT",
        source_ref="execution-100",
        source_revision_ref="result-self",
    )
    with pytest.raises(WorkEvidenceError) as self_reference:
        build_work_evidence(
            _candidate(
                source_revision_ref="result-self",
                supersedes_evidence_id=own_id,
            )
        )
    assert self_reference.value.error_code == "WA_SUPERSESSION_INVALID"


def test_get_validates_identity_and_store_failures_are_redacted() -> None:
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("private database detail")

        def get_bind(self):
            return None

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    repository = SqlAlchemyWorkEvidenceRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(WorkEvidenceError, match="must be a UUID"):
        repository.get("VO00", "bad-id")
    with pytest.raises(WorkEvidenceError) as get_error:
        repository.get("VO00", str(uuid4()))
    assert get_error.value.error_code == "WA_EVIDENCE_STORE_UNAVAILABLE"
    assert "private" not in str(get_error.value)
    with pytest.raises(WorkEvidenceError) as create_error:
        repository.create_or_get(_candidate())
    assert create_error.value.error_code == "WA_EVIDENCE_STORE_UNAVAILABLE"
    assert "private" not in str(create_error.value)


def test_stored_timestamp_corruption_fails_closed(
    repository: SqlAlchemyWorkEvidenceRepository,
) -> None:
    stored = repository.create_or_get(_candidate())
    session_factory = repository._session_factory
    with session_factory.begin() as session:
        session.execute(
            text(
                "UPDATE wa_work_evidence SET occurred_at = 'invalid' "
                "WHERE work_evidence_id = :work_evidence_id"
            ),
            {"work_evidence_id": stored.work_evidence_id},
        )
    with pytest.raises(WorkEvidenceError) as error:
        repository.get("VO00", stored.work_evidence_id)
    assert error.value.error_code == "WA_EVIDENCE_STORE_UNAVAILABLE"


def test_nullable_agent_snapshot_and_stored_timestamp_type_branches() -> None:
    human = build_work_evidence(
        _candidate(
            source_type="AE_ARTIFACT",
            actor_type="HUMAN",
            agent_type_snapshot=None,
        ),
        created_at=NOW,
    )
    assert human.agent_type_snapshot is None
    assert evidence_module._row_timestamp(NOW) == "2026-10-27T03:00:00.000000Z"
    with pytest.raises(WorkEvidenceError) as invalid:
        evidence_module._row_timestamp(7)
    assert invalid.value.error_code == "WA_EVIDENCE_STORE_UNAVAILABLE"


def test_concurrent_insert_winner_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _candidate()
    winner = build_work_evidence(candidate, created_at=NOW)

    class RacingSession:
        def execute(self, *_args, **_kwargs):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        def get_bind(self):
            return None

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    repository = SqlAlchemyWorkEvidenceRepository(
        lambda: RacingSession(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    existing = iter((None, winner))
    monkeypatch.setattr(
        repository,
        "_select_by_source",
        lambda *_args: next(existing),
    )
    monkeypatch.setattr(repository, "_apply_supersession", lambda *_args: None)

    assert repository.create_or_get(candidate) == winner


def test_unresolved_integrity_and_missing_readback_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self, *, integrity_failure: bool) -> None:
            self.integrity_failure = integrity_failure

        def execute(self, *_args, **_kwargs):
            if self.integrity_failure:
                raise IntegrityError("insert", {}, Exception("constraint"))

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

        def get_bind(self):
            return None

    for integrity_failure, expected_code in (
        (True, "WA_SUPERSESSION_INVALID"),
        (False, "WA_EVIDENCE_STORE_UNAVAILABLE"),
    ):
        repository = SqlAlchemyWorkEvidenceRepository(
            lambda value=integrity_failure: Session(integrity_failure=value),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        monkeypatch.setattr(repository, "_select_by_source", lambda *_args: None)
        monkeypatch.setattr(
            repository,
            "_apply_supersession",
            lambda *_args: None,
        )
        monkeypatch.setattr(repository, "_select_by_id", lambda *_args: None)

        with pytest.raises(WorkEvidenceError) as error:
            repository.create_or_get(_candidate())
        assert error.value.error_code == expected_code
