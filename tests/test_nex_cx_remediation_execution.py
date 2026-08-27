from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text

from nex_cx.generation import GenerationExecutionStore
from nex_cx.remediation_execution import (
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_JOB_TYPE,
    CX_REMEDIATION_EXECUTION_LIST_SCHEMA_VERSION,
    CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
    RemediationExecutionError,
    RemediationExecutionStore,
    SqlAlchemyRemediationExecutionStore,
    _json_loads,
    _json_sql_expression,
    _timestamp_to_wire,
    build_cx_remediation_execution_result,
    build_cx_remediation_execution_detail_response,
    build_cx_remediation_execution_list_response,
    build_cx_repaired_generation_lineage,
    build_remediation_execution_job,
    enqueue_remediation_execution_job,
    register_remediation_execution_routes,
    remediation_execution_job_id,
    validate_cx_remediation_execution_request,
)
from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
)


ROOT = Path(__file__).parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_route_client() -> tuple[
    TestClient,
    GenerationExecutionStore,
    RemediationExecutionStore,
]:
    client, generation_store, execution_store, _ = build_route_client_with_queue()
    return client, generation_store, execution_store


def build_route_client_with_queue(
    job_queue: object | None = None,
) -> tuple[
    TestClient,
    GenerationExecutionStore,
    RemediationExecutionStore,
    object | None,
]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    register_remediation_execution_routes(
        app,
        generation_store=generation_store,
        execution_store=execution_store,
        job_queue=job_queue,
    )
    return TestClient(app), generation_store, execution_store, job_queue


def result_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "generation"
            / "cx_remediation_execution_result.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def remediation_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_schema_version": "cx_remediation_execution_request.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "reason_codes": [
            "negative_user_feedback",
            "citation_quality",
        ],
        "source_refs": [
            {
                "source_service": "nex-ae-api",
                "ref_type": "feedback",
                "ref_id": "ae-feedback-001",
                "relation": "caused_by",
            },
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": "ag-gq-disposition-001",
                "relation": "recommended_by",
            },
        ],
        "evidence": {
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "evidence_previews": [
                "Citation [2] did not support the generated answer.",
            ],
            "raw_evidence_stored": False,
        },
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": "reuse_or_expand_cited_evidence",
            "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
            "provider_boundary": "cx_to_mo_service_api_only",
        },
        "idempotency_key": "cx-remediation-execution-001",
        "requested_by": {
            "source_service": "nex-ag",
            "owner_ref": {
                "owner_type": "service",
                "owner_id": "nex-ag",
                "tenant_id": "local-tenant",
            },
        },
        "metadata": {
            "handoff_source": "ag_remediation_action",
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "raw_feedback_comment_stored": False,
            "raw_operator_note_stored": False,
            "free_text_storage": "hash_and_short_preview_only",
        },
        "requested_at": "2026-08-26T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def parent_generation_record() -> dict[str, Any]:
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-gen-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "status": "COMPLETED",
    }


def test_cx_remediation_execution_route_accepts_and_stores_result() -> None:
    client, generation_store, execution_store = build_route_client()
    generation_store.save(parent_generation_record())

    response = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(),
    )

    assert response.status_code == 202
    body = response.json()
    Draft202012Validator(result_schema()).validate(body)
    assert body["result_schema_version"] == "cx_remediation_execution_result.v1"
    assert body["execution_status"] == "ACCEPTED"
    assert body["repair_cx_generation_id"] is None
    assert body["result_ref"] is None
    assert body["redaction_summary"]["provider_detail_included"] is False
    assert execution_store.get("ag-remediation-action-001") == body
    assert execution_store.list_for_parent("cx-gen-001") == [body]


def test_cx_remediation_execution_read_model_lists_and_gets_persisted_rows() -> None:
    client, generation_store, execution_store = build_route_client()
    accepted = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )
    failed = {
        **build_cx_remediation_execution_result(
            remediation_request(remediation_action_id="ag-remediation-action-002"),
            created_at="2026-08-26T00:00:01Z",
        ),
        "execution_status": "FAILED",
        "failure": {
            "failure_class": "policy_rejected",
            "retryable": False,
            "detail_hash": "b" * 64,
        },
        "updated_at": "2026-08-26T00:00:02Z",
    }
    execution_store.save(accepted)
    execution_store.save(failed)

    listed = client.get(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
    )
    detail = client.get(
        (
            "/api/v1/generations/cx-gen-001/remediation-executions/"
            "ag-remediation-action-002"
        ),
        headers=auth_headers(),
    )

    assert generation_store.get("cx-gen-001") is None
    assert listed.status_code == 200
    assert listed.json()["list_schema_version"] == (
        CX_REMEDIATION_EXECUTION_LIST_SCHEMA_VERSION
    )
    assert listed.json()["summary"] == {
        "count": 2,
        "by_execution_status": {"FAILED": 1, "ACCEPTED": 1},
        "by_action_type": {"citation_repair": 2},
        "latest_updated_at": "2026-08-26T00:00:02Z",
    }
    assert [item["remediation_action_id"] for item in listed.json()["items"]] == [
        "ag-remediation-action-002",
        "ag-remediation-action-001",
    ]
    assert listed.json()["redaction_summary"]["prompt_text_included"] is False

    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["detail_schema_version"] == (
        CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
    )
    assert detail_body["projection_status"] == "READY"
    assert detail_body["execution_status"] == "FAILED"
    assert detail_body["attention_required"] is True
    assert detail_body["execution"]["failure"]["detail_hash"] == "b" * 64
    assert detail_body["repaired_generation_lineage"]["lineage_status"] == (
        "TERMINAL_WITHOUT_REPAIR"
    )
    assert detail_body["repaired_generation_lineage"]["diagnostics"] == {
        "lineage_consistent": True,
        "repair_generation_linked": False,
        "result_ref_present": False,
        "result_ref_matches_remediation_action": False,
        "parent_generation_mutated": False,
    }
    assert detail_body["debug_paths"]["cx_remediation_execution_path"].endswith(
        "/ag-remediation-action-002"
    )


def test_cx_repaired_generation_lineage_read_model_covers_runtime_edges() -> None:
    accepted = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )
    pending = build_cx_repaired_generation_lineage(accepted)

    assert pending["lineage_schema_version"] == (
        CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION
    )
    assert pending["lineage_status"] == "PENDING_REPAIR_GENERATION"
    assert pending["root_cx_generation_id"] == "cx-gen-001"
    assert pending["repair_cx_generation_id"] is None
    assert pending["debug_paths"]["repair_generation_path"] is None
    assert pending["diagnostics"]["lineage_consistent"] is True

    succeeded = {
        **accepted,
        "execution_status": "SUCCEEDED",
        "root_cx_generation_id": "cx-gen-root-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "attempt_no": 2,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "ag-remediation-action-001",
            "relation": "result_of",
            "api_key": "do-not-leak",
        },
    }
    linked = build_cx_repaired_generation_lineage(succeeded)

    assert linked["lineage_status"] == "LINKED"
    assert linked["attempt_no"] == 2
    assert linked["root_cx_generation_id"] == "cx-gen-root-001"
    assert linked["debug_paths"]["repair_generation_path"] == (
        "/api/v1/generations/cx-gen-repair-001"
    )
    assert linked["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    assert linked["diagnostics"]["repair_generation_linked"] is True
    assert linked["diagnostics"]["result_ref_matches_remediation_action"] is True
    assert "do-not-leak" not in json.dumps(linked, sort_keys=True)

    missing_child = {**succeeded, "repair_cx_generation_id": None}
    inconsistent_detail = build_cx_remediation_execution_detail_response(
        missing_child,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        checked_at="2026-08-26T00:00:03Z",
    )
    assert inconsistent_detail["repaired_generation_lineage"]["lineage_status"] == (
        "INCONSISTENT"
    )
    assert inconsistent_detail["attention_required"] is True

    self_link = {**succeeded, "repair_cx_generation_id": "cx-gen-001"}
    assert build_cx_repaired_generation_lineage(self_link)["lineage_status"] == (
        "INCONSISTENT"
    )
    bad_result_ref = {
        **succeeded,
        "result_ref": {"source_service": "nex-cx", "ref_type": "repair_execution"},
    }
    without_safe_ref = build_cx_repaired_generation_lineage(bad_result_ref)
    assert without_safe_ref["lineage_status"] == "LINKED"
    assert without_safe_ref["result_ref"] is None
    assert without_safe_ref["diagnostics"]["result_ref_present"] is False

    non_canonical_ref = {
        **succeeded,
        "result_ref": {
            "source_service": "nex-ag",
            "ref_type": "repair_execution",
            "ref_id": "ag-remediation-action-001",
            "relation": "result_of",
        },
    }
    assert (
        build_cx_repaired_generation_lineage(non_canonical_ref)["result_ref"] is None
    )


def test_cx_remediation_execution_read_model_handles_auth_and_not_found_edges() -> None:
    client, _, execution_store = build_route_client()
    execution_store.save(
        build_cx_remediation_execution_result(
            remediation_request(),
            created_at="2026-08-26T00:00:00Z",
        )
    )

    unauthorized_list = client.get(
        "/api/v1/generations/cx-gen-001/remediation-executions"
    )
    unauthorized_detail = client.get(
        (
            "/api/v1/generations/cx-gen-001/remediation-executions/"
            "ag-remediation-action-001"
        )
    )
    missing_detail = client.get(
        "/api/v1/generations/cx-gen-001/remediation-executions/missing",
        headers=auth_headers(),
    )
    wrong_parent = client.get(
        (
            "/api/v1/generations/cx-gen-other/remediation-executions/"
            "ag-remediation-action-001"
        ),
        headers=auth_headers(),
    )

    assert unauthorized_list.status_code == 401
    assert unauthorized_detail.status_code == 401
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error_code"] == "cx.remediation_execution_not_found"
    assert wrong_parent.status_code == 404
    assert wrong_parent.json()["error_code"] == "cx.remediation_execution_not_found"


def test_cx_remediation_execution_read_model_reports_store_errors() -> None:
    class FailingExecutionStore:
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            return record

        def get(self, remediation_action_id: str) -> dict[str, Any] | None:
            raise RemediationExecutionError(
                status_code=503,
                error_code="cx.remediation_execution_store_unavailable",
                detail="store unavailable",
                retryable=True,
            )

        def list_for_parent(self, parent_cx_generation_id: str) -> list[dict[str, Any]]:
            raise RemediationExecutionError(
                status_code=503,
                error_code="cx.remediation_execution_store_unavailable",
                detail="store unavailable",
                retryable=True,
            )

    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_remediation_execution_routes(
        app,
        generation_store=GenerationExecutionStore(),
        execution_store=FailingExecutionStore(),
    )
    client = TestClient(app)

    listed = client.get(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
    )
    detail = client.get(
        (
            "/api/v1/generations/cx-gen-001/remediation-executions/"
            "ag-remediation-action-001"
        ),
        headers=auth_headers(),
    )

    assert listed.status_code == 503
    assert listed.json()["retryable"] is True
    assert detail.status_code == 503
    assert detail.json()["error_code"] == "cx.remediation_execution_store_unavailable"


def test_cx_remediation_execution_read_model_builders_cover_empty_and_unknown_edges() -> None:
    listed = build_cx_remediation_execution_list_response(
        [{"remediation_action_id": "a", "updated_at": "2026-08-26T00:00:00Z"}],
        parent_cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    empty = build_cx_remediation_execution_list_response(
        [],
        parent_cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert listed["summary"]["by_execution_status"] == {"UNKNOWN": 1}
    assert empty["summary"]["latest_updated_at"] is None

    with pytest.raises(RemediationExecutionError) as detail_error:
        build_cx_remediation_execution_detail_response(
            {"parent_cx_generation_id": "cx-gen-001"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert detail_error.value.error_code == (
        "cx.remediation_execution_remediation_action_id_required"
    )


def test_cx_remediation_execution_route_enqueues_job_when_queue_is_configured() -> None:
    job_queue = InMemoryJobQueue()
    client, generation_store, execution_store, _ = build_route_client_with_queue(
        job_queue=job_queue,
    )
    generation_store.save(parent_generation_record())

    response = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(),
    )
    repeated = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(),
    )

    assert response.status_code == 202
    assert repeated.status_code == 202
    body = response.json()
    repeated_body = repeated.json()
    job_id = remediation_execution_job_id("ag-remediation-action-001")
    job = job_queue.get_job(job_id)
    assert job is not None
    assert len(job_queue.list_jobs(job_type=CX_REMEDIATION_EXECUTION_JOB_TYPE)) == 1
    assert job["job_type"] == CX_REMEDIATION_EXECUTION_JOB_TYPE
    assert job["subject_ref"] == {
        "type": "cx.remediation_execution",
        "id": "ag-remediation-action-001",
    }
    assert job["idempotency_key"] == "cx-remediation-execution-001"
    assert job["links"] == {
        "parent_generation": "/api/v1/generations/cx-gen-001",
        "remediation_execution": (
            "/api/v1/generations/cx-gen-001/remediation-executions"
        ),
    }
    assert job["payload"]["payload_schema_version"] == (
        "cx_remediation_execution_job_payload.v1"
    )
    assert job["payload"]["worker_plan"]["action_type"] == "citation_repair"
    assert job["payload"]["worker_plan"]["provider_boundary"] == (
        "cx_to_mo_service_api_only"
    )
    assert job["payload"]["execution_policy"]["parent_generation_mutation_allowed"] is False
    job_dump = json.dumps(job, sort_keys=True)
    assert "hidden prompt" not in job_dump
    assert "ed6@c496em" not in job_dump
    assert body["remediation_action_id"] == repeated_body["remediation_action_id"]
    assert execution_store.get("ag-remediation-action-001") == repeated_body


def test_build_remediation_execution_job_is_deterministic_and_raw_safe() -> None:
    result = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )

    job = build_remediation_execution_job(
        execution_record=result,
        request_payload=remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )

    assert job["job_id"] == remediation_execution_job_id("ag-remediation-action-001")
    assert job["created_at"] == "2026-08-26T00:00:00Z"
    assert job["payload"]["root_cx_generation_id"] == "cx-gen-001"
    assert job["payload"]["attempt_no"] == 1
    assert job["payload"]["reason_codes"] == [
        "negative_user_feedback",
        "citation_quality",
    ]
    assert job["payload"]["source_refs"][0]["ref_id"] == "ae-feedback-001"
    assert job["payload"]["evidence_hashes"] == [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ]
    assert job["payload"]["worker_plan"]["worker_stages"][-1]["stage_id"] == (
        "notify_ag_result_available"
    )


def test_build_remediation_execution_job_handles_optional_ref_shape_edges() -> None:
    result = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )
    payload = remediation_request(
        source_refs="not-a-list",
        evidence={"evidence_hashes": "not-a-list"},
    )

    job = build_remediation_execution_job(
        execution_record=result,
        request_payload=payload,
        created_at="2026-08-26T00:00:00Z",
    )

    assert job["payload"]["source_refs"] == []
    assert job["payload"]["evidence_hashes"] == []

    with pytest.raises(RemediationExecutionError) as blank_action:
        remediation_execution_job_id(" ")

    assert blank_action.value.error_code == (
        "cx.remediation_execution_remediation_action_id_required"
    )


def test_enqueue_remediation_execution_job_wraps_queue_errors() -> None:
    class FailingQueue:
        def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    result = build_cx_remediation_execution_result(remediation_request())

    with pytest.raises(RemediationExecutionError) as exc_info:
        enqueue_remediation_execution_job(
            FailingQueue(),
            execution_record=result,
            request_payload=remediation_request(),
        )

    assert exc_info.value.error_code == "cx.remediation_execution_job_admission_failed"
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True


def test_cx_remediation_execution_route_reports_job_admission_failures() -> None:
    class FailingQueue:
        def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    client, generation_store, execution_store, _ = build_route_client_with_queue(
        job_queue=FailingQueue(),
    )
    generation_store.save(parent_generation_record())

    response = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "cx.remediation_execution_job_admission_failed"
    )
    assert execution_store.get("ag-remediation-action-001") is not None


def test_cx_remediation_execution_store_reindexes_existing_action() -> None:
    store = RemediationExecutionStore()
    first = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )
    second_payload = remediation_request(parent_cx_generation_id="cx-gen-002")
    second = build_cx_remediation_execution_result(
        second_payload,
        created_at="2026-08-26T00:00:01Z",
    )

    store.action_ids_by_parent["cx-gen-001"] = ["ag-remediation-action-001"]
    store.save(first)
    store.save(first)
    store.save(second)

    assert store.get("ag-remediation-action-001") == second
    assert store.list_for_parent("cx-gen-001") == []
    assert store.list_for_parent("cx-gen-002") == [second]

    null_tenant = build_cx_remediation_execution_result(
        remediation_request(
            remediation_action_id="ag-remediation-action-null-tenant",
            tenant_id=None,
        ),
        created_at="2026-08-26T00:00:02Z",
    )

    assert null_tenant["tenant_id"] is None


def test_sqlalchemy_remediation_execution_store_persists_lineage_without_raw_data() -> None:
    store, engine = sqlite_remediation_execution_store()
    result = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )

    saved = store.save(result)
    loaded = store.get("ag-remediation-action-001")
    listed = store.list_for_parent("cx-gen-001")

    assert saved == result
    assert loaded is not None
    assert loaded["result_schema_version"] == "cx_remediation_execution_result.v1"
    assert loaded["parent_cx_generation_id"] == "cx-gen-001"
    assert loaded["root_cx_generation_id"] == "cx-gen-001"
    assert loaded["action_type"] == "citation_repair"
    assert loaded["lineage_type"] == "repair"
    assert loaded["attempt_no"] == 1
    assert loaded["result_ref"] is None
    assert loaded["failure"] is None
    assert loaded["metadata"] == {}
    assert listed == [loaded]

    dump = sqlite_table_dump(engine, "cx_remediation_execution_attempts")
    assert "hidden prompt" not in dump
    assert "provider_endpoint" in dump
    assert "ed6@c496em" not in dump


def test_sqlalchemy_remediation_execution_store_reindexes_and_reads_json_payloads() -> None:
    store, _ = sqlite_remediation_execution_store()
    accepted = build_cx_remediation_execution_result(
        remediation_request(),
        created_at="2026-08-26T00:00:00Z",
    )
    succeeded = {
        **accepted,
        "parent_cx_generation_id": "cx-gen-002",
        "root_cx_generation_id": "cx-gen-root",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "execution_status": "SUCCEEDED",
        "attempt_no": 2,
        "result_ref": {
            "ref_type": "cx_generation",
            "ref_id": "cx-gen-repair-001",
        },
        "metadata": {"repair_source": "slice_0355"},
        "updated_at": "2026-08-26T00:00:01Z",
    }

    store.save(accepted)
    store.save(succeeded)

    assert store.list_for_parent("cx-gen-001") == []
    loaded = store.get("ag-remediation-action-001")
    assert loaded is not None
    assert loaded["parent_cx_generation_id"] == "cx-gen-002"
    assert loaded["root_cx_generation_id"] == "cx-gen-root"
    assert loaded["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert loaded["attempt_no"] == 2
    assert loaded["result_ref"]["ref_id"] == "cx-gen-repair-001"
    assert loaded["metadata"] == {"repair_source": "slice_0355"}
    assert store.list_for_parent("cx-gen-002") == [loaded]


def test_sqlalchemy_remediation_execution_store_reports_database_errors() -> None:
    store, _ = sqlite_remediation_execution_store(create_schema=False)

    with pytest.raises(RemediationExecutionError) as save_error:
        store.save(build_cx_remediation_execution_result(remediation_request()))
    with pytest.raises(RemediationExecutionError) as get_error:
        store.get("ag-remediation-action-001")
    with pytest.raises(RemediationExecutionError) as list_error:
        store.list_for_parent("cx-gen-001")

    assert save_error.value.error_code == "cx.remediation_execution_store_unavailable"
    assert save_error.value.status_code == 503
    assert save_error.value.retryable is True
    assert get_error.value.error_code == "cx.remediation_execution_store_unavailable"
    assert list_error.value.error_code == "cx.remediation_execution_store_unavailable"


def test_remediation_execution_sqlalchemy_helpers_cover_dialect_and_wire_edges() -> None:
    store, _ = sqlite_remediation_execution_store()

    assert store.get("missing-action") is None
    assert _json_loads({"already": "decoded"}, default={}) == {"already": "decoded"}
    assert _json_loads(b'{"from":"bytes"}', default={}) == {"from": "bytes"}
    assert _json_loads(123, default={"fallback": True}) == {"fallback": True}
    assert _timestamp_to_wire(datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)) == (
        "2026-08-26T01:02:03Z"
    )
    assert _timestamp_to_wire(datetime(2026, 8, 26, 1, 2, 3)) == (
        "2026-08-26T01:02:03Z"
    )

    class PostgresSession:
        def get_bind(self) -> Any:
            class Bind:
                class dialect:
                    name = "postgresql"

            return Bind()

    assert _json_sql_expression(PostgresSession(), "payload") == "CAST(:payload AS JSONB)"


def test_validate_cx_remediation_execution_request_rejects_boundary_violations() -> None:
    with pytest.raises(RemediationExecutionError) as schema_error:
        validate_cx_remediation_execution_request(
            remediation_request(request_schema_version="old")
        )

    assert schema_error.value.error_code == (
        "cx.remediation_execution_request_schema_invalid"
    )

    with pytest.raises(RemediationExecutionError) as ag_only:
        validate_cx_remediation_execution_request(
            remediation_request(
                action_type="prompt_policy_review",
                lineage_type="repair",
            )
        )

    assert ag_only.value.error_code == "cx.remediation_execution_action_not_executable"

    with pytest.raises(RemediationExecutionError) as lineage_error:
        validate_cx_remediation_execution_request(
            remediation_request(
                action_type="retrieval_repair",
                lineage_type="repair",
            )
        )

    assert lineage_error.value.error_code == "cx.remediation_execution_lineage_invalid"

    bad_policy = deepcopy(remediation_request()["execution_policy"])
    bad_policy["parent_generation_mutation_allowed"] = True
    with pytest.raises(RemediationExecutionError) as mutation_error:
        validate_cx_remediation_execution_request(
            remediation_request(execution_policy=bad_policy)
        )

    assert mutation_error.value.error_code == (
        "cx.remediation_execution_parent_mutation_forbidden"
    )

    bad_boundary = deepcopy(remediation_request()["execution_policy"])
    bad_boundary["provider_boundary"] = "direct_provider"
    with pytest.raises(RemediationExecutionError) as boundary_error:
        validate_cx_remediation_execution_request(
            remediation_request(execution_policy=bad_boundary)
        )

    assert boundary_error.value.error_code == (
        "cx.remediation_execution_provider_boundary_invalid"
    )

    bad_evidence = deepcopy(remediation_request()["evidence"])
    bad_evidence.pop("raw_evidence_stored")
    with pytest.raises(RemediationExecutionError) as evidence_error:
        validate_cx_remediation_execution_request(
            remediation_request(evidence=bad_evidence)
        )

    assert evidence_error.value.error_code == "cx.remediation_execution_evidence_invalid"


def test_cx_remediation_execution_route_rejects_auth_path_and_parent_errors() -> None:
    client, generation_store, _ = build_route_client()
    generation_store.save(parent_generation_record())

    unauthorized = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        json=remediation_request(),
    )
    mismatch = client.post(
        "/api/v1/generations/cx-gen-other/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(),
    )
    missing_parent = client.post(
        "/api/v1/generations/missing/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(parent_cx_generation_id="missing"),
    )

    assert unauthorized.status_code == 401
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "cx.remediation_execution_parent_mismatch"
    assert missing_parent.status_code == 404
    assert missing_parent.json()["error_code"] == (
        "cx.remediation_execution_parent_not_found"
    )


def test_cx_remediation_execution_route_rejects_sensitive_payload() -> None:
    client, generation_store, _ = build_route_client()
    generation_store.save(parent_generation_record())

    response = client.post(
        "/api/v1/generations/cx-gen-001/remediation-executions",
        headers=auth_headers(),
        json=remediation_request(raw_prompt="hidden prompt"),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.remediation_execution_sensitive_payload"


def test_build_cx_remediation_execution_result_requires_core_fields() -> None:
    assert str(
        RemediationExecutionError(
            status_code=422,
            error_code="example",
            detail="example detail",
        )
    ) == "example detail"

    payload = remediation_request()
    payload["remediation_action_id"] = " "

    with pytest.raises(RemediationExecutionError) as exc_info:
        build_cx_remediation_execution_result(payload)

    assert exc_info.value.error_code == (
        "cx.remediation_execution_remediation_action_id_required"
    )


def sqlite_remediation_execution_store(
    *,
    create_schema: bool = True,
) -> tuple[SqlAlchemyRemediationExecutionStore, object]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    if create_schema:
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
                        attempt_no INTEGER NOT NULL DEFAULT 1,
                        result_ref TEXT,
                        failure TEXT,
                        redaction_summary TEXT NOT NULL,
                        metadata TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
    return (
        SqlAlchemyRemediationExecutionStore(
            build_session_factory(engine),
            source_kind="sqlite-regression",
            database_env="test",
            redacted_database_url="sqlite:///***",
        ),
        engine,
    )


def sqlite_table_dump(engine: object, table_name: str) -> str:
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT * FROM {table_name}")).mappings().all()
    return json.dumps(
        [dict(row) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
