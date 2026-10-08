from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_mo.main import MODEL_ROLLOUTS
from nex_mo.main import app as main_app
from nex_mo.model_rollout import ModelRolloutError
from nex_mo.model_rollout_api import register_model_rollout_routes
from nex_mo.model_rollout_persistence import ModelRolloutEvent
from nex_mo.model_rollout_repository import (
    InMemoryModelRolloutRepository,
    ModelRolloutRepositoryError,
    SqlAlchemyModelRolloutRepository,
    _timestamp_text,
)
from nex_mo.model_rollout_runtime import (
    ModelRolloutRuntimeError,
    build_model_rollout_service,
)
from nex_mo.model_rollout_service import (
    ModelRolloutService,
    ModelRolloutServiceError,
    _map_repository_error,
)
from nex_mo.model_rollout_state import begin_validation
from nex_mo.provider_auth import MO_OPERATIONS_READ_SCOPE
from nex_runtime import issue_mock_service_token
from run_s147_rollout_persistence_restart import SQLITE_SCHEMA, _record
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DIGEST = "sha256:" + "f" * 64


def event(
    record, event_id="event:one", event_type="rollout.registered", from_state=None
):
    return ModelRolloutEvent(
        event_id=event_id,
        rollout_id=record.rollout_id,
        event_type=event_type,
        from_state=from_state,
        to_state=record.state,
        state_revision=record.state_revision,
        evidence_digest=None,
        failure_code=record.failure_code,
        occurred_at=record.updated_at,
    )


def service(repository=None):
    identifiers = iter(("one", "two", "three"))
    return ModelRolloutService(
        repository or InMemoryModelRolloutRepository(),
        id_factory=lambda: next(identifiers),
    )


def sql_repository(path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, SqlAlchemyModelRolloutRepository(factory)


def headers(service_id="nex-ag", audience="nex-mo"):
    token = issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=("service:call", MO_OPERATIONS_READ_SCOPE),
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_memory_service_persists_revisioned_event_history() -> None:
    store = InMemoryModelRolloutRepository()
    rollout_service = service(store)
    registered = _record()
    assert rollout_service.register(registered) == registered
    validating = begin_validation(registered, changed_at="2026-10-08T00:01:00Z")
    assert (
        rollout_service.persist_transition(
            validating,
            expected_state_revision=1,
            event_type="rollout.validation_started",
            evidence_digest=DIGEST,
        )
        == validating
    )

    assert rollout_service.get(registered.rollout_id) == validating
    assert rollout_service.list(capability="generation", state="VALIDATING") == [
        validating
    ]
    assert [
        item.event_type for item in rollout_service.list_events(registered.rollout_id)
    ] == [
        "rollout.registered",
        "rollout.validation_started",
    ]


def test_memory_repository_rejects_conflicts_drift_and_invalid_filters() -> None:
    repository = InMemoryModelRolloutRepository()
    record = _record()
    repository.insert(record, event(record))
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.insert(record, event(record, "event:duplicate"))
    assert exc.value.error_code == "mo.rollout_conflict"

    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    next_event = event(
        validating,
        "event:two",
        "rollout.validation_started",
        "REGISTERED",
    )
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(validating, next_event, expected_state_revision=0)
    assert exc.value.error_code == "mo.rollout_revision_conflict"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            replace(validating, last_known_good_binding_id="binding:other"),
            next_event,
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_immutable_drift"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            validating,
            replace(next_event, from_state="READY"),
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_event_mismatch"

    for kwargs in (
        {"capability": "other"},
        {"state": "OTHER"},
        {"limit": 0},
        {"limit": True},
    ):
        with pytest.raises(ModelRolloutRepositoryError) as exc:
            repository.list(**kwargs)
        assert exc.value.error_code == "mo.rollout_filter_invalid"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.list_events("rollout:missing")
    assert exc.value.error_code == "mo.rollout_not_found"


def test_repository_event_mismatch_and_missing_update() -> None:
    repository = InMemoryModelRolloutRepository()
    record = _record()
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.insert(record, replace(event(record), to_state="READY"))
    assert exc.value.error_code == "mo.rollout_event_mismatch"
    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            validating,
            event(validating, "event:two", "rollout.validation_started", "REGISTERED"),
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_not_found"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"event_id": "bad value"}, "mo.event_id_invalid"),
        ({"from_state": "bad value"}, "mo.from_state_invalid"),
        ({"event_type": "unknown"}, "mo.rollout_event_type_invalid"),
        ({"state_revision": 0}, "mo.rollout_event_revision_invalid"),
        ({"evidence_digest": "bad"}, "mo.evidence_digest_invalid"),
        ({"failure_code": "bad value"}, "mo.failure_code_invalid"),
        ({"occurred_at": "bad"}, "mo.occurred_at_invalid"),
        ({"occurred_at": "2026-10-08T00:00:00"}, "mo.occurred_at_invalid"),
    ],
)
def test_event_validation(changes, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        replace(event(_record()), **changes)
    assert exc.value.error_code == code


def test_service_maps_repository_errors_and_registration_guard() -> None:
    rollout_service = service()
    registered = _record()
    with pytest.raises(ModelRolloutServiceError) as exc:
        rollout_service.register(
            begin_validation(registered, changed_at="2026-10-08T00:01:00Z")
        )
    assert exc.value.error_code == "MO_ROLLOUT_REGISTRATION_INVALID"
    with pytest.raises(ModelRolloutServiceError) as exc:
        rollout_service.get("rollout:missing")
    assert exc.value.error_code == "MO_ROLLOUT_NOT_FOUND"
    with pytest.raises(ModelRolloutServiceError) as exc:
        rollout_service.list(capability="other")
    assert exc.value.error_code == "MO_ROLLOUT_FILTER_INVALID"


@pytest.mark.parametrize(
    ("repository_code", "status_code", "service_code"),
    [
        ("mo.rollout_not_found", 404, "MO_ROLLOUT_NOT_FOUND"),
        ("mo.rollout_conflict", 409, "MO_ROLLOUT_CONFLICT"),
        ("mo.rollout_revision_conflict", 409, "MO_ROLLOUT_REVISION_CONFLICT"),
        ("mo.rollout_immutable_drift", 409, "MO_ROLLOUT_IMMUTABLE_DRIFT"),
        ("mo.rollout_event_mismatch", 409, "MO_ROLLOUT_EVENT_MISMATCH"),
        ("mo.rollout_filter_invalid", 422, "MO_ROLLOUT_FILTER_INVALID"),
        (
            "mo.rollout_persistence_unavailable",
            503,
            "MO_ROLLOUT_PERSISTENCE_UNAVAILABLE",
        ),
    ],
)
def test_repository_errors_map_to_safe_service_errors(
    repository_code: str,
    status_code: int,
    service_code: str,
) -> None:
    mapped = _map_repository_error(
        ModelRolloutRepositoryError(repository_code, "private persistence detail")
    )
    assert mapped.status_code == status_code
    assert mapped.error_code == service_code
    if status_code == 503:
        assert "private persistence detail" not in mapped.detail


def test_service_maps_repository_failures_for_every_operation() -> None:
    record = _record()
    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    repository = Mock()
    rollout_service = service(repository)
    failure = ModelRolloutRepositoryError("mo.rollout_conflict", "conflict")

    repository.insert.side_effect = failure
    with pytest.raises(ModelRolloutServiceError):
        rollout_service.register(record)
    repository.get.side_effect = failure
    with pytest.raises(ModelRolloutServiceError):
        rollout_service.get(record.rollout_id)
    repository.get.side_effect = None
    repository.get.return_value = record
    repository.update.side_effect = failure
    with pytest.raises(ModelRolloutServiceError):
        rollout_service.persist_transition(
            validating,
            expected_state_revision=1,
            event_type="rollout.validation_started",
        )
    repository.list.side_effect = failure
    with pytest.raises(ModelRolloutServiceError):
        rollout_service.list()
    repository.list_events.side_effect = failure
    with pytest.raises(ModelRolloutServiceError):
        rollout_service.list_events(record.rollout_id)


def test_sql_repository_transaction_conflict_filters_and_restart(
    tmp_path: Path,
) -> None:
    engine, repository = sql_repository(tmp_path / "rollout.db")
    record = _record()
    first_event = event(record)
    repository.insert(record, first_event)

    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.insert(record, replace(first_event, event_id="event:duplicate"))
    assert exc.value.error_code == "mo.rollout_conflict"
    assert repository.list(capability="generation") == [record]
    assert repository.list(state="REGISTERED") == [record]

    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    duplicate_event = event(
        validating,
        "event:one",
        "rollout.validation_started",
        "REGISTERED",
    )
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(validating, duplicate_event, expected_state_revision=1)
    assert exc.value.error_code == "mo.rollout_revision_conflict"
    assert repository.get(record.rollout_id).state_revision == 1

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER ignore_rollout_update BEFORE UPDATE "
                "ON mo_model_rollouts BEGIN SELECT RAISE(IGNORE); END"
            )
        )
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            validating,
            replace(duplicate_event, event_id="event:rowcount"),
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_revision_conflict"
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER ignore_rollout_update"))

    missing = replace(record, rollout_id="rollout:generation:missing")
    missing_next = begin_validation(missing, changed_at="2026-10-08T00:01:00Z")
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            missing_next,
            event(
                missing_next,
                "event:missing",
                "rollout.validation_started",
                "REGISTERED",
            ),
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_not_found"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.list_events(missing.rollout_id)
    assert exc.value.error_code == "mo.rollout_not_found"
    engine.dispose()


def test_sql_repository_fails_closed_on_corrupt_or_unavailable_storage(
    tmp_path: Path,
) -> None:
    engine, repository = sql_repository(tmp_path / "corrupt.db")
    record = _record()
    repository.insert(record, event(record))
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE mo_model_rollouts SET identity_fingerprint = :fingerprint "
                "WHERE rollout_id = :rollout_id"
            ),
            {"fingerprint": DIGEST, "rollout_id": record.rollout_id},
        )
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.get(record.rollout_id)
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE mo_model_rollouts SET identity_fingerprint = :fingerprint "
                "WHERE rollout_id = :rollout_id"
            ),
            {
                "fingerprint": record.identity.fingerprint,
                "rollout_id": record.rollout_id,
            },
        )
        connection.execute(text("DROP TABLE mo_rollout_events"))
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.list_events(record.rollout_id)
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE mo_model_rollouts"))
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.get(record.rollout_id)
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.list()
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"
    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.update(
            validating,
            event(
                validating,
                "event:after-drop-update",
                "rollout.validation_started",
                "REGISTERED",
            ),
            expected_state_revision=1,
        )
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"
    with pytest.raises(ModelRolloutRepositoryError) as exc:
        repository.insert(record, event(record, "event:after-drop"))
    assert exc.value.error_code == "mo.rollout_persistence_unavailable"
    engine.dispose()


def test_timestamp_projection_normalizes_datetime() -> None:
    assert _timestamp_text(datetime(2026, 10, 8, tzinfo=UTC)) == "2026-10-08T00:00:00Z"


def test_runtime_selects_memory_and_postgres(monkeypatch) -> None:
    assert build_model_rollout_service(SimpleNamespace(mode="memory")).list() == []
    with pytest.raises(ModelRolloutRuntimeError, match="session factory"):
        build_model_rollout_service(
            SimpleNamespace(mode="postgres", api_session_factory=None)
        )
    repository = InMemoryModelRolloutRepository()
    monkeypatch.setattr(
        "nex_mo.model_rollout_runtime.SqlAlchemyModelRolloutRepository",
        lambda _factory: repository,
    )
    assert (
        build_model_rollout_service(
            SimpleNamespace(mode="postgres", api_session_factory=object())
        ).list()
        == []
    )
    with pytest.raises(ModelRolloutRuntimeError, match="memory or postgres"):
        build_model_rollout_service(SimpleNamespace(mode="other"))


def test_operations_api_is_ag_only_and_returns_safe_projection() -> None:
    rollout_service = service()
    rollout_service.register(_record())
    app = FastAPI()
    register_model_rollout_routes(app, service=rollout_service)
    client = TestClient(app)

    assert client.get("/api/v1/model-rollouts").status_code == 401
    assert (
        client.get("/api/v1/model-rollouts", headers=headers("nex-cx")).status_code
        == 403
    )
    collection = client.get("/api/v1/model-rollouts", headers=headers())
    detail = client.get(
        "/api/v1/model-rollouts/rollout:generation:2", headers=headers()
    )
    history = client.get(
        "/api/v1/model-rollouts/rollout:generation:2/events", headers=headers()
    )
    missing = client.get("/api/v1/model-rollouts/rollout:missing", headers=headers())
    invalid = client.get("/api/v1/model-rollouts?limit=0", headers=headers())

    assert collection.status_code == detail.status_code == history.status_code == 200
    assert len(collection.json()["data"]) == 1
    assert len(history.json()["data"]) == 1
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert "model_name" not in collection.text and "endpoint" not in collection.text


def test_operations_api_maps_unexpected_projection_error(monkeypatch) -> None:
    rollout_service = service()
    app = FastAPI()
    register_model_rollout_routes(app, service=rollout_service)
    monkeypatch.setattr(
        rollout_service, "list", Mock(side_effect=ValueError("private"))
    )
    response = TestClient(app).get("/api/v1/model-rollouts", headers=headers())
    assert response.status_code == 422
    assert response.json()["error_code"] == "MO_ROLLOUT_REQUEST_INVALID"
    assert "private" not in response.text


def test_main_app_registers_model_rollout_runtime_and_routes() -> None:
    response = TestClient(main_app).get("/api/v1/model-rollouts", headers=headers())
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert main_app.state.model_rollout_service is MODEL_ROLLOUTS
