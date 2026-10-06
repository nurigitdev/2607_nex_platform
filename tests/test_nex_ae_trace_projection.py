from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_ae_api.trace_projection import (
    AE_TRACE_OPERATIONS_PATH,
    AeTraceProjectionError,
    InMemoryAeTraceProjectionSource,
    SqlAlchemyAeTraceProjectionSource,
    _stage_status,
    _timestamp,
    build_ae_trace_projection,
    register_ae_trace_projection_routes,
)
from nex_runtime import issue_mock_service_token

TRACE_ID = "13751375137513751375137513751375"
NOW = datetime(2026, 10, 6, 11, 0, tzinfo=UTC)


def _records() -> list[dict[str, object]]:
    common = {
        "trace_id": TRACE_ID,
        "request_id": "request-1375",
        "tenant_id": "tenant-private",
        "owner_user_id": "owner-private",
        "created_at": "2026-10-06T10:00:00Z",
    }
    return [
        {
            **common,
            "record_kind": "upload",
            "upload_handoff_id": "upload-1375",
            "cx_upload_id": "cx-upload-1375",
            "ingestion_job_id": "ingestion-1375",
            "status": "READY",
            "updated_at": "2026-10-06T10:01:00Z",
        },
        {
            **common,
            "record_kind": "response",
            "chat_interaction_id": "response-1375",
            "cx_retrieval_package_id": "retrieval-1375",
            "cx_generation_id": "generation-1375",
            "cx_generation_status": "CITATIONS_VALID",
            "status": "COMPLETED",
            "updated_at": "2026-10-06T10:02:00Z",
        },
        {
            **common,
            "record_kind": "artifact",
            "artifact_id": "artifact-1375",
            "status": "READY",
            "updated_at": "2026-10-06T10:03:00Z",
        },
        {
            **common,
            "record_kind": "render",
            "artifact_id": "artifact-1375",
            "render_job_id": "render-1375",
            "status": "COMPLETED",
            "progress_percent": 100,
            "retryable": False,
            "failure_code": None,
            "updated_at": datetime(2026, 10, 6, 10, 4, tzinfo=UTC),
        },
        {
            "record_kind": "access",
            "event_id": "access-event-1375",
            "event_type": "ae.artifact_access.preview.succeeded",
            "trace_id": TRACE_ID,
            "request_id": "request-access-1375",
            "subject_id": "artifact-file-1375",
            "details": {
                "access_type": "preview",
                "result_code": "SUCCEEDED",
                "artifact_id": "artifact-1375",
            },
            "created_at": "2026-10-06T10:05:00Z",
            "updated_at": "2026-10-06T10:05:00Z",
        },
    ]


def test_projection_redacts_owner_and_private_fields() -> None:
    result = build_ae_trace_projection(TRACE_ID, _records(), checked_at=NOW)

    assert result["service_id"] == "nex-ae-api"
    assert result["summary"] == {
        "stage_count": 5,
        "by_family": {
            "ACCESS": 1,
            "ARTIFACT": 2,
            "GENERATION": 1,
            "UPLOAD": 1,
        },
        "by_status": {"SUCCEEDED": 5},
        "private_payload_included": False,
    }
    assert [stage["stage_family"] for stage in result["stages"]] == [
        "UPLOAD",
        "GENERATION",
        "ARTIFACT",
        "ARTIFACT",
        "ACCESS",
    ]
    serialized = str(result)
    assert "tenant-private" not in serialized
    assert "owner-private" not in serialized
    assert all(len(stage["owner_digest"]) == 64 for stage in result["stages"][:4])
    assert "owner_digest" not in result["stages"][4]
    assert result["stages"][1]["correlation_refs"] == {
        "response_id": "response-1375",
        "retrieval_package_id": "retrieval-1375",
        "cx_generation_id": "generation-1375",
    }
    assert result["stages"][3]["safe_attributes"]["progress_percent"] == 100


def test_optional_metadata_is_omitted() -> None:
    records = _records()
    records[0]["ingestion_job_id"] = None
    records[1]["cx_retrieval_package_id"] = None
    records[1]["cx_generation_id"] = None
    records[1]["cx_generation_status"] = None
    records[3]["failure_code"] = "RENDER_FAILED"

    result = build_ae_trace_projection(TRACE_ID, records, checked_at=NOW)

    assert result["stages"][0]["correlation_refs"] == {"upload_id": "upload-1375"}
    assert result["stages"][1]["correlation_refs"] == {"response_id": "response-1375"}
    assert "citation_status" not in result["stages"][1]["safe_attributes"]
    assert result["stages"][3]["safe_attributes"]["failure_code"] == ("RENDER_FAILED")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ALREADY_EXISTS", "SUCCEEDED"),
        ("FAILED", "FAILED"),
        ("NO_ANSWER", "BLOCKED"),
        ("CANCELLED", "SKIPPED"),
        ("ARCHIVED", "SKIPPED"),
        ("RETRYING", "RECOVERING"),
        ("RUNNING", "STARTED"),
    ],
)
def test_status_mapping(status: str, expected: str) -> None:
    assert _stage_status(status) == expected


def test_projection_rejects_invalid_records_and_clock() -> None:
    assert str(AeTraceProjectionError("code", "detail")) == "detail"
    assert _timestamp(datetime(2026, 10, 6, 11, 0)) == "2026-10-06T11:00:00Z"
    with pytest.raises(AeTraceProjectionError) as clock_error:
        build_ae_trace_projection(
            TRACE_ID,
            [],
            checked_at=datetime(2026, 10, 6, 11, 0),
        )
    assert clock_error.value.error_code == "ae.trace_clock_invalid"

    mutations = (
        (0, {"record_kind": "private"}, "ae.trace_record_kind_invalid"),
        (0, {"trace_id": "f" * 32}, "ae.trace_record_mismatch"),
        (0, {"request_id": None}, "ae.trace_record_invalid"),
        (0, {"tenant_id": None}, "ae.trace_record_invalid"),
        (
            0,
            {"updated_at": None, "created_at": None},
            "ae.trace_record_timestamp_invalid",
        ),
        (0, {"upload_handoff_id": None}, "ae.trace_record_invalid"),
        (1, {"chat_interaction_id": None}, "ae.trace_record_invalid"),
        (2, {"artifact_id": None}, "ae.trace_record_invalid"),
        (3, {"render_job_id": None}, "ae.trace_record_invalid"),
        (3, {"progress_percent": True}, "ae.trace_record_invalid"),
        (3, {"retryable": "false"}, "ae.trace_record_invalid"),
    )
    for record_index, update, code in mutations:
        record = _records()[record_index]
        record.update(update)
        with pytest.raises(AeTraceProjectionError) as exc_info:
            build_ae_trace_projection(TRACE_ID, [record], checked_at=NOW)
        assert exc_info.value.error_code == code


def test_in_memory_source_filters_and_copies() -> None:
    source = InMemoryAeTraceProjectionSource(
        _records() + [{**_records()[0], "trace_id": "f" * 32}]
    )

    selected = source.list_trace_records(TRACE_ID)
    selected[0]["status"] = "CHANGED"

    assert len(selected) == 5
    assert source.records[0]["status"] == "READY"


def _sqlite_source() -> SqlAlchemyAeTraceProjectionSource:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_upload_handoffs (upload_handoff_id TEXT, status TEXT, cx_upload_id TEXT, ingestion_job_id TEXT, trace_id TEXT, request_id TEXT, tenant_id TEXT, owner_user_id TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_chat_interactions (chat_interaction_id TEXT, status TEXT, cx_retrieval_package_id TEXT, cx_generation_id TEXT, cx_generation_status TEXT, trace_id TEXT, request_id TEXT, tenant_id TEXT, user_id TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_artifacts (artifact_id TEXT, artifact_status TEXT, trace_id TEXT, request_id TEXT, tenant_id TEXT, owner_user_id TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_artifact_render_jobs (render_job_id TEXT, artifact_id TEXT, job_status TEXT, progress_percent INTEGER, retryable BOOLEAN, failure_code TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE service_operational_events (event_id TEXT, service_id TEXT, event_type TEXT, trace_id TEXT, request_id TEXT, subject_id TEXT, details TEXT, created_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_upload_handoffs VALUES ('upload-1375','READY','cx-upload-1375','ingestion-1375',:trace,'request-1375','tenant-private','owner-private',:created,:updated)"
            ),
            {
                "trace": TRACE_ID,
                "created": "2026-10-06T10:00:00Z",
                "updated": "2026-10-06T10:01:00Z",
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_chat_interactions VALUES ('response-1375','COMPLETED','retrieval-1375','generation-1375','CITATIONS_VALID',:trace,'request-1375','tenant-private','owner-private',:created,:updated)"
            ),
            {
                "trace": TRACE_ID,
                "created": "2026-10-06T10:00:00Z",
                "updated": "2026-10-06T10:02:00Z",
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifacts VALUES ('artifact-1375','READY',:trace,'request-1375','tenant-private','owner-private',:created,:updated)"
            ),
            {
                "trace": TRACE_ID,
                "created": "2026-10-06T10:00:00Z",
                "updated": "2026-10-06T10:03:00Z",
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifact_render_jobs VALUES ('render-1375','artifact-1375','COMPLETED',100,0,NULL,:created,:updated)"
            ),
            {"created": "2026-10-06T10:03:00Z", "updated": "2026-10-06T10:04:00Z"},
        )
        connection.execute(
            text(
                "INSERT INTO service_operational_events VALUES ('access-event-1375','nex-ae-api','ae.artifact_access.preview.succeeded',:trace,'request-access-1375','artifact-file-1375',:details,:created)"
            ),
            {
                "trace": TRACE_ID,
                "details": '{"access_type":"preview","result_code":"SUCCEEDED","artifact_id":"artifact-1375"}',
                "created": "2026-10-06T10:05:00Z",
            },
        )
    return SqlAlchemyAeTraceProjectionSource(sessionmaker(bind=engine))


def test_sqlalchemy_source_queries_existing_durable_tables() -> None:
    source = _sqlite_source()

    records = source.list_trace_records(TRACE_ID)

    assert [record["record_kind"] for record in records] == [
        "upload",
        "response",
        "artifact",
        "render",
        "access",
    ]
    assert source.list_trace_records("f" * 32) == []


def test_sqlalchemy_source_translates_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    source = SqlAlchemyAeTraceProjectionSource(sessionmaker(bind=engine))

    with pytest.raises(AeTraceProjectionError) as exc_info:
        source.list_trace_records(TRACE_ID)

    assert exc_info.value.error_code == "ae.trace_source_unavailable"


class FailingSource:
    def list_trace_records(self, _trace_id: str) -> list[dict[str, object]]:
        raise AeTraceProjectionError("ae.trace_source_unavailable", "unavailable")


def _client(source: object) -> TestClient:
    app = FastAPI()
    register_ae_trace_projection_routes(
        app,
        source=source,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    return TestClient(app)


def _authorization(service_id: str = "nex-ag", *, include_scope: bool = True) -> str:
    scopes = ["service:call"]
    if include_scope:
        scopes.append("operations:read")
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-ae-api",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def test_route_requires_ag_operations_scope_and_returns_projection() -> None:
    client = _client(InMemoryAeTraceProjectionSource(_records()))
    path = AE_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID)

    assert client.get(path).status_code == 401
    assert (
        client.get(
            path,
            headers={"Authorization": _authorization(include_scope=False)},
        ).status_code
        == 401
    )
    forbidden = client.get(
        path,
        headers={"Authorization": _authorization("nex-cx")},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "AE_OPERATIONS_CALLER_FORBIDDEN"

    response = client.get(path, headers={"Authorization": _authorization()})
    assert response.status_code == 200
    assert response.json()["summary"]["stage_count"] == 5


def test_route_translates_invalid_trace_and_source_failure() -> None:
    invalid = _client(InMemoryAeTraceProjectionSource()).get(
        AE_TRACE_OPERATIONS_PATH.format(trace_id="invalid"),
        headers={"Authorization": _authorization()},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "trace.trace_id_invalid"

    unavailable = _client(FailingSource()).get(
        AE_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID),
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
