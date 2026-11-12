from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.project_agent_lifecycle import (
    AE_PROJECT_AGENT_METADATA,
    AE_PROJECT_AGENT_SYNC_TABLE,
    AE_PROJECT_LIFECYCLE_INBOX_TABLE,
    AdmittedProjectAgentProfilePolicy,
    ProjectAgentLifecycleError,
    SqlAlchemyProjectAgentLifecycleService,
)
from nex_ae_api.project_agent_lifecycle_api import (
    register_project_agent_lifecycle_routes,
)
from nex_eos import (
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    EosOutboxPublishReceipt,
    EosProjectLifecycleEventError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosOutboxPublisher,
    SqlAlchemyEosProjectRepository,
    append_project_lifecycle_event,
    project_lifecycle_event_payload,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "deployment/product/config/project-agent-profile-policy.v1.json"
POLICY_REF = "policy://nex-platform/project-agent-lifecycle/v1"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
TENANT = "VO00"
NVT_ID = "c5000000-0000-4000-8000-000000000001"
PROJECT_ID = "c5000000-0000-4000-8000-000000000002"
PROJECT_CODE = "VO00D260001"


def _engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_agent_identity_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_agent_identity (
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    project_id TEXT NULL,
                    created_at TIMESTAMP NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, agent_id)
                )
                """
            )
        )


@pytest.fixture
def lifecycle_runtime():
    eos_engine = _engine()
    ae_engine = _engine()
    EOS_METADATA.create_all(eos_engine)
    _create_agent_identity_table(ae_engine)
    AE_PROJECT_AGENT_METADATA.create_all(ae_engine)
    eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
    ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
    policy = AdmittedProjectAgentProfilePolicy.from_path(POLICY_PATH)
    ae_service = SqlAlchemyProjectAgentLifecycleService(
        ae_sessions,
        profile_policy=policy,
        clock=lambda: NOW,
    )
    projects = SqlAlchemyEosProjectRepository(eos_sessions)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "NVT-W30-C", "W30 PA Lifecycle")
    )
    projects.create_project(
        ProjectInput(
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code=PROJECT_CODE,
            name="Project Agent Lifecycle",
            nvt_project_id=NVT_ID,
            status="ACTIVE",
            project_request_code="VO00R260001",
            purpose_type="D",
            origin="APPROVED_APPLICATION",
            approval_evidence_ref="eos.project-application-approval:VO00R260001",
            approval_evidence_hash="sha256:" + "a" * 64,
            agent_sync_state="PENDING",
        )
    )
    correlation_id = str(uuid4())
    with eos_sessions.begin() as session:
        append_project_lifecycle_event(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code=PROJECT_CODE,
            previous_state="SUBMITTED",
            current_state="ACTIVE",
            project_version=1,
            profile_policy_ref=POLICY_REF,
            correlation_id=correlation_id,
            causation_id=correlation_id,
            occurred_at=NOW,
        )
    yield eos_sessions, ae_sessions, ae_service, projects
    eos_engine.dispose()
    ae_engine.dispose()


class DirectAeTransport:
    def __init__(self, service: SqlAlchemyProjectAgentLifecycleService) -> None:
        self.service = service
        self.envelopes: list[dict] = []

    def publish(self, event):
        envelope = {
            "event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "business_operation_id": event.business_operation_id,
            "event_type": event.event_type,
            "event_payload_hash": event.event_payload_hash,
            "event_payload": event.event_payload,
        }
        self.envelopes.append(envelope)
        receipt, _ = self.service.ingest(envelope)
        return EosOutboxPublishReceipt(
            event_id=receipt["event_id"],
            event_payload_hash=receipt["event_payload_hash"],
            receipt_ref=receipt["receipt_ref"],
        )


def _initial_envelope(eos_sessions) -> dict:
    with eos_sessions() as session:
        row = session.execute(select(EOS_OUTBOX_TABLE)).mappings().one()
    return {
        "event_id": str(row["event_id"]),
        "tenant_id": row["tenant_id"],
        "business_operation_id": str(row["business_operation_id"]),
        "event_type": row["event_type"],
        "event_payload_hash": row["event_payload_hash"],
        "event_payload": row["event_payload"],
    }


def _rehash(envelope: dict) -> None:
    envelope["event_payload_hash"] = semantic_sha256_hash_ref(envelope["event_payload"])


def test_direct_lifecycle_sync_reuses_one_pa_and_acknowledges_eos(
    lifecycle_runtime,
) -> None:
    eos_sessions, ae_sessions, ae_service, projects = lifecycle_runtime
    publisher = SqlAlchemyEosOutboxPublisher(eos_sessions, clock=lambda: NOW)
    transport = DirectAeTransport(ae_service)

    first = publisher.publish_next(transport, tenant_id=TENANT)
    assert first is not None and first.delivery_state == "PUBLISHED"
    with eos_sessions() as session:
        project = (
            session.execute(
                select(EOS_PROJECT_TABLE).where(
                    EOS_PROJECT_TABLE.c.tenant_id == TENANT,
                    EOS_PROJECT_TABLE.c.project_id == PROJECT_ID,
                )
            )
            .mappings()
            .one()
        )
        assert project["agent_sync_state"] == "IN_SYNC"
    with ae_sessions() as session:
        projection = (
            session.execute(select(AE_PROJECT_AGENT_SYNC_TABLE)).mappings().one()
        )
        original_agent_id = str(projection["agent_id"])
        assert projection["agent_status"] == "ACTIVE"
        assert projection["capability_mode"] == "ORDINARY"

    replay, created = ae_service.ingest(transport.envelopes[0])
    assert created is False
    assert replay["agent_id"] == original_agent_id

    for expected_version, target, agent_status, capability_mode in (
        (1, "INACTIVE", "SUSPENDED", "SUSPENDED"),
        (2, "ACTIVE", "ACTIVE", "ORDINARY"),
        (3, "CLOSING", "ACTIVE", "CLOSURE"),
        (4, "CLOSED", "RETIRED", "RETIRED"),
    ):
        changed = projects.transition_project_status(
            tenant_id=TENANT,
            project_code=PROJECT_CODE,
            target_status=target,
            expected_version=expected_version,
            profile_policy_ref=POLICY_REF,
        )
        assert changed["agent_sync_state"] == "PENDING"
        result = publisher.publish_next(transport, tenant_id=TENANT)
        assert result is not None and result.retry_required is False
        with ae_sessions() as session:
            projection = (
                session.execute(select(AE_PROJECT_AGENT_SYNC_TABLE)).mappings().one()
            )
            assert str(projection["agent_id"]) == original_agent_id
            assert projection["project_state"] == target
            assert projection["agent_status"] == agent_status
            assert projection["capability_mode"] == capability_mode

    with ae_sessions() as session:
        inbox_rows = (
            session.execute(select(AE_PROJECT_LIFECYCLE_INBOX_TABLE)).mappings().all()
        )
        assert len(inbox_rows) == 5
        identities = (
            session.execute(
                text(
                    "SELECT agent_id, status FROM ae_agent_identity "
                    "WHERE tenant_id=:tenant_id AND project_id=:project_id"
                ),
                {"tenant_id": TENANT, "project_id": PROJECT_ID},
            )
            .mappings()
            .all()
        )
        assert identities == [{"agent_id": original_agent_id, "status": "RETIRED"}]
    with eos_sessions() as session:
        assert (
            session.scalar(
                select(EOS_OUTBOX_TABLE.c.outbox_id).where(
                    EOS_OUTBOX_TABLE.c.delivery_state == "PENDING"
                )
            )
            is None
        )


def test_lifecycle_consumer_fails_closed_on_drift_and_noncontiguous_state(
    lifecycle_runtime,
) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    transport = DirectAeTransport(service)
    SqlAlchemyEosOutboxPublisher(eos_sessions, clock=lambda: NOW).publish_next(
        transport, tenant_id=TENANT
    )
    drifted = deepcopy(transport.envelopes[0])
    drifted["event_payload"]["project_code"] = "VO00D269999"
    with pytest.raises(ProjectAgentLifecycleError, match="hash has drifted"):
        service.ingest(drifted)

    skipped = deepcopy(transport.envelopes[0])
    skipped["event_id"] = str(uuid4())
    skipped["event_payload"]["previous_state"] = "ACTIVE"
    skipped["event_payload"]["current_state"] = "CLOSING"
    skipped["event_payload"]["project_version"] = 3
    skipped["event_payload_hash"] = semantic_sha256_hash_ref(skipped["event_payload"])
    with pytest.raises(ProjectAgentLifecycleError, match="not contiguous"):
        service.ingest(skipped)


def test_eos_lifecycle_event_append_is_idempotent_and_semantically_bound(
    lifecycle_runtime,
) -> None:
    eos_sessions, _, _, _ = lifecycle_runtime
    correlation_id = str(uuid4())
    arguments = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "previous_state": "ACTIVE",
        "current_state": "INACTIVE",
        "project_version": 2,
        "profile_policy_ref": POLICY_REF,
        "correlation_id": correlation_id,
        "causation_id": correlation_id,
        "occurred_at": NOW,
    }
    with eos_sessions.begin() as session:
        created = append_project_lifecycle_event(session, **arguments)
    with eos_sessions.begin() as session:
        replay = append_project_lifecycle_event(session, **arguments)
    assert replay["event_id"] == created["event_id"]
    assert project_lifecycle_event_payload(replay)["current_state"] == "INACTIVE"

    with (
        eos_sessions.begin() as session,
        pytest.raises(EosProjectLifecycleEventError, match="different semantics"),
    ):
        append_project_lifecycle_event(
            session,
            **{**arguments, "project_code": "VO00D269999"},
        )
    with pytest.raises(EosProjectLifecycleEventError, match="payload is absent"):
        project_lifecycle_event_payload({"event_payload": None})


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("tenant_id", " bad ", "tenant_id is invalid"),
        ("project_id", "not-a-uuid", "project_id must be a UUID"),
        ("previous_state", "DRAFT", "previous_state is invalid"),
        ("project_version", True, "must be a positive integer"),
        ("occurred_at", "not-a-datetime", "must be a datetime"),
        ("occurred_at", NOW.replace(tzinfo=None), "timezone-aware"),
    ),
)
def test_eos_lifecycle_event_input_validation_fails_closed(
    lifecycle_runtime,
    field: str,
    value: object,
    expected: str,
) -> None:
    eos_sessions, _, _, _ = lifecycle_runtime
    correlation_id = str(uuid4())
    arguments = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "previous_state": "ACTIVE",
        "current_state": "INACTIVE",
        "project_version": 2,
        "profile_policy_ref": POLICY_REF,
        "correlation_id": correlation_id,
        "causation_id": correlation_id,
        "occurred_at": NOW,
        field: value,
    }
    with (
        eos_sessions.begin() as session,
        pytest.raises(EosProjectLifecycleEventError, match=expected),
    ):
        append_project_lifecycle_event(session, **arguments)


def test_project_lifecycle_api_is_signed_eos_only_and_replay_safe(
    lifecycle_runtime,
) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    transport = DirectAeTransport(service)
    publisher = SqlAlchemyEosOutboxPublisher(eos_sessions, clock=lambda: NOW)
    publisher.publish_next(transport, tenant_id=TENANT)
    envelope = transport.envelopes[0]

    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_project_agent_lifecycle_routes(app, service=service)
    client = TestClient(app)
    eos_token = issue_mock_service_token(
        service_id="nex-eos", audience="nex-ae-api", scopes=["service:call"]
    ).access_token
    response = client.post(
        "/internal/v1/project-lifecycle-events",
        json=envelope,
        headers={"Authorization": f"Bearer {eos_token}"},
    )
    assert response.status_code == 200
    assert response.json()["project_code"] == PROJECT_CODE

    wc_token = issue_mock_service_token(
        service_id="nex-wc", audience="nex-ae-api", scopes=["service:call"]
    ).access_token
    denied = client.post(
        "/internal/v1/project-lifecycle-events",
        json=envelope,
        headers={"Authorization": f"Bearer {wc_token}"},
    )
    assert denied.status_code == 403
    assert (
        client.post("/internal/v1/project-lifecycle-events", json=envelope).status_code
        == 401
    )


def test_profile_policy_is_immutable_and_hash_bound(tmp_path: Path) -> None:
    policy = AdmittedProjectAgentProfilePolicy.from_path(POLICY_PATH)
    assert policy.policy_ref == POLICY_REF
    assert policy.profile_ref == "agent-profile://nex-platform/project-agent/v1"
    drifted = tmp_path / "policy.json"
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    value["profile_ref"] = "agent-profile://nex-platform/project-agent/drifted"
    drifted.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProjectAgentLifecycleError, match="hash has drifted"):
        AdmittedProjectAgentProfilePolicy.from_path(drifted)


@pytest.mark.parametrize(
    ("target", "value", "expected"),
    (
        ("event_type", "OTHER", "type is unsupported"),
        ("tenant_id", "OTHER", "tenant binding is invalid"),
        ("event_payload_hash", "invalid", "payload hash is invalid"),
        ("schema_version", "unsupported", "schema is unsupported"),
        ("previous_state", "DRAFT", "previous_state is invalid"),
        ("current_state", "DRAFT", "current_state is invalid"),
        ("project_id", "not-a-uuid", "project_id must be a UUID"),
        ("project_version", True, "must be a positive integer"),
        ("project_code", " padded ", "project_code is invalid"),
        ("occurred_at", None, "must be an ISO-8601 timestamp"),
        ("occurred_at", "not-a-time", "must be an ISO-8601 timestamp"),
        ("occurred_at", "2026-11-12T09:00:00", "timezone-aware"),
    ),
)
def test_lifecycle_envelope_validation_fails_closed(
    lifecycle_runtime,
    target: str,
    value: object,
    expected: str,
) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    envelope = _initial_envelope(eos_sessions)
    if target in {"event_type", "tenant_id", "event_payload_hash"}:
        envelope[target] = value
    else:
        envelope["event_payload"][target] = value
        _rehash(envelope)

    with pytest.raises(ProjectAgentLifecycleError, match=expected):
        service.ingest(envelope)


def test_lifecycle_envelope_and_payload_require_exact_fields(lifecycle_runtime) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    envelope = _initial_envelope(eos_sessions)
    envelope["unexpected"] = True
    with pytest.raises(ProjectAgentLifecycleError, match="envelope is invalid"):
        service.ingest(envelope)

    envelope = _initial_envelope(eos_sessions)
    envelope["event_payload"]["unexpected"] = True
    _rehash(envelope)
    with pytest.raises(ProjectAgentLifecycleError, match="payload is invalid"):
        service.ingest(envelope)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("extra_field", "invalid fields"),
        ("invalid_hash", "hash is invalid"),
        ("unsupported_schema", "schema is unsupported"),
        ("capability_drift", "capability policy has drifted"),
    ),
)
def test_profile_policy_admission_fails_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if mutation == "extra_field":
        value["unexpected"] = True
    elif mutation == "invalid_hash":
        value["policy_hash"] = "invalid"
    elif mutation == "unsupported_schema":
        value["schema_version"] = "unsupported"
        value["policy_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "policy_hash"}
        )
    else:
        value["state_capability_modes"]["ACTIVE"] = "CLOSURE"
        value["policy_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "policy_hash"}
        )
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ProjectAgentLifecycleError, match=expected):
        AdmittedProjectAgentProfilePolicy.from_path(path)

    with pytest.raises(ProjectAgentLifecycleError, match="cannot be loaded"):
        AdmittedProjectAgentProfilePolicy.from_path(tmp_path / "absent.json")


def test_lifecycle_policy_replay_and_transition_conflicts_fail_closed(
    lifecycle_runtime,
) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    initial = _initial_envelope(eos_sessions)

    unadmitted = deepcopy(initial)
    unadmitted["event_payload"]["profile_policy_ref"] = "policy://unadmitted"
    _rehash(unadmitted)
    with pytest.raises(ProjectAgentLifecycleError, match="unadmitted profile policy"):
        service.ingest(unadmitted)

    bad_initial = deepcopy(initial)
    bad_initial["event_payload"]["project_version"] = 2
    _rehash(bad_initial)
    with pytest.raises(ProjectAgentLifecycleError, match="initial ACTIVE v1"):
        service.ingest(bad_initial)

    service.ingest(initial)
    changed_replay = deepcopy(initial)
    changed_replay["event_payload"]["project_code"] = "VO00D269999"
    _rehash(changed_replay)
    with pytest.raises(ProjectAgentLifecycleError, match="immutable semantics"):
        service.ingest(changed_replay)

    cases = (
        ("project_code", "VO00D269999", "Project code changed"),
        ("previous_state", "INACTIVE", "previous state does not match"),
        ("current_state", "CLOSED", "transition is not allowed"),
    )
    for field, value, expected in cases:
        candidate = deepcopy(initial)
        candidate["event_id"] = str(uuid4())
        candidate["event_payload"]["project_version"] = 2
        candidate["event_payload"]["previous_state"] = "ACTIVE"
        candidate["event_payload"]["current_state"] = "INACTIVE"
        candidate["event_payload"][field] = value
        _rehash(candidate)
        with pytest.raises(ProjectAgentLifecycleError, match=expected):
            service.ingest(candidate)


def test_project_lifecycle_api_reports_unavailable_and_invalid_events(
    lifecycle_runtime,
) -> None:
    eos_sessions, _, service, _ = lifecycle_runtime
    token = issue_mock_service_token(
        service_id="nex-eos", audience="nex-ae-api", scopes=["service:call"]
    ).access_token
    headers = {"Authorization": f"Bearer {token}"}
    envelope = _initial_envelope(eos_sessions)

    unavailable_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_project_agent_lifecycle_routes(unavailable_app, service=None)
    unavailable = TestClient(unavailable_app).post(
        "/internal/v1/project-lifecycle-events", json=envelope, headers=headers
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "AE_PROJECT_AGENT_LIFECYCLE_UNAVAILABLE"

    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_project_agent_lifecycle_routes(app, service=service)
    invalid = TestClient(app).post(
        "/internal/v1/project-lifecycle-events",
        json={**envelope, "event_type": "OTHER"},
        headers=headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "AE_PROJECT_AGENT_LIFECYCLE_INVALID"


@pytest.mark.skipif(
    not (
        os.getenv("NEX_EOS_MYBEE_W30_S00C_POSTGRES_SMOKE") == "1"
        and os.getenv("NEX_EOS_TEST_DATABASE_URL")
        and os.getenv("NEX_AE_TEST_DATABASE_URL")
    ),
    reason="Protected W30-S00C EOS/AE PostgreSQL smoke is disabled",
)
def test_project_agent_lifecycle_actual_postgres_smoke() -> None:
    # The protected runner invokes the same lifecycle assertions after applying
    # both services' migrations to isolated schemas in the actual test DBs.
    from run_w30_s00c_project_agent_postgres_smoke import run_smoke

    result = run_smoke(
        eos_database_url=os.environ["NEX_EOS_TEST_DATABASE_URL"],
        ae_database_url=os.environ["NEX_AE_TEST_DATABASE_URL"],
    )
    assert result["status"] == "PASS"
    assert result["project"]["agent_sync_state"] == "IN_SYNC"
    assert result["project_agent"]["status"] == "RETIRED"
    assert result["project_agent"]["identity_count"] == 1
