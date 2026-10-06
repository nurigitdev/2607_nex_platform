from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_cx.trace_projection import (
    CX_TRACE_OPERATIONS_PATH,
    CxTraceProjectionError,
    InMemoryCxTraceProjectionSource,
    SqlAlchemyCxTraceProjectionSource,
    _stage_status,
    _timestamp,
    build_cx_trace_projection,
    register_cx_trace_projection_routes,
)
from nex_runtime import issue_mock_service_token


TRACE_ID = "13741374137413741374137413741374"
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


def _records() -> list[dict[str, object]]:
    base = {
        "trace_id": TRACE_ID,
        "request_id": "request-1374",
        "tenant_ref_id": "tenant-private",
        "owner_subject_ref_id": "owner-private",
        "created_at": "2026-10-06T09:00:00Z",
        "updated_at": "2026-10-06T09:05:00Z",
    }
    return [
        {
            **base,
            "record_kind": "ingestion",
            "run_id": "ingestion-1374",
            "status": "SUCCEEDED",
            "current_step": "PUBLISHING",
            "attempt_count": 1,
        },
        {
            **base,
            "record_kind": "retrieval",
            "retrieval_package_id": "retrieval-1374",
            "status": "READY",
            "rerank_state": "APPLIED",
            "updated_at": "2026-10-06T09:06:00Z",
        },
        {
            **base,
            "record_kind": "generation",
            "cx_generation_id": "generation-1374",
            "retrieval_package_id": "retrieval-1374",
            "status": "COMPLETED",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "updated_at": datetime(2026, 10, 6, 9, 7, tzinfo=UTC),
        },
    ]


def test_projection_redacts_owner_and_private_payload() -> None:
    result = build_cx_trace_projection(TRACE_ID, _records(), checked_at=NOW)

    assert result["service_id"] == "nex-cx"
    assert result["source_status"] == "READY"
    assert result["summary"] == {
        "stage_count": 3,
        "by_family": {"GENERATION": 1, "INGESTION": 1, "RETRIEVAL": 1},
        "by_status": {"SUCCEEDED": 3},
        "private_payload_included": False,
    }
    assert [stage["stage_family"] for stage in result["stages"]] == [
        "INGESTION",
        "RETRIEVAL",
        "GENERATION",
    ]
    serialized = str(result)
    assert "tenant-private" not in serialized
    assert "owner-private" not in serialized
    assert all(len(stage["owner_digest"]) == 64 for stage in result["stages"])
    assert result["stages"][2]["safe_attributes"]["model_alias"] == (
        "general-llm-default"
    )


def test_optional_trace_metadata_is_omitted() -> None:
    records = _records()
    records[0]["current_step"] = None
    records[1]["rerank_state"] = None
    records[2]["retrieval_package_id"] = None
    records[2]["alias"] = None
    records[2]["provider_capability"] = None

    result = build_cx_trace_projection(TRACE_ID, records, checked_at=NOW)

    assert "confidence_state" not in result["stages"][0]["safe_attributes"]
    assert "citation_status" not in result["stages"][1]["safe_attributes"]
    assert result["stages"][2]["correlation_refs"] == {
        "cx_generation_id": "generation-1374"
    }


def test_postgresql_uuid_identifiers_are_normalized() -> None:
    records = _records()
    run_id = UUID("13741374-1374-1374-1374-137413741374")
    package_id = UUID("13741374-1374-1374-1374-137413741375")
    records[0]["run_id"] = run_id
    records[1]["retrieval_package_id"] = package_id
    records[2]["retrieval_package_id"] = package_id

    result = build_cx_trace_projection(TRACE_ID, records, checked_at=NOW)

    assert result["stages"][0]["correlation_refs"] == {
        "ingestion_run_id": str(run_id)
    }
    assert result["stages"][1]["correlation_refs"] == {
        "retrieval_package_id": str(package_id)
    }
    assert result["stages"][2]["correlation_refs"]["retrieval_package_id"] == str(
        package_id
    )


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        ("ingestion", "FAILED", "FAILED"),
        ("retrieval", "LOW_CONFIDENCE", "BLOCKED"),
        ("retrieval", "NO_ANSWER", "BLOCKED"),
        ("generation", "CANCELLED", "SKIPPED"),
        ("generation", "RETRYING", "RECOVERING"),
        ("ingestion", "RUNNING", "STARTED"),
    ],
)
def test_status_mapping(kind: str, status: str, expected: str) -> None:
    assert _stage_status(kind, status) == expected


def test_projection_rejects_invalid_records_and_clock() -> None:
    assert str(CxTraceProjectionError("code", "detail")) == "detail"
    assert _timestamp(datetime(2026, 10, 6, 10, 0)) == "2026-10-06T10:00:00Z"
    with pytest.raises(CxTraceProjectionError) as clock_error:
        build_cx_trace_projection(
            TRACE_ID,
            [],
            checked_at=datetime(2026, 10, 6, 10, 0),
        )
    assert clock_error.value.error_code == "cx.trace_clock_invalid"

    for update, code in (
        ({"record_kind": "private"}, "cx.trace_record_kind_invalid"),
        ({"trace_id": "f" * 32}, "cx.trace_record_mismatch"),
        ({"request_id": None}, "cx.trace_record_invalid"),
        ({"tenant_ref_id": None}, "cx.trace_record_invalid"),
        ({"updated_at": None, "created_at": None}, "cx.trace_record_timestamp_invalid"),
        ({"attempt_count": True}, "cx.trace_record_invalid"),
    ):
        record = _records()[0]
        record.update(update)
        with pytest.raises(CxTraceProjectionError) as exc_info:
            build_cx_trace_projection(TRACE_ID, [record], checked_at=NOW)
        assert exc_info.value.error_code == code

    with pytest.raises(CxTraceProjectionError) as kind_error:
        _stage_status("private", "RUNNING")
    assert kind_error.value.error_code == "cx.trace_record_kind_invalid"


def test_in_memory_source_returns_defensive_trace_filter() -> None:
    records = _records() + [{**_records()[0], "trace_id": "f" * 32}]
    source = InMemoryCxTraceProjectionSource(records)

    selected = source.list_trace_records(TRACE_ID)
    selected[0]["status"] = "CHANGED"

    assert len(selected) == 3
    assert source.records[0]["status"] == "SUCCEEDED"


def test_sqlalchemy_source_queries_three_durable_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE cx_ingest_runs (run_id TEXT, status TEXT, "
                "current_step TEXT, attempt_count INTEGER, trace_id TEXT, "
                "request_id TEXT, tenant_ref_id TEXT, owner_subject_ref_id TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE cx_retrieval_packages (retrieval_package_id TEXT, "
                "status TEXT, rerank_state TEXT, trace_id TEXT, request_id TEXT, "
                "tenant_ref_id TEXT, owner_subject_ref_id TEXT, created_at TEXT, "
                "updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE cx_generation_executions (cx_generation_id TEXT, "
                "status TEXT, retrieval_package_id TEXT, trace_id TEXT, "
                "request_id TEXT, tenant_ref_id TEXT, owner_subject_ref_id TEXT, "
                "alias TEXT, provider_capability TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cx_ingest_runs VALUES "
                "('ingestion-1374','SUCCEEDED','PUBLISHING',1,:trace,'request-1374',"
                "'tenant-private','owner-private',:created,:updated)"
            ),
            {"trace": TRACE_ID, "created": "2026-10-06T09:00:00Z", "updated": "2026-10-06T09:05:00Z"},
        )
        connection.execute(
            text(
                "INSERT INTO cx_retrieval_packages VALUES "
                "('retrieval-1374','READY','APPLIED',:trace,'request-1374',"
                "'tenant-private','owner-private',:created,:updated)"
            ),
            {"trace": TRACE_ID, "created": "2026-10-06T09:00:00Z", "updated": "2026-10-06T09:06:00Z"},
        )
        connection.execute(
            text(
                "INSERT INTO cx_generation_executions VALUES "
                "('generation-1374','COMPLETED','retrieval-1374',:trace,'request-1374',"
                "'tenant-private','owner-private','general-llm-default','generation',"
                ":created,:updated)"
            ),
            {"trace": TRACE_ID, "created": "2026-10-06T09:00:00Z", "updated": "2026-10-06T09:07:00Z"},
        )

    source = SqlAlchemyCxTraceProjectionSource(sessionmaker(bind=engine))
    records = source.list_trace_records(TRACE_ID)

    assert [record["record_kind"] for record in records] == [
        "ingestion",
        "retrieval",
        "generation",
    ]
    assert source.list_trace_records("f" * 32) == []


def test_sqlalchemy_source_translates_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    source = SqlAlchemyCxTraceProjectionSource(sessionmaker(bind=engine))

    with pytest.raises(CxTraceProjectionError) as exc_info:
        source.list_trace_records(TRACE_ID)

    assert exc_info.value.error_code == "cx.trace_source_unavailable"


class FailingSource:
    def list_trace_records(self, _trace_id: str) -> list[dict[str, object]]:
        raise CxTraceProjectionError(
            "cx.trace_source_unavailable",
            "unavailable",
        )


def _client(source: object) -> TestClient:
    app = FastAPI()
    register_cx_trace_projection_routes(
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
        audience="nex-cx",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def test_route_requires_ag_operations_scope_and_returns_projection() -> None:
    client = _client(InMemoryCxTraceProjectionSource(_records()))
    path = CX_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID)

    assert client.get(path).status_code == 401
    missing_scope = client.get(
        path,
        headers={"Authorization": _authorization(include_scope=False)},
    )
    assert missing_scope.status_code == 401
    forbidden = client.get(
        path,
        headers={"Authorization": _authorization("nex-ae-api")},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "CX_OPERATIONS_CALLER_FORBIDDEN"

    response = client.get(path, headers={"Authorization": _authorization()})
    assert response.status_code == 200
    assert response.json()["summary"]["stage_count"] == 3


def test_route_translates_invalid_trace_and_source_failure() -> None:
    invalid = _client(InMemoryCxTraceProjectionSource()).get(
        CX_TRACE_OPERATIONS_PATH.format(trace_id="invalid"),
        headers={"Authorization": _authorization()},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "trace.trace_id_invalid"

    unavailable = _client(FailingSource()).get(
        CX_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID),
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
