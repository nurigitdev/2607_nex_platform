from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_oa.auth_events import (
    InMemoryOaAuthEventRepository,
    OaAuthEventError,
    SqlAlchemyOaAuthEventRepository,
)
from nex_oa.trace_projection import (
    OA_TRACE_OPERATIONS_PATH,
    OaTraceProjectionError,
    RepositoryOaTraceProjectionSource,
    _auth_status,
    _opaque_identifier,
    _timestamp,
    build_oa_trace_projection,
    register_oa_trace_projection_routes,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventError,
    build_operational_event,
    issue_mock_service_token,
)

TRACE_ID = "13761376137613761376137613761376"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _auth_record(outcome: str = "SUCCEEDED") -> dict[str, object]:
    return {
        "record_kind": "auth",
        "event_id": "oa-auth-1376",
        "event_type": "LOGIN_SUCCEEDED",
        "outcome": outcome,
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-private"},
        "subject_ref": {"type": "oa.user", "id": "owner-private"},
        "request_id": "request-1376",
        "trace_id": TRACE_ID,
        "details": {},
        "occurred_at": "2026-10-06T11:00:00Z",
    }


def _trust_record(severity: str = "INFO") -> dict[str, object]:
    return {
        "record_kind": "trust",
        "event_id": "oa-trust-1376",
        "event_type": "oa.service_token.issued",
        "severity": severity,
        "request_id": None,
        "trace_id": TRACE_ID,
        "details": {},
        "created_at": datetime(2026, 10, 6, 11, 1, tzinfo=UTC),
    }


def test_projection_redacts_owner_and_combines_auth_and_trust() -> None:
    result = build_oa_trace_projection(
        TRACE_ID,
        [_auth_record(), _trust_record()],
        checked_at=NOW,
    )

    assert result["service_id"] == "nex-oa"
    assert result["summary"] == {
        "stage_count": 2,
        "by_family": {"AUTH": 2},
        "by_status": {"SUCCEEDED": 2},
        "private_payload_included": False,
    }
    serialized = str(result)
    assert "tenant-private" not in serialized
    assert "owner-private" not in serialized
    assert len(result["stages"][0]["owner_digest"]) == 64
    assert "owner_digest" not in result["stages"][1]
    assert result["stages"][1]["request_id"].startswith("oa-request-")


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("SUCCEEDED", "SUCCEEDED"), ("FAILED", "FAILED"), ("BLOCKED", "BLOCKED")],
)
def test_auth_status(outcome: str, expected: str) -> None:
    assert _auth_status(outcome) == expected


def test_projection_failure_metadata_and_identifier_hashing() -> None:
    auth = _auth_record("FAILED")
    auth["details"] = {"error_code": "INVALID_CREDENTIAL"}
    auth["request_id"] = "private request with spaces"
    trust = _trust_record("ERROR")
    trust["details"] = {"error_code": "TOKEN_REJECTED"}

    result = build_oa_trace_projection(
        TRACE_ID,
        [auth, trust],
        checked_at=NOW,
    )

    assert result["summary"]["by_status"] == {"FAILED": 2}
    assert result["stages"][0]["safe_attributes"]["failure_code"] == (
        "INVALID_CREDENTIAL"
    )
    assert _opaque_identifier("prefix", "valid-id") == "valid-id"
    assert _opaque_identifier("prefix", "bad id").startswith("prefix-")

    without_owner = _auth_record()
    without_owner["tenant_ref"] = None
    ownerless = build_oa_trace_projection(
        TRACE_ID,
        [without_owner],
        checked_at=NOW,
    )
    assert "owner_digest" not in ownerless["stages"][0]


def test_projection_rejects_invalid_records_and_clock() -> None:
    assert str(OaTraceProjectionError("code", "detail")) == "detail"
    assert _timestamp(datetime(2026, 10, 6, 12, 0)) == "2026-10-06T12:00:00Z"
    with pytest.raises(OaTraceProjectionError) as clock_error:
        build_oa_trace_projection(
            TRACE_ID,
            [],
            checked_at=datetime(2026, 10, 6, 12, 0),
        )
    assert clock_error.value.error_code == "oa.trace_clock_invalid"

    for record, update, code in (
        (_auth_record(), {"record_kind": "private"}, "oa.trace_record_kind_invalid"),
        (_auth_record(), {"trace_id": "f" * 32}, "oa.trace_record_mismatch"),
        (_auth_record(), {"event_id": None}, "oa.trace_record_invalid"),
        (_auth_record(), {"outcome": "UNKNOWN"}, "oa.trace_record_invalid"),
        (_auth_record(), {"occurred_at": None}, "oa.trace_record_timestamp_invalid"),
        (_trust_record(), {"severity": None}, "oa.trace_record_invalid"),
        (_trust_record(), {"created_at": None}, "oa.trace_record_timestamp_invalid"),
    ):
        record.update(update)
        with pytest.raises(OaTraceProjectionError) as exc_info:
            build_oa_trace_projection(TRACE_ID, [record], checked_at=NOW)
        assert exc_info.value.error_code == code


def _raw_auth_event(trace_id: str = TRACE_ID) -> dict[str, object]:
    return {
        "event_id": "oa-auth-1376",
        "event_schema_version": "oa_auth_event.v1",
        "event_type": "LOGIN_SUCCEEDED",
        "outcome": "SUCCEEDED",
        "tenant_id": "tenant-private",
        "subject_id": "owner-private",
        "credential_id": None,
        "actor_ref": "nex.service:nex-ae-api",
        "request_id": "request-1376",
        "trace_id": trace_id,
        "details": {},
        "occurred_at": "2026-10-06T11:00:00Z",
        "created_at": "2026-10-06T11:00:00Z",
    }


def test_repository_source_combines_trace_filtered_stores() -> None:
    auth_repository = InMemoryOaAuthEventRepository(
        [_raw_auth_event(), _raw_auth_event("f" * 32)]
    )
    operations = InMemoryOperationalEventStore()
    operations.append(
        build_operational_event(
            service_id="nex-oa",
            event_type="oa.service_token.issued",
            severity="INFO",
            message="issued",
            trace_id=TRACE_ID,
            request_id="request-1376",
            created_at="2026-10-06T11:01:00Z",
        )
    )
    source = RepositoryOaTraceProjectionSource(auth_repository, operations)

    records = source.list_trace_records(TRACE_ID)

    assert [record["record_kind"] for record in records] == ["auth", "trust"]


def test_sqlalchemy_auth_repository_reads_by_trace() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE oa_auth_events (event_id TEXT, event_schema_version TEXT, "
                "event_type TEXT, outcome TEXT, tenant_id TEXT, subject_id TEXT, "
                "credential_id TEXT, actor_ref TEXT, request_id TEXT, trace_id TEXT, "
                "details TEXT, occurred_at TEXT, created_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO oa_auth_events VALUES "
                "('oa-auth-1376','oa_auth_event.v1','LOGIN_SUCCEEDED','SUCCEEDED',"
                "'tenant-private','owner-private',NULL,'nex.service:nex-ae-api',"
                "'request-1376',:trace,'{}',:at,:at)"
            ),
            {"trace": TRACE_ID, "at": "2026-10-06T11:00:00Z"},
        )
    repository = SqlAlchemyOaAuthEventRepository(sessionmaker(bind=engine))

    assert len(repository.list_events_by_trace(TRACE_ID)) == 1
    assert repository.list_events_by_trace("f" * 32) == []


class FailingAuthRepository:
    def list_events_by_trace(self, _trace_id: str, *, limit: int = 500):
        raise OaAuthEventError(503, "oa.auth_event_store_unavailable", "unavailable")


def test_repository_source_translates_failure() -> None:
    source = RepositoryOaTraceProjectionSource(
        FailingAuthRepository(),  # type: ignore[arg-type]
        InMemoryOperationalEventStore(),
    )
    with pytest.raises(OaTraceProjectionError) as exc_info:
        source.list_trace_records(TRACE_ID)
    assert exc_info.value.error_code == "oa.trace_source_unavailable"


def _authorization(service_id: str = "nex-ag", *, scope: bool = True) -> str:
    scopes = ["service:call"] + (["operations:read"] if scope else [])
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-oa",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def _client(source: object) -> TestClient:
    app = FastAPI()
    register_oa_trace_projection_routes(
        app,
        source=source,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    return TestClient(app)


def test_route_requires_ag_operations_scope() -> None:
    source = type("Source", (), {"list_trace_records": lambda self, trace: []})()
    client = _client(source)
    path = OA_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID)

    assert client.get(path).status_code == 401
    assert (
        client.get(
            path, headers={"Authorization": _authorization(scope=False)}
        ).status_code
        == 401
    )
    forbidden = client.get(path, headers={"Authorization": _authorization("nex-cx")})
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "OA_OPERATIONS_CALLER_FORBIDDEN"
    assert (
        client.get(path, headers={"Authorization": _authorization()}).status_code == 200
    )


def test_route_translates_invalid_trace_and_source_failure() -> None:
    empty = type("Source", (), {"list_trace_records": lambda self, trace: []})()
    invalid = _client(empty).get(
        OA_TRACE_OPERATIONS_PATH.format(trace_id="invalid"),
        headers={"Authorization": _authorization()},
    )
    assert invalid.status_code == 422

    failing = type(
        "Source",
        (),
        {
            "list_trace_records": lambda self, trace: (_ for _ in ()).throw(
                OaTraceProjectionError("oa.trace_source_unavailable", "unavailable")
            )
        },
    )()
    unavailable = _client(failing).get(
        OA_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID),
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503
