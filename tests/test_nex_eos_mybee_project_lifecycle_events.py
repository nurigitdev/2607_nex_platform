from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_eos import (
    EOS_METADATA,
    EosProjectLifecycleEventError,
    append_project_lifecycle_event,
    project_lifecycle_event_payload,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
TENANT = "VO00"
PROJECT_ID = "c5000000-0000-4000-8000-000000000002"


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _arguments(**overrides):
    values = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": "VO00D260001",
        "previous_state": "ACTIVE",
        "current_state": "INACTIVE",
        "project_version": 2,
        "profile_policy_ref": "policy://nex-platform/project-agent-lifecycle/v1",
        "correlation_id": "w30-s00d-correlation",
        "causation_id": "w30-s00d-causation",
        "occurred_at": NOW,
    }
    values.update(overrides)
    return values


def test_lifecycle_event_replay_is_stable_and_semantic_drift_fails_closed(
    sessions,
) -> None:
    with sessions.begin() as session:
        created = append_project_lifecycle_event(session, **_arguments())
    with sessions.begin() as session:
        replay = append_project_lifecycle_event(session, **_arguments())

    assert replay["event_id"] == created["event_id"]
    assert replay["event_payload_hash"] == created["event_payload_hash"]
    assert project_lifecycle_event_payload(replay)["current_state"] == "INACTIVE"

    with (
        sessions.begin() as session,
        pytest.raises(EosProjectLifecycleEventError, match="different semantics"),
    ):
        append_project_lifecycle_event(
            session,
            **_arguments(project_code="VO00D260999"),
        )


@pytest.mark.parametrize("payload", (None, [], "not-an-object"))
def test_lifecycle_event_payload_requires_an_object(payload) -> None:
    with pytest.raises(EosProjectLifecycleEventError, match="payload is absent"):
        project_lifecycle_event_payload({"event_payload": payload})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("tenant_id", None, "tenant_id is invalid"),
        ("tenant_id", "", "tenant_id is invalid"),
        ("tenant_id", " VO00", "tenant_id is invalid"),
        ("tenant_id", "A" * 129, "tenant_id is invalid"),
        ("tenant_id", "VO00!", "tenant_id is invalid"),
        ("project_id", "not-a-uuid", "project_id must be a UUID"),
        ("current_state", None, "current_state is invalid"),
        ("current_state", "DRAFT", "current_state is invalid"),
        ("project_version", True, "project_version must be a positive integer"),
        ("project_version", "2", "project_version must be a positive integer"),
        ("project_version", 0, "project_version must be a positive integer"),
        ("occurred_at", "not-a-datetime", "occurred_at must be a datetime"),
        ("occurred_at", NOW.replace(tzinfo=None), "timezone-aware"),
    ),
)
def test_lifecycle_event_input_contract_rejects_malformed_values(
    sessions, field, value, message
) -> None:
    with (
        sessions.begin() as session,
        pytest.raises(EosProjectLifecycleEventError, match=message),
    ):
        append_project_lifecycle_event(session, **_arguments(**{field: value}))
