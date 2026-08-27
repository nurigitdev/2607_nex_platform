from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from nex_ag.generation_remediation import GenerationRemediationTaskStore
from nex_ag.operations import build_operation_query_options
from nex_ag.remediation_execution_operations import (
    AG_REMEDIATION_EXECUTION_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
    AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
    InMemoryRemediationExecutionOperationsStore,
    RemediationExecutionOperationsError,
    SqlAlchemyRemediationExecutionOperationsStore,
    build_remediation_execution_operations_projection,
)
import nex_ag.remediation_execution_operations as remediation_ops
from nex_runtime import build_engine, build_session_factory


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CX_GENERATION_ID = "11111111-1111-4111-8111-111111111111"
REPAIR_GENERATION_ID = "22222222-2222-4222-8222-222222222222"
REMEDIATION_ACTION_ID = "33333333-3333-4333-8333-333333333333"


def task_record(
    *,
    remediation_action_id: str = REMEDIATION_ACTION_ID,
    cx_generation_id: str = CX_GENERATION_ID,
    action_status: str = "WAITING_ON_CX",
    action_type: str = "citation_repair",
    updated_at: str = "2026-08-20T00:05:00Z",
    trace_id: str = TRACE_ID,
    request_id: str = REQUEST_ID,
) -> dict[str, Any]:
    return {
        "action_schema_version": "ag_generation_remediation_action.v1",
        "remediation_action_id": remediation_action_id,
        "cx_generation_id": cx_generation_id,
        "tenant_id": "local-tenant",
        "trace_id": trace_id,
        "request_id": request_id,
        "action_type": action_type,
        "action_status": action_status,
        "priority": "HIGH",
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-cx",
            "tenant_id": "local-tenant",
        },
        "reason_codes": ["citation_quality"],
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": cx_generation_id,
                "relation": "caused_by",
            }
        ],
        "evidence": {
            "evidence_hashes": ["a" * 64],
            "evidence_previews": ["raw-ish operator preview must not be projected"],
        },
        "result_ref": None,
        "metadata": {
            "action_source": "unit_test",
            "raw_prompt": "must not leak",
            "raw_generation_output": "must not leak",
        },
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": updated_at,
    }


def execution_record(
    *,
    remediation_action_id: str = REMEDIATION_ACTION_ID,
    parent_cx_generation_id: str = CX_GENERATION_ID,
    execution_status: str = "SUCCEEDED",
    action_type: str = "citation_repair",
    updated_at: str = "2026-08-20T00:06:00Z",
    trace_id: str = TRACE_ID,
    request_id: str = REQUEST_ID,
) -> dict[str, Any]:
    return {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": remediation_action_id,
        "parent_cx_generation_id": parent_cx_generation_id,
        "root_cx_generation_id": parent_cx_generation_id,
        "repair_cx_generation_id": REPAIR_GENERATION_ID,
        "tenant_id": "local-tenant",
        "trace_id": trace_id,
        "request_id": request_id,
        "action_type": action_type,
        "lineage_type": "repair_attempt",
        "execution_status": execution_status,
        "attempt_no": 1,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": remediation_action_id,
            "relation": "result_of",
            "raw_output": "must not leak",
        },
        "failure": {
            "error_code": "cx.remediation.failed",
            "error_detail_sha256": "b" * 64,
            "error_detail": "must not leak",
            "retryable": True,
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "metadata": {"worker": "mock"},
        "created_at": "2026-08-20T00:01:00Z",
        "updated_at": updated_at,
    }


def test_remediation_execution_operations_projection_merges_and_summarizes() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(task_record())
    execution_store = InMemoryRemediationExecutionOperationsStore(
        records=[execution_record()]
    )

    projection = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store},
        execution_stores={CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: execution_store},
        cx_generation_id=CX_GENERATION_ID,
        request_trace_id=TRACE_ID,
    )

    operation = projection["operations"][0]
    serialized = str(projection)
    assert projection["projection_schema_version"] == (
        AG_REMEDIATION_EXECUTION_OPERATIONS_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["summary"] == {
        "total": 1,
        "by_task_status": {"WAITING_ON_CX": 1},
        "by_execution_status": {"SUCCEEDED": 1},
        "sync_required_count": 1,
        "missing_execution_count": 0,
        "orphan_execution_count": 0,
        "failed_execution_count": 0,
        "attention_required_count": 1,
    }
    assert operation["target_task_status"] == "COMPLETED"
    assert operation["status_sync_state"] == "SYNC_REQUIRED"
    assert operation["evidence_hash_count"] == 1
    assert operation["source_ref_count"] == 1
    assert operation["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": REMEDIATION_ACTION_ID,
        "relation": "result_of",
    }
    assert operation["failure"] == {
        "error_code": "cx.remediation.failed",
        "error_detail_sha256": "b" * 64,
        "retryable": True,
    }
    assert "must not leak" not in serialized
    assert "'raw_prompt':" not in serialized
    assert projection["request_trace_id"] == TRACE_ID


def test_in_memory_remediation_execution_store_filters_and_deep_copies() -> None:
    store = InMemoryRemediationExecutionOperationsStore(
        records=[
            execution_record(),
            execution_record(
                remediation_action_id="44444444-4444-4444-8444-444444444444",
                parent_cx_generation_id="55555555-5555-4555-8555-555555555555",
                execution_status="FAILED",
                trace_id="0" * 32,
                request_id="different",
            ),
        ]
    )

    assert store.list_remediation_executions(parent_cx_generation_id="missing") == []
    assert store.list_remediation_executions(execution_status="FAILED")[0][
        "execution_status"
    ] == "FAILED"
    assert store.list_remediation_executions(trace_id="missing") == []
    assert store.list_remediation_executions(request_id="missing") == []
    assert store.list_remediation_executions(remediation_action_id="missing") == []
    matched = store.list_remediation_executions(
        parent_cx_generation_id=CX_GENERATION_ID,
        execution_status="SUCCEEDED",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        remediation_action_id=REMEDIATION_ACTION_ID,
        limit=1,
    )
    matched[0]["execution_status"] = "MUTATED"

    assert len(matched) == 1
    assert store.records[0]["execution_status"] == "SUCCEEDED"


def test_remediation_execution_operations_projection_handles_missing_and_orphan_records() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        task_record(
            remediation_action_id="66666666-6666-4666-8666-666666666666",
            action_status="PROPOSED",
            updated_at="2026-08-20T00:02:00Z",
        )
    )
    execution_store = InMemoryRemediationExecutionOperationsStore(
        records=[
            execution_record(
                remediation_action_id="77777777-7777-4777-8777-777777777777",
                execution_status="RUNNING",
                updated_at="2026-08-20T00:03:00Z",
            )
        ]
    )

    projection = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store},
        execution_stores={CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: execution_store},
        query_options=build_operation_query_options(sort="asc", limit=10),
    )

    states = {
        item["remediation_action_id"]: item["status_sync_state"]
        for item in projection["operations"]
    }
    assert states == {
        "66666666-6666-4666-8666-666666666666": "NO_EXECUTION",
        "77777777-7777-4777-8777-777777777777": "ORPHAN_EXECUTION",
    }
    assert projection["summary"]["missing_execution_count"] == 1
    assert projection["summary"]["orphan_execution_count"] == 1
    assert projection["summary"]["by_task_status"] == {"PROPOSED": 1, "NONE": 1}


@pytest.mark.parametrize(
    ("task_status", "execution_status", "expected_state", "attention_required"),
    [
        ("COMPLETED", "SUCCEEDED", "IN_SYNC", False),
        ("COMPLETED", "FAILED", "TERMINAL_TASK_DIVERGED", True),
        ("WAITING_ON_CX", "STRANGE", "UNKNOWN_EXECUTION_STATUS", True),
        ("FAILED", None, "NO_EXECUTION", True),
    ],
)
def test_remediation_execution_operations_projection_status_sync_matrix(
    task_status: str,
    execution_status: str | None,
    expected_state: str,
    attention_required: bool,
) -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(task_record(action_status=task_status))
    execution_records = []
    if execution_status is not None:
        execution_records.append(execution_record(execution_status=execution_status))

    projection = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store},
        execution_stores={
            CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: (
                InMemoryRemediationExecutionOperationsStore(records=execution_records)
            )
        },
    )

    operation = projection["operations"][0]
    assert operation["status_sync_state"] == expected_state
    assert operation["attention_required"] is attention_required


def test_remediation_execution_operations_projection_filters_and_paginates() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        task_record(
            remediation_action_id="88888888-8888-4888-8888-888888888888",
            action_status="COMPLETED",
            updated_at="2026-08-20T00:08:00Z",
        )
    )
    task_store.save(
        task_record(
            remediation_action_id="99999999-9999-4999-8999-999999999999",
            trace_id="1" * 32,
            request_id="filtered-out",
            updated_at="2026-08-20T00:09:00Z",
        )
    )
    execution_store = InMemoryRemediationExecutionOperationsStore(
        records=[
            execution_record(
                remediation_action_id="88888888-8888-4888-8888-888888888888",
                execution_status="SUCCEEDED",
                updated_at="2026-08-20T00:10:00Z",
            ),
            execution_record(
                remediation_action_id="99999999-9999-4999-8999-999999999999",
                trace_id="1" * 32,
                request_id="filtered-out",
                updated_at="2026-08-20T00:11:00Z",
            ),
        ]
    )

    projection = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store},
        execution_stores={CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: execution_store},
        action_status="COMPLETED",
        execution_status="SUCCEEDED",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        remediation_action_id="88888888-8888-4888-8888-888888888888",
        query_options=build_operation_query_options(
            since="2026-08-20T00:09:00Z",
            until="2026-08-20T00:12:00Z",
            sort="desc",
            limit=1,
        ),
    )

    assert [item["remediation_action_id"] for item in projection["operations"]] == [
        "88888888-8888-4888-8888-888888888888"
    ]
    assert projection["pagination"]["returned"] == 1
    assert projection["filters"]["trace_id"] == TRACE_ID


def test_remediation_execution_operations_projection_covers_task_filter_misses() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        task_record(
            remediation_action_id="aaaaaaa1-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            cx_generation_id="aaaaaaa2-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        )
    )
    task_store.save(
        task_record(
            remediation_action_id="bbbbbbb1-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
            trace_id="2" * 32,
        )
    )
    task_store.save(
        task_record(
            remediation_action_id="ccccccc1-cccc-4ccc-8ccc-ccccccccccc1",
            request_id="wrong-request",
        )
    )
    task_store.save(
        task_record(remediation_action_id="ddddddd1-dddd-4ddd-8ddd-ddddddddddd1")
    )

    projection = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store},
        execution_stores={
            CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: (
                InMemoryRemediationExecutionOperationsStore()
            )
        },
        cx_generation_id=CX_GENERATION_ID,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        remediation_action_id=REMEDIATION_ACTION_ID,
    )

    assert projection["operations"] == []
    assert projection["source_statuses"]["nex-ag"]["record_count"] == 0


def test_remediation_execution_operations_projection_covers_time_range_exclusions() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        task_record(
            remediation_action_id="eeeeeee1-eeee-4eee-8eee-eeeeeeeeeee1",
            updated_at="2026-08-20T00:05:00Z",
        )
    )
    stores = {
        AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_store,
    }
    execution_stores = {
        CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: (
            InMemoryRemediationExecutionOperationsStore()
        )
    }

    after = build_remediation_execution_operations_projection(
        task_stores=stores,
        execution_stores=execution_stores,
        query_options=build_operation_query_options(
            since="2026-08-20T00:06:00Z",
            limit=10,
        ),
    )
    before = build_remediation_execution_operations_projection(
        task_stores=stores,
        execution_stores=execution_stores,
        query_options=build_operation_query_options(
            until="2026-08-20T00:04:00Z",
            limit=10,
        ),
    )

    assert after["operations"] == []
    assert before["operations"] == []


def test_remediation_execution_operations_projection_degrades_missing_and_unavailable_sources() -> None:
    class BrokenTaskStore:
        source_kind = "broken"
        database_env = "NEX_AG_TEST_DATABASE_URL"
        redacted_database_url = "postgresql://user:***@localhost/db"

        def list_recent(self, *, limit: int = 500) -> list[dict[str, Any]]:
            raise RuntimeError("database unavailable")

    class BrokenExecutionStore:
        source_kind = "broken"
        database_env = "NEX_CX_TEST_DATABASE_URL"
        redacted_database_url = "postgresql://user:***@localhost/db"

        def list_remediation_executions(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise RemediationExecutionOperationsError(
                error_code="ag.cx_remediation_execution_source_unavailable",
                detail="CX source unavailable.",
            )

    missing = build_remediation_execution_operations_projection(
        task_stores={},
        execution_stores={},
    )
    broken = build_remediation_execution_operations_projection(
        task_stores={AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: BrokenTaskStore()},
        execution_stores={
            CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: BrokenExecutionStore()
        },
    )

    assert missing["projection_status"] == "DEGRADED"
    assert missing["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"
    assert broken["projection_status"] == "DEGRADED"
    assert broken["source_statuses"]["nex-ag"]["error_code"] == (
        "ag.remediation_task_source_unavailable"
    )
    assert broken["source_statuses"]["nex-cx"]["error_code"] == (
        "ag.cx_remediation_execution_source_unavailable"
    )


def test_sqlalchemy_remediation_execution_operations_store_reads_sqlite_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'remediation-executions.sqlite'}"
    engine = build_engine(database_url)
    _create_sqlite_remediation_execution_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_remediation_execution_attempts (
                    remediation_action_id,
                    result_schema_version,
                    parent_cx_generation_id,
                    root_cx_generation_id,
                    repair_cx_generation_id,
                    tenant_id,
                    trace_id,
                    request_id,
                    action_type,
                    lineage_type,
                    execution_status,
                    attempt_no,
                    result_ref,
                    failure,
                    redaction_summary,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :remediation_action_id,
                    :result_schema_version,
                    :parent_cx_generation_id,
                    :root_cx_generation_id,
                    :repair_cx_generation_id,
                    :tenant_id,
                    :trace_id,
                    :request_id,
                    :action_type,
                    :lineage_type,
                    :execution_status,
                    :attempt_no,
                    :result_ref,
                    :failure,
                    :redaction_summary,
                    :metadata,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                **execution_record(),
                "result_ref": (
                    '{"source_service":"nex-cx","ref_type":"repair_execution",'
                    f'"ref_id":"{REMEDIATION_ACTION_ID}","relation":"result_of"}}'
                ),
                "failure": (
                    '{"error_code":"cx.remediation.failed",'
                    '"error_detail_sha256":"'
                    + ("b" * 64)
                    + '","retryable":true}'
                ),
                "redaction_summary": '{"raw_content_included":false}',
                "metadata": '{"worker":"sqlite-test"}',
            },
        )
    store = SqlAlchemyRemediationExecutionOperationsStore(
        build_session_factory(engine),
        database_env="NEX_CX_TEST_DATABASE_URL",
        redacted_database_url="sqlite:///***",
    )

    rows = store.list_remediation_executions(
        parent_cx_generation_id=CX_GENERATION_ID,
        execution_status="SUCCEEDED",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        remediation_action_id=REMEDIATION_ACTION_ID,
    )

    assert len(rows) == 1
    assert rows[0]["result_ref"]["source_service"] == "nex-cx"
    assert rows[0]["failure"]["error_detail_sha256"] == "b" * 64
    assert rows[0]["redaction_summary"] == {"raw_content_included": False}


def test_sqlalchemy_remediation_execution_operations_store_wraps_sql_errors(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'missing-table.sqlite'}"
    store = SqlAlchemyRemediationExecutionOperationsStore(
        build_session_factory(build_engine(database_url))
    )

    with pytest.raises(RemediationExecutionOperationsError) as exc_info:
        store.list_remediation_executions()

    assert exc_info.value.error_code == "ag.remediation_execution_source_unavailable"
    assert str(exc_info.value)


def test_remediation_execution_operations_helpers_cover_scalar_edges() -> None:
    naive = remediation_ops._timestamp_to_wire(
        remediation_ops.datetime(2026, 8, 20, 0, 0, 0)
    )
    aware = remediation_ops._timestamp_to_wire(
        remediation_ops.datetime(2026, 8, 20, 0, 0, 0, tzinfo=remediation_ops.UTC)
    )

    assert naive == "2026-08-20T00:00:00Z"
    assert aware == "2026-08-20T00:00:00Z"
    assert remediation_ops._max_timestamp(None, None).endswith("Z")
    assert remediation_ops._json_loads(None, default={"fallback": True}) == {
        "fallback": True
    }
    assert remediation_ops._json_loads({"already": "mapping"}, default={}) == {
        "already": "mapping"
    }
    assert remediation_ops._json_loads(b'{"from":"bytes"}', default={}) == {
        "from": "bytes"
    }
    assert remediation_ops._json_loads(123, default={"fallback": True}) == {
        "fallback": True
    }
    assert remediation_ops._optional_string(None) is None
    assert remediation_ops._int_value(True) == 0


def _create_sqlite_remediation_execution_table(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_remediation_execution_attempts (
                    remediation_action_id TEXT PRIMARY KEY,
                    result_schema_version TEXT NOT NULL,
                    parent_cx_generation_id TEXT NOT NULL,
                    root_cx_generation_id TEXT NOT NULL,
                    repair_cx_generation_id TEXT,
                    tenant_id TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    lineage_type TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    result_ref TEXT,
                    failure TEXT,
                    redaction_summary TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
