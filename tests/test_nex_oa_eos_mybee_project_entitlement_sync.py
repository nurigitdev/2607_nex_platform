from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from nex_eos.business_transactions import EOS_METADATA
from nex_eos.oa_outbox_transport import (
    HttpOaProjectEntitlementTransport,
    RoutingEosOutboxTransport,
)
from nex_eos.outbox_publication import (
    EosOutboxEvent,
    EosOutboxPublicationError,
    EosOutboxPublishReceipt,
    SqlAlchemyEosOutboxPublisher,
)
from nex_eos.project_entitlement_events import (
    EosProjectEntitlementEventError,
    PROJECT_ENTITLEMENT_EVENT_TYPE,
    append_project_entitlement_snapshot,
)
from nex_eos.projects import (
    EOS_PROJECT_TABLE,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
)
from nex_oa.project_entitlement_sync import (
    OA_PROJECT_ENTITLEMENT_WRITE_SCOPE,
    InMemoryOaProjectEntitlementInbox,
    SqlAlchemyOaProjectEntitlementInbox,
    register_project_entitlement_sync_routes,
)
from nex_oa import project_entitlement_sync
from nex_oa.authorization import OaAuthorizationError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    psycopg_database_url,
)
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
NVT_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_CODE = "VO00D260001"
EVENT_ID = "33333333-3333-4333-8333-333333333333"
OPERATION_ID = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)


def _payload(*, version: int = 1) -> dict[str, object]:
    return {
        "schema_version": "eos.project_entitlement_snapshot.v1",
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_status": "ACTIVE",
        "source_version": version,
        "members": [
            {"subject_id": "employee-100", "project_role": "OWNER"},
            {"subject_id": "employee-200", "project_role": "MEMBER"},
        ],
        "correlation_id": "wc-work-1",
        "causation_id": "wc-event-1",
        "occurred_at": "2026-11-12T05:00:00Z",
    }


def _envelope(*, version: int = 1, event_id: str = EVENT_ID) -> dict[str, object]:
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    payload = _payload(version=version)
    return {
        "event_id": event_id,
        "tenant_id": TENANT,
        "business_operation_id": OPERATION_ID,
        "event_type": PROJECT_ENTITLEMENT_EVENT_TYPE,
        "event_payload": payload,
        "event_payload_hash": semantic_sha256_hash_ref(payload),
    }


def _event(envelope: dict[str, object] | None = None) -> EosOutboxEvent:
    value = envelope or _envelope()
    return EosOutboxEvent(
        outbox_id="55555555-5555-4555-8555-555555555555",
        tenant_id=str(value["tenant_id"]),
        event_id=str(value["event_id"]),
        business_operation_id=str(value["business_operation_id"]),
        event_type=str(value["event_type"]),
        event_payload=dict(value["event_payload"]),  # type: ignore[arg-type]
        event_payload_hash=str(value["event_payload_hash"]),
    )


def test_inbox_applies_exact_snapshot_replay_and_stale_rules() -> None:
    inbox = InMemoryOaProjectEntitlementInbox()
    first = inbox.apply_event(_envelope())
    replay = inbox.apply_event(_envelope())
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert len(inbox.events) == 1
    assert len(inbox.grants) == 2
    assert {value["source_event_id"] for value in inbox.grants.values()} == {EVENT_ID}

    changed = _envelope()
    changed["event_payload"] = {**_payload(), "project_status": "CLOSING"}
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    changed["event_payload_hash"] = semantic_sha256_hash_ref(changed["event_payload"])
    with pytest.raises(Exception, match="immutable semantics"):
        inbox.apply_event(changed)
    stale = _envelope(event_id="66666666-6666-4666-8666-666666666666")
    with pytest.raises(Exception, match="stale or conflicting"):
        inbox.apply_event(stale)


def test_inbox_replaces_snapshot_and_revokes_absent_member() -> None:
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    inbox = InMemoryOaProjectEntitlementInbox()
    inbox.apply_event(_envelope())
    second = _envelope(version=2, event_id="77777777-7777-4777-8777-777777777777")
    second_payload = dict(second["event_payload"])  # type: ignore[arg-type]
    second_payload["members"] = [
        {"subject_id": "employee-100", "project_role": "MANAGER"}
    ]
    second["event_payload"] = second_payload
    second["event_payload_hash"] = semantic_sha256_hash_ref(second_payload)
    inbox.apply_event(second)
    assert (
        inbox.grants[(TENANT, PROJECT_CODE, "employee-100")]["project_role"]
        == "MANAGER"
    )
    assert (
        inbox.grants[(TENANT, PROJECT_CODE, "employee-200")]["grant_status"]
        == "REVOKED"
    )


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (lambda value: value.update(tenant_id="OTHER"), "tenant binding"),
        (
            lambda value: value.update(event_payload_hash="sha256:" + "0" * 64),
            "does not match",
        ),
        (lambda value: value.update(event_type="OTHER"), "unsupported"),
    ],
)
def test_inbox_fails_closed_for_tenant_hash_and_type(mutation, expected) -> None:
    value = _envelope()
    mutation(value)
    with pytest.raises(Exception, match=expected):
        InMemoryOaProjectEntitlementInbox().apply_event(value)


def _mutated_envelope(kind: str) -> dict[str, object]:
    value = _envelope()
    payload = dict(value["event_payload"])  # type: ignore[arg-type]
    if kind == "envelope_fields":
        value.pop("event_id")
    elif kind == "payload_type":
        value["event_payload"] = []
        return value
    elif kind == "payload_fields":
        payload.pop("correlation_id")
    elif kind == "schema":
        payload["schema_version"] = "unsupported"
    elif kind == "hash_format":
        value["event_payload_hash"] = "bad"
        return value
    elif kind == "members_empty":
        payload["members"] = []
    elif kind == "member_shape":
        payload["members"] = [{"subject_id": "employee-100"}]
    elif kind == "member_duplicate":
        payload["members"] = [
            {"subject_id": "employee-100", "project_role": "OWNER"},
            {"subject_id": "employee-100", "project_role": "MEMBER"},
        ]
    elif kind == "member_subject":
        payload["members"] = [{"subject_id": " bad", "project_role": "OWNER"}]
    elif kind == "member_role":
        payload["members"] = [{"subject_id": "employee-100", "project_role": "ROOT"}]
    elif kind == "project_code":
        payload["project_code"] = "bad"
    elif kind == "project_status":
        payload["project_status"] = "DRAFT"
    elif kind == "source_version":
        payload["source_version"] = 0
    elif kind == "project_id":
        payload["project_id"] = "bad"
    elif kind == "occurred_at":
        payload["occurred_at"] = "not-a-time"
    elif kind == "occurred_at_naive":
        payload["occurred_at"] = "2026-01-01T00:00:00"
    elif kind == "event_id":
        value["event_id"] = "bad"
    elif kind == "operation_id":
        value["business_operation_id"] = "bad"
    else:  # pragma: no cover - test helper guard
        raise AssertionError(kind)
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    value["event_payload"] = payload
    value["event_payload_hash"] = semantic_sha256_hash_ref(payload)
    return value


@pytest.mark.parametrize(
    "kind",
    [
        "envelope_fields",
        "payload_type",
        "payload_fields",
        "schema",
        "hash_format",
        "members_empty",
        "member_shape",
        "member_duplicate",
        "member_subject",
        "member_role",
        "project_code",
        "project_status",
        "source_version",
        "project_id",
        "occurred_at",
        "occurred_at_naive",
        "event_id",
        "operation_id",
    ],
)
def test_event_admission_rejects_malformed_semantics(kind: str) -> None:
    with pytest.raises(OaAuthorizationError):
        InMemoryOaProjectEntitlementInbox().apply_event(_mutated_envelope(kind))


def test_memory_snapshot_ignores_other_projects_and_parses_string_replay() -> None:
    inbox = InMemoryOaProjectEntitlementInbox()
    event = project_entitlement_sync._admit_event(_envelope())
    inbox.grants[(TENANT, "VO00D260002", "employee-300")] = {
        "subject_id": "employee-300",
        "project_role": "MEMBER",
        "grant_status": "ACTIVE",
        "granted_at": NOW,
    }
    inbox.apply_event(_envelope())
    assert (TENANT, "VO00D260002", "employee-300") in inbox.grants
    current = {
        **event,
        "event_payload": json.dumps(event["event_payload"], sort_keys=True),
    }
    project_entitlement_sync._require_same_event(current, event)


class _FailingSession:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.rolled_back = False
        self.closed = False

    def begin(self) -> None:
        return None

    def execute(self, *_args, **_kwargs):
        raise self.exc

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "exc, status",
    [
        (IntegrityError("insert", {}, RuntimeError("collision")), 409),
        (SQLAlchemyError("down"), 503),
    ],
)
def test_sql_inbox_maps_integrity_and_availability_failures(exc, status) -> None:
    session = _FailingSession(exc)
    inbox = SqlAlchemyOaProjectEntitlementInbox(lambda: session)  # type: ignore[arg-type]
    with pytest.raises(OaAuthorizationError) as caught:
        inbox.apply_event(_envelope())
    assert caught.value.status_code == status
    assert session.rolled_back is True
    assert session.closed is True


def test_runtime_factory_selects_persistent_and_memory_profiles() -> None:
    persistent = project_entitlement_sync.build_project_entitlement_inbox_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_POSTGRES, api_session_factory=object())
    )
    memory = project_entitlement_sync.build_project_entitlement_inbox_for_runtime(
        SimpleNamespace(mode="MEMORY", api_session_factory=None)
    )
    assert isinstance(persistent, SqlAlchemyOaProjectEntitlementInbox)
    assert isinstance(memory, InMemoryOaProjectEntitlementInbox)


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def test_http_transport_and_router_validate_exact_oa_ack() -> None:
    captured = {}

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        return _Response(
            {
                "event_id": EVENT_ID,
                "event_payload_hash": _event().event_payload_hash,
                "receipt_ref": f"oa.project-entitlement:{EVENT_ID}:v1",
                "inbox_state": "APPLIED",
            }
        )

    oa = HttpOaProjectEntitlementTransport(
        base_url="http://oa.local/",
        service_token="signed",
        timeout_seconds=7,
        opener=opener,
    )
    ae_events = []

    class Ae:
        def publish(self, event):
            ae_events.append(event.event_type)
            return EosOutboxPublishReceipt(
                event.event_id, event.event_payload_hash, "ae:receipt"
            )

    routed = RoutingEosOutboxTransport(ae_transport=Ae(), oa_transport=oa)
    receipt = routed.publish(_event())
    assert receipt.event_id == EVENT_ID
    assert captured == {
        "url": "http://oa.local/internal/v1/auth/project-entitlement-events",
        "timeout": 7.0,
        "authorization": "Bearer signed",
    }
    other = _event({**_envelope(), "event_type": "OTHER"})
    routed.publish(other)
    assert ae_events == ["OTHER"]


def test_http_transport_classifies_terminal_and_retryable_failures() -> None:
    def rejected(*_args, **_kwargs):
        raise HTTPError("http://oa", 409, "conflict", {}, BytesIO())

    with pytest.raises(EosOutboxPublicationError) as terminal:
        HttpOaProjectEntitlementTransport(
            base_url="http://oa", service_token="signed", opener=rejected
        ).publish(_event())
    assert terminal.value.retryable is False

    def unavailable(*_args, **_kwargs):
        raise HTTPError("http://oa", 503, "down", {}, BytesIO())

    with pytest.raises(EosOutboxPublicationError) as retryable:
        HttpOaProjectEntitlementTransport(
            base_url="http://oa", service_token="signed", opener=unavailable
        ).publish(_event())
    assert retryable.value.retryable is True


def _sqlite_runtime():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyEosProjectRepository(sessions)
    repository.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-DEMO", "Demo"))
    repository.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            PROJECT_CODE,
            "Project",
            nvt_project_id=NVT_ID,
            authorization_sync_state="PENDING",
            authorization_version=1,
        )
    )
    with sessions.begin() as session:
        append_project_entitlement_snapshot(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code=PROJECT_CODE,
            project_status="ACTIVE",
            source_version=1,
            members=_payload()["members"],  # type: ignore[arg-type]
            correlation_id="wc-work-1",
            causation_id="wc-event-1",
            occurred_at=NOW,
        )
    return engine, sessions


def test_eos_snapshot_append_is_deterministic_and_rejects_changed_replay() -> None:
    engine, sessions = _sqlite_runtime()
    kwargs = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_status": "ACTIVE",
        "source_version": 1,
        "members": _payload()["members"],
        "correlation_id": "wc-work-1",
        "causation_id": "wc-event-1",
        "occurred_at": NOW,
    }
    with sessions.begin() as session:
        replay = append_project_entitlement_snapshot(session, **kwargs)
        assert replay["delivery_state"] == "PENDING"
        with pytest.raises(
            EosProjectEntitlementEventError, match="different semantics"
        ):
            append_project_entitlement_snapshot(
                session,
                **{
                    **kwargs,
                    "members": [
                        {"subject_id": "employee-100", "project_role": "MANAGER"}
                    ],
                },
            )
    engine.dispose()


@pytest.mark.parametrize(
    "field, value",
    [
        ("tenant_id", " bad"),
        ("project_id", "bad"),
        ("project_code", "bad"),
        ("project_status", "DRAFT"),
        ("source_version", 0),
        ("members", []),
        ("members", [{}]),
        (
            "members",
            [
                {"subject_id": "employee-1", "project_role": "MEMBER"},
                {"subject_id": "employee-1", "project_role": "MEMBER"},
            ],
        ),
        ("members", [{"subject_id": " bad", "project_role": "MEMBER"}]),
        ("members", [{"subject_id": "employee-1", "project_role": "ROOT"}]),
        ("correlation_id", " bad"),
        ("occurred_at", datetime(2026, 1, 1)),
    ],
)
def test_eos_snapshot_append_rejects_malformed_boundary(field, value) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine)
    kwargs = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_status": "ACTIVE",
        "source_version": 1,
        "members": [{"subject_id": "employee-1", "project_role": "OWNER"}],
        "correlation_id": "wc-work-1",
        "causation_id": "wc-event-1",
        "occurred_at": NOW,
    }
    kwargs[field] = value
    with sessions.begin() as session, pytest.raises(EosProjectEntitlementEventError):
        append_project_entitlement_snapshot(session, **kwargs)
    engine.dispose()


def test_publisher_ack_marks_in_sync_and_terminal_failure_is_replayable() -> None:
    engine, sessions = _sqlite_runtime()
    publisher = SqlAlchemyEosOutboxPublisher(sessions, clock=lambda: NOW)

    class Rejected:
        def publish(self, _event):
            raise EosOutboxPublicationError("OA_REJECTED", "invalid", retryable=False)

    rejected = publisher.publish_next(Rejected())
    assert rejected is not None
    assert rejected.retry_required is False
    with sessions() as session:
        assert (
            session.execute(
                select(EOS_PROJECT_TABLE.c.authorization_sync_state)
            ).scalar_one()
            == "FAILED"
        )

    inbox = InMemoryOaProjectEntitlementInbox()

    class Applied:
        def publish(self, event):
            receipt = inbox.apply_event(
                {
                    "event_id": event.event_id,
                    "tenant_id": event.tenant_id,
                    "business_operation_id": event.business_operation_id,
                    "event_type": event.event_type,
                    "event_payload": event.event_payload,
                    "event_payload_hash": event.event_payload_hash,
                }
            )
            return EosOutboxPublishReceipt(
                event.event_id, event.event_payload_hash, receipt["receipt_ref"]
            )

    accepted = publisher.publish_next(Applied())
    assert accepted is not None
    assert accepted.delivery_state == "PUBLISHED"
    with sessions() as session:
        assert (
            session.execute(
                select(EOS_PROJECT_TABLE.c.authorization_sync_state)
            ).scalar_one()
            == "IN_SYNC"
        )
    engine.dispose()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "service_token": "signed"},
        {"base_url": "http://oa", "service_token": ""},
        {"base_url": "http://oa", "service_token": "signed", "timeout_seconds": 0},
        {"base_url": "http://oa", "service_token": "signed", "timeout_seconds": True},
    ],
)
def test_oa_transport_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(EosOutboxPublicationError):
        HttpOaProjectEntitlementTransport(**kwargs)


def test_oa_transport_rejects_invalid_event_and_receipt_shapes() -> None:
    transport = HttpOaProjectEntitlementTransport(
        base_url="http://oa", service_token="signed", opener=lambda *_a, **_k: None
    )
    with pytest.raises(EosOutboxPublicationError, match="event is invalid"):
        transport.publish(object())  # type: ignore[arg-type]
    with pytest.raises(EosOutboxPublicationError, match="unsupported event"):
        transport.publish(_event({**_envelope(), "event_type": "OTHER"}))

    bad_receipts = [
        [],
        {"event_id": "wrong"},
        {
            "event_id": EVENT_ID,
            "event_payload_hash": _event().event_payload_hash,
            "inbox_state": "APPLIED",
            "receipt_ref": " ",
        },
    ]
    for receipt in bad_receipts:
        rejected = HttpOaProjectEntitlementTransport(
            base_url="http://oa",
            service_token="signed",
            opener=lambda *_a, value=receipt, **_k: _Response(value),
        )
        with pytest.raises(EosOutboxPublicationError):
            rejected.publish(_event())


def test_oa_transport_maps_network_and_malformed_json_as_retryable() -> None:
    def network(*_args, **_kwargs):
        raise URLError("down")

    with pytest.raises(EosOutboxPublicationError) as unavailable:
        HttpOaProjectEntitlementTransport(
            base_url="http://oa", service_token="signed", opener=network
        ).publish(_event())
    assert unavailable.value.retryable is True

    class InvalidJson(_Response):
        def read(self) -> bytes:
            return b"not-json"

    with pytest.raises(EosOutboxPublicationError) as malformed:
        HttpOaProjectEntitlementTransport(
            base_url="http://oa",
            service_token="signed",
            opener=lambda *_a, **_k: InvalidJson(None),
        ).publish(_event())
    assert malformed.value.retryable is True


def _headers(service_id: str = "nex-eos", *scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_oa_route_is_scope_and_caller_protected() -> None:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_project_entitlement_sync_routes(
        app, inbox=InMemoryOaProjectEntitlementInbox()
    )
    client = TestClient(app)
    path = "/internal/v1/auth/project-entitlement-events"
    assert client.post(path, json=_envelope()).status_code == 401
    assert (
        client.post(
            path, json=_envelope(), headers=_headers("nex-eos", "authorization:read")
        ).status_code
        == 403
    )
    assert (
        client.post(
            path,
            json=_envelope(),
            headers=_headers("nex-wc", OA_PROJECT_ENTITLEMENT_WRITE_SCOPE),
        ).status_code
        == 403
    )
    accepted = client.post(
        path,
        json=_envelope(),
        headers=_headers("nex-eos", OA_PROJECT_ENTITLEMENT_WRITE_SCOPE),
    )
    assert accepted.status_code == 200
    assert accepted.json()["inbox_state"] == "APPLIED"
    assert accepted.headers["cache-control"] == "no-store, max-age=0"


def test_oa_route_returns_configured_admission_problem(monkeypatch) -> None:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    app.state.service_token_admission = object()
    register_project_entitlement_sync_routes(
        app, inbox=InMemoryOaProjectEntitlementInbox()
    )
    monkeypatch.setattr(
        project_entitlement_sync,
        "authorize_oa_service_request",
        lambda *_args, **_kwargs: project_entitlement_sync.JSONResponse(
            status_code=503, content={"error_code": "ADMISSION_UNAVAILABLE"}
        ),
    )
    response = TestClient(app).post(
        "/internal/v1/auth/project-entitlement-events", json=_envelope()
    )
    assert response.status_code == 503


EOS_DATABASE_URL = os.getenv(
    "NEX_EOS_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_eos_user:nuri1004@127.0.0.1:5432/nex_eos_test",
)
OA_DATABASE_URL = os.getenv(
    "NEX_OA_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test",
)
POSTGRES_SMOKE = os.getenv("NEX_MYBEE_W40_CA01_S04_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not POSTGRES_SMOKE,
    reason="Protected W40-CA01-S04 EOS/OA PostgreSQL smoke is disabled",
)
def test_actual_postgres_eos_to_oa_ack_replay_and_zero_residue() -> None:
    eos_schema = f"mybee_w40ca01s04_eos_{uuid.uuid4().hex}"
    oa_schema = f"mybee_w40ca01s04_oa_{uuid.uuid4().hex}"
    eos_psycopg = psycopg_database_url(EOS_DATABASE_URL)
    oa_psycopg = psycopg_database_url(OA_DATABASE_URL)
    for url, expected, schema_name in (
        (eos_psycopg, ("nex_eos_test", "nex_eos_user"), eos_schema),
        (oa_psycopg, ("nex_oa_test", "nex_oa_user"), oa_schema),
    ):
        with psycopg.connect(
            url, autocommit=True
        ) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            assert cursor.fetchone() == expected
            cursor.execute(f'CREATE SCHEMA "{schema_name}"')
    eos_url = (
        make_url(EOS_DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={eos_schema}"})
        .render_as_string(hide_password=False)
    )
    oa_url = (
        make_url(OA_DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={oa_schema}"})
        .render_as_string(hide_password=False)
    )
    try:
        assert (
            "2538_eos_project_authorization_sync"
            in run_service_migrations(
                "nex-eos", database_url=eos_url, profile="test"
            ).applied
        )
        assert (
            "2519_oa_project_entitlement_inbox"
            in run_service_migrations(
                "nex-oa", database_url=oa_url, profile="test"
            ).applied
        )
        eos_engine = create_engine(eos_url, pool_pre_ping=True)
        oa_engine = create_engine(oa_url, pool_pre_ping=True)
        eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
        oa_sessions = sessionmaker(bind=oa_engine, expire_on_commit=False)
        with oa_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO oa_tenants (tenant_id, display_name) VALUES (:id, 'W40')"
                ),
                {"id": TENANT},
            )
        eos_repository = SqlAlchemyEosProjectRepository(eos_sessions)
        eos_repository.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-DEMO", "Demo")
        )
        eos_repository.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                PROJECT_CODE,
                "Project",
                nvt_project_id=NVT_ID,
                authorization_sync_state="PENDING",
                authorization_version=1,
            )
        )
        with eos_sessions.begin() as session:
            append_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                project_status="ACTIVE",
                source_version=1,
                members=_payload()["members"],  # type: ignore[arg-type]
                correlation_id="wc-work-1",
                causation_id="wc-event-1",
                occurred_at=NOW,
            )
        inbox = SqlAlchemyOaProjectEntitlementInbox(oa_sessions)

        class DirectOa:
            last = None

            def publish(self, event):
                self.last = {
                    "event_id": event.event_id,
                    "tenant_id": event.tenant_id,
                    "business_operation_id": event.business_operation_id,
                    "event_type": event.event_type,
                    "event_payload": event.event_payload,
                    "event_payload_hash": event.event_payload_hash,
                }
                receipt = inbox.apply_event(self.last)
                return EosOutboxPublishReceipt(
                    event.event_id, event.event_payload_hash, receipt["receipt_ref"]
                )

        transport = DirectOa()
        result = SqlAlchemyEosOutboxPublisher(
            eos_sessions, clock=lambda: NOW
        ).publish_next(transport)
        assert result is not None and result.delivery_state == "PUBLISHED"
        assert inbox.apply_event(transport.last)["replayed"] is True
        stale = dict(transport.last)
        stale["event_id"] = "88888888-8888-4888-8888-888888888888"
        with pytest.raises(OaAuthorizationError, match="stale or conflicting"):
            inbox.apply_event(stale)

        from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

        second_payload = dict(transport.last["event_payload"])
        second_payload["source_version"] = 2
        second_payload["members"] = [
            {"subject_id": "employee-100", "project_role": "MANAGER"}
        ]
        second = {
            **transport.last,
            "event_id": "99999999-9999-4999-8999-999999999999",
            "event_payload": second_payload,
            "event_payload_hash": semantic_sha256_hash_ref(second_payload),
        }
        assert inbox.apply_event(second)["source_version"] == 2
        with eos_sessions() as session:
            assert (
                session.execute(
                    select(EOS_PROJECT_TABLE.c.authorization_sync_state)
                ).scalar_one()
                == "IN_SYNC"
            )
        with oa_sessions() as session:
            assert (
                session.execute(
                    text("SELECT count(*) FROM oa_project_entitlement_inbox")
                ).scalar_one()
                == 2
            )
            assert (
                session.execute(
                    text("SELECT count(*) FROM oa_project_grant")
                ).scalar_one()
                == 2
            )
        eos_engine.dispose()
        oa_engine.dispose()
    finally:
        for url, schema_name in ((eos_psycopg, eos_schema), (oa_psycopg, oa_schema)):
            with psycopg.connect(
                url, autocommit=True
            ) as connection, connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
                assert cursor.fetchone() == (None,)


def test_migrations_and_slice_doc_are_bounded() -> None:
    assert (
        "oa_project_entitlement_inbox"
        in Path(
            "database/nex-oa/migrations/2519_oa_project_entitlement_inbox.sql"
        ).read_text()
    )
    assert (
        "authorization_sync_state"
        in Path(
            "database/nex-eos/migrations/2538_eos_project_authorization_sync.sql"
        ).read_text()
    )


def test_contract_examples_and_openapi_route_are_admitted() -> None:
    root = Path("contracts")
    for stem, example in (
        (
            "project_entitlement_event.v1.schema.json",
            "oa_project_entitlement_event.valid.json",
        ),
        (
            "project_entitlement_receipt.v1.schema.json",
            "oa_project_entitlement_receipt.applied.json",
        ),
    ):
        schema = json.loads(
            (root / "schemas/service/nex_oa" / stem).read_text(encoding="utf-8")
        )
        value = json.loads(
            (root / "examples/auth" / example).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, format_checker=None).validate(value)
    openapi = yaml.safe_load(
        (root / "openapi/nex-oa.openapi.yaml").read_text(encoding="utf-8")
    )
    operation = openapi["paths"]["/internal/v1/auth/project-entitlement-events"]["post"]
    assert operation["x-nex-required-scopes"] == [
        "service:call",
        "project-entitlement:write",
    ]
