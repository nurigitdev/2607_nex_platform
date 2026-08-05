from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from sqlalchemy import text

import nex_runtime.worker_heartbeats as runtime_worker_heartbeats
from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    InMemoryWorkerHeartbeatStore,
    STARTING,
    STOPPED,
    STOPPING,
    SqlAlchemyWorkerHeartbeatStore,
    WORKER_HEARTBEAT_SCHEMA_VERSION,
    WorkerHeartbeatError,
    build_engine,
    build_session_factory,
    build_worker_heartbeat,
    normalize_worker_stale_after_seconds,
    summarize_worker_heartbeats,
    validate_worker_heartbeat,
    worker_heartbeat_is_stale,
)

NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:30Z"
STALE_CHECK = "2026-08-05T00:01:15Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def sqlite_worker_heartbeat_store() -> SqlAlchemyWorkerHeartbeatStore:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_worker_heartbeats (
                    service_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    heartbeat_schema_version TEXT NOT NULL DEFAULT 'worker_heartbeat.v1',
                    worker_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    trace_id TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (service_id, worker_id)
                )
                """
            )
        )
    return SqlAlchemyWorkerHeartbeatStore(build_session_factory(engine))


def sample_heartbeat(**overrides: Any) -> dict[str, Any]:
    heartbeat = build_worker_heartbeat(
        service_id=overrides.pop("service_id", "nex-cx"),
        worker_id=overrides.pop("worker_id", "cx-worker-001"),
        worker_type=overrides.pop("worker_type", "cx.document_processing.worker"),
        status=overrides.pop("status", BUSY),
        active_job_id=overrides.pop("active_job_id", "job-001"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        started_at=overrides.pop("started_at", NOW),
        last_seen_at=overrides.pop("last_seen_at", LATER),
        metadata=overrides.pop("metadata", {"queue": "cx.document_processing"}),
    )
    return {**heartbeat, **overrides}


def test_build_worker_heartbeat_matches_contract_schema_and_returns_copies() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1] / "contracts/schemas/common/worker_heartbeat.v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    heartbeat = sample_heartbeat()
    heartbeat["metadata"]["queue"] = "mutated"
    rebuilt = sample_heartbeat()

    jsonschema.validate(instance=rebuilt, schema=schema)
    assert rebuilt["heartbeat_schema_version"] == WORKER_HEARTBEAT_SCHEMA_VERSION
    assert rebuilt["status"] == BUSY
    assert rebuilt["metadata"] == {"queue": "cx.document_processing"}


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda heartbeat: heartbeat.pop("service_id"), "worker_heartbeat.invalid"),
        (
            lambda heartbeat: heartbeat.__setitem__("heartbeat_schema_version", "other"),
            "worker_heartbeat.schema_version_invalid",
        ),
        (lambda heartbeat: heartbeat.__setitem__("service_id", "nex-unknown"), "worker_heartbeat.service_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("status", "BROKEN"), "worker_heartbeat.status_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("worker_id", ""), "worker_heartbeat.field_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("worker_type", ""), "worker_heartbeat.field_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("trace_id", "ABC"), "worker_heartbeat.trace_id_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("active_job_id", ""), "worker_heartbeat.active_job_id_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("active_job_id", 100), "worker_heartbeat.active_job_id_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("active_job_id", None), "worker_heartbeat.active_job_required"),
        (lambda heartbeat: heartbeat.__setitem__("metadata", []), "worker_heartbeat.metadata_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("started_at", ""), "worker_heartbeat.timestamp_invalid"),
        (lambda heartbeat: heartbeat.__setitem__("last_seen_at", "not-a-date"), "worker_heartbeat.timestamp_invalid"),
        (
            lambda heartbeat: heartbeat.__setitem__("last_seen_at", "2026-08-04T23:59:59Z"),
            "worker_heartbeat.timestamp_order_invalid",
        ),
    ],
)
def test_validate_worker_heartbeat_rejects_invalid_shapes(mutator: Any, error_code: str) -> None:
    heartbeat = sample_heartbeat()
    mutator(heartbeat)

    with pytest.raises(WorkerHeartbeatError) as exc_info:
        validate_worker_heartbeat(heartbeat)

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == 422


def test_validate_worker_heartbeat_rejects_non_object() -> None:
    with pytest.raises(WorkerHeartbeatError) as exc_info:
        validate_worker_heartbeat([])  # type: ignore[arg-type]

    assert exc_info.value.error_code == "worker_heartbeat.invalid"


def test_worker_heartbeat_stale_detection_clamps_threshold_and_accepts_naive_times() -> None:
    stale = sample_heartbeat(started_at="2026-08-05T00:00:00", last_seen_at="2026-08-05T00:00:10")
    fresh = sample_heartbeat(worker_id="cx-worker-002", last_seen_at="2026-08-05T00:01:30Z")

    assert worker_heartbeat_is_stale(stale, checked_at=STALE_CHECK)
    assert not worker_heartbeat_is_stale(fresh, checked_at=STALE_CHECK)
    assert not worker_heartbeat_is_stale(
        fresh,
        stale_after_seconds=0,
        checked_at="2026-08-05T00:01:31Z",
    )
    assert normalize_worker_stale_after_seconds(0) == 1
    assert normalize_worker_stale_after_seconds(100_000) == 86_400
    assert normalize_worker_stale_after_seconds(60) == 60


def test_summarize_worker_heartbeats_counts_status_service_active_and_stale() -> None:
    heartbeats = [
        sample_heartbeat(worker_id="cx-worker-001", status=BUSY, active_job_id="job-001"),
        sample_heartbeat(worker_id="cx-worker-002", status=IDLE, active_job_id=None),
        sample_heartbeat(
            service_id="nex-mo",
            worker_id="mo-worker-001",
            status=STOPPED,
            active_job_id=None,
            last_seen_at=NOW,
        ),
        sample_heartbeat(
            service_id="nex-ag",
            worker_id="ag-worker-001",
            status=STARTING,
            active_job_id=None,
        ),
        sample_heartbeat(
            service_id="nex-oa",
            worker_id="oa-worker-001",
            status=STOPPING,
            active_job_id=None,
        ),
        sample_heartbeat(
            service_id="nex-ae-api",
            worker_id="ae-worker-001",
            status=ERROR,
            active_job_id=None,
        ),
    ]

    summary = summarize_worker_heartbeats(heartbeats, stale_after_seconds=60, checked_at=STALE_CHECK)

    assert summary["total"] == 6
    assert summary["active"] == 3
    assert summary["stale"] == 1
    assert summary["statuses"][BUSY] == 1
    assert summary["statuses"][IDLE] == 1
    assert summary["statuses"][STOPPED] == 1
    assert summary["services"]["nex-cx"] == 2
    assert summary["services"]["nex-mo"] == 1


def test_datetime_helper_accepts_aware_datetime_string_and_utc_now_shape() -> None:
    observed = runtime_worker_heartbeats._parse_wire_datetime("2026-08-05T09:00:00+09:00", "checked_at")

    assert observed == datetime(2026, 8, 5, 0, 0, 0, tzinfo=UTC)
    assert runtime_worker_heartbeats._utc_now().endswith("Z")


def test_in_memory_worker_heartbeat_store_upserts_filters_and_returns_copies() -> None:
    store = InMemoryWorkerHeartbeatStore()
    stored = store.upsert_heartbeat(sample_heartbeat())
    stored["metadata"]["queue"] = "mutated"
    store.upsert_heartbeat(
        sample_heartbeat(
            service_id="nex-mo",
            worker_id="mo-worker-001",
            worker_type="mo.embedding.worker",
            status=IDLE,
            active_job_id=None,
        )
    )

    refreshed = store.upsert_heartbeat(
        sample_heartbeat(
            worker_id="cx-worker-001",
            status=IDLE,
            active_job_id=None,
            last_seen_at="2026-08-05T00:00:45Z",
        )
    )

    assert refreshed["status"] == IDLE
    assert store.get_heartbeat("nex-cx", "cx-worker-001")["metadata"] == {
        "queue": "cx.document_processing"
    }
    assert store.get_heartbeat("nex-cx", "missing") is None
    assert [item["worker_id"] for item in store.list_heartbeats(service_id="nex-cx")] == [
        "cx-worker-001"
    ]
    assert [item["worker_id"] for item in store.list_heartbeats(status="idle")] == [
        "cx-worker-001",
        "mo-worker-001",
    ]
    assert store.summary()["total"] == 2


def test_worker_heartbeat_store_rejects_invalid_filters() -> None:
    store = InMemoryWorkerHeartbeatStore()

    with pytest.raises(WorkerHeartbeatError) as service_error:
        store.list_heartbeats(service_id="unknown")
    assert service_error.value.error_code == "worker_heartbeat.service_invalid"

    with pytest.raises(WorkerHeartbeatError) as status_error:
        store.list_heartbeats(status="BROKEN")
    assert status_error.value.error_code == "worker_heartbeat.status_invalid"

    with pytest.raises(WorkerHeartbeatError) as worker_error:
        store.get_heartbeat("nex-cx", "")
    assert worker_error.value.error_code == "worker_heartbeat.field_invalid"


def test_sqlalchemy_worker_heartbeat_store_upserts_filters_and_summarizes() -> None:
    store = sqlite_worker_heartbeat_store()
    assert store.get_heartbeat("nex-cx", "missing") is None

    first = store.upsert_heartbeat(sample_heartbeat())
    first["metadata"]["queue"] = "mutated"
    store.upsert_heartbeat(
        sample_heartbeat(
            service_id="nex-mo",
            worker_id="mo-worker-001",
            worker_type="mo.embedding.worker",
            status=IDLE,
            active_job_id=None,
        )
    )
    updated = store.upsert_heartbeat(
        sample_heartbeat(
            status=ERROR,
            active_job_id=None,
            last_seen_at="2026-08-05T00:00:45Z",
            metadata={"queue": "cx.document_processing", "failure": "provider_timeout"},
        )
    )

    assert updated["status"] == ERROR
    assert store.get_heartbeat("nex-cx", "cx-worker-001")["metadata"] == {
        "failure": "provider_timeout",
        "queue": "cx.document_processing",
    }
    assert [item["worker_id"] for item in store.list_heartbeats(worker_type="mo.embedding.worker")] == [
        "mo-worker-001"
    ]
    assert [item["worker_id"] for item in store.list_heartbeats(service_id="nex-cx", status=ERROR)] == [
        "cx-worker-001"
    ]
    assert store.summary()["statuses"][ERROR] == 1


def test_sqlalchemy_worker_heartbeat_store_reports_unavailable_store() -> None:
    store = SqlAlchemyWorkerHeartbeatStore(
        build_session_factory(build_engine("sqlite+pysqlite:///:memory:"))
    )

    with pytest.raises(WorkerHeartbeatError) as get_error:
        store.get_heartbeat("nex-cx", "cx-worker-001")
    assert get_error.value.error_code == "worker_heartbeat.store_unavailable"
    assert get_error.value.status_code == 503

    with pytest.raises(WorkerHeartbeatError) as upsert_error:
        store.upsert_heartbeat(sample_heartbeat())
    assert upsert_error.value.error_code == "worker_heartbeat.store_unavailable"

    with pytest.raises(WorkerHeartbeatError) as list_error:
        store.list_heartbeats()
    assert list_error.value.error_code == "worker_heartbeat.store_unavailable"


def test_worker_heartbeat_sqlalchemy_helpers_cover_backend_edges() -> None:
    postgres_engine = build_engine("postgresql://user:secret@localhost/nex_cx_dev")
    postgres_session = build_session_factory(postgres_engine)()
    try:
        assert runtime_worker_heartbeats._metadata_sql_expression(postgres_session) == (
            "CAST(:metadata AS JSONB)"
        )
    finally:
        postgres_session.close()

    assert runtime_worker_heartbeats._json_loads(None, default={"fallback": "yes"}) == {
        "fallback": "yes"
    }
    assert runtime_worker_heartbeats._json_loads({"already": "dict"}, default={}) == {
        "already": "dict"
    }
    assert runtime_worker_heartbeats._json_loads(b'{"from":"bytes"}', default={}) == {
        "from": "bytes"
    }
    assert runtime_worker_heartbeats._json_loads(123, default={"fallback": "yes"}) == {
        "fallback": "yes"
    }
    assert runtime_worker_heartbeats._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0)) == (
        "2026-08-05T00:00:00Z"
    )
