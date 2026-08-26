from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from nex_ag.generation_remediation import build_generation_remediation_action
from nex_ag.generation_remediation_execution import (
    AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION,
    GenerationRemediationExecutionError,
    _status_path,
    apply_generation_remediation_execution_handoff_plan,
    build_generation_remediation_execution_handoff_plan,
    build_generation_remediation_execution_result_ref,
    clone_plan,
    dispatch_generation_remediation_execution,
    register_generation_remediation_execution_routes,
    sync_generation_remediation_execution_status,
)
from nex_ag.generation_remediation_handoff import CxRemediationExecutionClientError
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-26T00:00:00Z"
ROOT = Path(__file__).parents[1]


def remediation_record(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "remediation_action_id": "ag-remediation-action-001",
        "tenant_id": "tenant-001",
        "action_type": "citation_repair",
        "action_status": "PROPOSED",
        "priority": "HIGH",
        "reason_codes": ["citation_quality"],
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-ag",
            "tenant_id": "tenant-001",
        },
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": "cx-gen-001",
                "relation": "caused_by",
            }
        ],
        "evidence_hashes": [
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ],
        "evidence_previews": ["citation quality failed"],
    }
    payload.update(overrides)
    return build_generation_remediation_action(
        payload,
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )


def cx_execution_result(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": None,
        "tenant_id": "tenant-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "ACCEPTED",
        "result_ref": None,
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return payload


def cx_execution_detail(**overrides: Any) -> dict[str, Any]:
    execution = overrides.pop("execution", None) or cx_execution_result(
        execution_status="SUCCEEDED",
        repair_cx_generation_id="cx-gen-repair-001",
        result_ref={
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "cx-repair-run-001",
            "relation": "result_of",
        },
    )
    payload: dict[str, Any] = {
        "detail_schema_version": "cx_remediation_execution_detail.v1",
        "projection_status": "READY",
        "parent_cx_generation_id": execution["parent_cx_generation_id"],
        "remediation_action_id": execution["remediation_action_id"],
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "execution_status": execution["execution_status"],
        "execution": execution,
        "attention_required": execution["execution_status"] in {"FAILED", "CANCELLED"},
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    payload.update(overrides)
    return payload


class FakeRemediationTaskStore:
    def __init__(self, record: dict[str, Any] | None) -> None:
        self.record = record
        self.saved: list[dict[str, Any]] = []

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        if self.record and self.record["remediation_action_id"] == remediation_action_id:
            return self.record
        return None

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.record = record
        self.saved.append(record)
        return record


class FakeCxExecutionClient:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or cx_execution_result()
        self.calls: list[dict[str, Any]] = []

    def submit_remediation_action(
        self,
        action: dict[str, Any],
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        requested_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "action": action,
                "request_id": request_id,
                "trace_id": trace_id,
                "requested_at": requested_at,
                "idempotency_key": idempotency_key,
            }
        )
        return self.response


class FakeCxExecutionStatusClient:
    def __init__(self, detail: dict[str, Any] | None = None) -> None:
        self.detail = detail or cx_execution_detail()
        self.calls: list[dict[str, Any]] = []

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "parent_cx_generation_id": parent_cx_generation_id,
                "remediation_action_id": remediation_action_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.detail


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_execution_route_client(
    *,
    store: FakeRemediationTaskStore | None = None,
    cx_client: FakeCxExecutionClient | None = None,
    cx_status_client: FakeCxExecutionStatusClient | None = None,
) -> tuple[
    TestClient,
    FakeRemediationTaskStore,
    FakeCxExecutionClient,
    FakeCxExecutionStatusClient,
]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_store = store or FakeRemediationTaskStore(remediation_record())
    selected_client = cx_client or FakeCxExecutionClient()
    selected_status_client = cx_status_client or FakeCxExecutionStatusClient()
    register_generation_remediation_execution_routes(
        app,
        store=selected_store,
        cx_client=selected_client,
        cx_status_client=selected_status_client,
    )
    return TestClient(app), selected_store, selected_client, selected_status_client


def test_handoff_plan_moves_proposed_task_through_in_progress_to_waiting_on_cx() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    assert plan["plan_schema_version"] == (
        AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
    )
    assert plan["current_action_status"] == "PROPOSED"
    assert plan["target_action_status"] == "WAITING_ON_CX"
    assert [update["action_status"] for update in plan["status_updates"]] == [
        "IN_PROGRESS",
        "WAITING_ON_CX",
    ]
    assert plan["status_updates"][-1]["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    assert plan["result_ref"]["result_ref_schema_version"] == (
        AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION
    )
    assert plan["redaction_summary"]["raw_generation_output_included"] is False
    assert "cx-gen-001/remediation-tasks/ag-remediation-action-001" in plan[
        "debug_paths"
    ]["ag_remediation_task_path"]


def test_dispatch_generation_remediation_execution_updates_store_sequentially() -> None:
    store = FakeRemediationTaskStore(remediation_record())
    client = FakeCxExecutionClient()

    dispatch = dispatch_generation_remediation_execution(
        store=store,
        cx_client=client,
        remediation_action_id="ag-remediation-action-001",
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at=NOW,
        idempotency_key="dispatch-idem-001",
        planned_at=NOW,
    )

    assert dispatch["dispatch_schema_version"] == (
        AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION
    )
    assert dispatch["dispatch_status"] == "DISPATCHED"
    assert dispatch["final_action_status"] == "WAITING_ON_CX"
    assert dispatch["status_update_count"] == 2
    assert [record["action_status"] for record in store.saved] == [
        "IN_PROGRESS",
        "WAITING_ON_CX",
    ]
    assert dispatch["task"] == store.saved[-1]
    assert dispatch["plan"]["status_updates"][-1]["result_ref"]["ref_id"] == (
        "ag-remediation-action-001"
    )
    assert dispatch["redaction_summary"]["provider_detail_included"] is False
    assert len(client.calls) == 1
    assert client.calls[0]["request_id"] == REQUEST_ID
    assert client.calls[0]["trace_id"] == TRACE_ID
    assert client.calls[0]["requested_at"] == NOW
    assert client.calls[0]["idempotency_key"] == "dispatch-idem-001"
    assert client.calls[0]["action"]["action_status"] == "PROPOSED"


def test_sync_generation_remediation_execution_status_completes_waiting_task() -> None:
    store = FakeRemediationTaskStore(remediation_record(action_status="WAITING_ON_CX"))
    cx_status_client = FakeCxExecutionStatusClient()

    sync = sync_generation_remediation_execution_status(
        store=store,
        cx_status_client=cx_status_client,
        remediation_action_id="ag-remediation-action-001",
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        observed_at=NOW,
    )

    assert sync["status_sync_schema_version"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION
    )
    assert sync["sync_status"] == "UPDATED"
    assert sync["previous_action_status"] == "WAITING_ON_CX"
    assert sync["final_action_status"] == "COMPLETED"
    assert sync["cx_execution_status"] == "SUCCEEDED"
    assert sync["status_update_count"] == 1
    assert sync["task"] == store.saved[-1]
    assert sync["result_ref"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert sync["plan"]["debug_paths"]["cx_remediation_execution_path"].endswith(
        "/remediation-executions"
    )
    assert cx_status_client.calls == [
        {
            "parent_cx_generation_id": "cx-gen-001",
            "remediation_action_id": "ag-remediation-action-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        }
    ]


def test_sync_generation_remediation_execution_status_is_idempotent_for_same_status() -> None:
    completed = remediation_record(action_status="COMPLETED")
    completed["result_ref"] = {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "cx-repair-run-001",
        "relation": "result_of",
    }
    store = FakeRemediationTaskStore(completed)
    cx_status_client = FakeCxExecutionStatusClient()

    sync = sync_generation_remediation_execution_status(
        store=store,
        cx_status_client=cx_status_client,
        remediation_action_id="ag-remediation-action-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        observed_at=NOW,
    )

    assert sync["sync_status"] == "UNCHANGED"
    assert sync["final_action_status"] == "COMPLETED"
    assert sync["status_update_count"] == 0
    assert sync["plan"]["status_updates"] == []
    assert sync["plan"]["debug_paths"]["cx_remediation_execution_path"].endswith(
        "/remediation-executions/ag-remediation-action-001"
    )
    assert store.saved == []


def test_generation_remediation_execution_route_dispatches_task() -> None:
    client, store, cx_client, _ = build_execution_route_client()

    response = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/execute"
        ),
        headers=auth_headers(),
        json={
            "requested_at": NOW,
            "planned_at": NOW,
            "idempotency_key": "route-idem-001",
        },
    )
    payload = response.json()

    assert response.status_code == 202
    assert payload["dispatch_schema_version"] == (
        AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION
    )
    assert payload["final_action_status"] == "WAITING_ON_CX"
    assert store.record["action_status"] == "WAITING_ON_CX"
    assert cx_client.calls[0]["idempotency_key"] == "route-idem-001"
    assert payload["task"]["result_ref"]["source_service"] == "nex-cx"


def test_generation_remediation_execution_route_syncs_task_status() -> None:
    client, store, _, cx_status_client = build_execution_route_client(
        store=FakeRemediationTaskStore(
            remediation_record(action_status="WAITING_ON_CX")
        )
    )

    response = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/sync-execution-status"
        ),
        headers=auth_headers(),
        json={"observed_at": NOW},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status_sync_schema_version"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION
    )
    assert payload["sync_status"] == "UPDATED"
    assert payload["final_action_status"] == "COMPLETED"
    assert store.record["action_status"] == "COMPLETED"
    assert cx_status_client.calls[0]["parent_cx_generation_id"] == "cx-gen-001"


def test_generation_remediation_execution_route_protects_auth_and_not_found() -> None:
    client, _, _, _ = build_execution_route_client(store=FakeRemediationTaskStore(None))

    unauthorized = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/execute"
        ),
        json={},
    )
    unauthorized_sync = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/sync-execution-status"
        ),
        json={},
    )
    missing = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/execute"
        ),
        headers=auth_headers(),
        json={},
    )

    assert unauthorized.status_code == 401
    assert unauthorized_sync.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.remediation_execution_task_not_found"


def test_generation_remediation_execution_route_maps_client_failure() -> None:
    class FailingCxClient(FakeCxExecutionClient):
        def submit_remediation_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="cx down",
                retryable=True,
            )

    client, store, _, _ = build_execution_route_client(cx_client=FailingCxClient())

    response = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/execute"
        ),
        headers=auth_headers(),
        json={},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "ag.cx_remediation_execution_unavailable"
    assert response.json()["retryable"] is True
    assert store.record["action_status"] == "PROPOSED"


def test_generation_remediation_execution_route_maps_sync_client_failure() -> None:
    class FailingStatusClient(FakeCxExecutionStatusClient):
        def get_remediation_execution_detail(
            self,
            *,
            parent_cx_generation_id: str,
            remediation_action_id: str,
            request_id: str | None = None,
            trace_id: str | None = None,
        ) -> dict[str, Any]:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="cx detail down",
                retryable=True,
            )

    client, store, _, _ = build_execution_route_client(
        store=FakeRemediationTaskStore(
            remediation_record(action_status="WAITING_ON_CX")
        ),
        cx_status_client=FailingStatusClient(),
    )

    response = client.post(
        (
            "/admin/v1/generation-audit/generations/cx-gen-001"
            "/remediation-tasks/ag-remediation-action-001/sync-execution-status"
        ),
        headers=auth_headers(),
        json={},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "ag.cx_remediation_execution_unavailable"
    assert store.record["action_status"] == "WAITING_ON_CX"


def test_generation_remediation_execution_static_openapi_contract() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts" / "openapi" / "nex-ag.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    execute_path = (
        "/admin/v1/generation-audit/generations/{cx_generation_id}"
        "/remediation-tasks/{remediation_action_id}/execute"
    )
    sync_path = (
        "/admin/v1/generation-audit/generations/{cx_generation_id}"
        "/remediation-tasks/{remediation_action_id}/sync-execution-status"
    )
    operation = spec["paths"][execute_path]["post"]
    sync_operation = spec["paths"][sync_path]["post"]

    assert operation["operationId"] == "executeAgGenerationRemediationTask"
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgGenerationRemediationExecutionDispatchRequest"
    }
    assert operation["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgGenerationRemediationExecutionDispatch"
    }
    assert spec["components"]["schemas"]["AgGenerationRemediationExecutionDispatch"][
        "properties"
    ]["dispatch_schema_version"]["const"] == (
        AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION
    )
    assert sync_operation["operationId"] == (
        "syncAgGenerationRemediationExecutionStatus"
    )
    assert sync_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": (
            "#/components/schemas/"
            "AgGenerationRemediationExecutionStatusSyncRequest"
        )
    }
    assert sync_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {
        "$ref": "#/components/schemas/AgGenerationRemediationExecutionStatusSync"
    }
    assert spec["components"]["schemas"][
        "AgGenerationRemediationExecutionStatusSync"
    ]["properties"]["status_sync_schema_version"]["const"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION
    )


def test_dispatch_generation_remediation_execution_can_complete_succeeded_result() -> None:
    store = FakeRemediationTaskStore(remediation_record(action_status="WAITING_ON_CX"))
    client = FakeCxExecutionClient(
        cx_execution_result(
            execution_status="SUCCEEDED",
            repair_cx_generation_id="cx-gen-repair-001",
            result_ref={
                "source_service": "nex-cx",
                "ref_type": "repair_execution",
                "ref_id": "cx-repair-run-001",
                "relation": "result_of",
            },
        )
    )

    dispatch = dispatch_generation_remediation_execution(
        store=store,
        cx_client=client,
        remediation_action_id="ag-remediation-action-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    assert dispatch["final_action_status"] == "COMPLETED"
    assert dispatch["status_update_count"] == 1
    assert dispatch["result_ref"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert store.saved[-1]["result_ref"]["ref_id"] == "cx-repair-run-001"


def test_apply_handoff_plan_returns_sequential_records() -> None:
    record = remediation_record()
    plan = build_generation_remediation_execution_handoff_plan(
        record,
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    applied = apply_generation_remediation_execution_handoff_plan(
        record,
        plan,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        updated_at=NOW,
    )

    assert [item["action_status"] for item in applied] == [
        "IN_PROGRESS",
        "WAITING_ON_CX",
    ]
    assert applied[-1]["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    assert applied[-1]["updated_at"] == NOW


@pytest.mark.parametrize(
    ("current_status", "cx_status", "expected_updates"),
    [
        ("ASSIGNED", "ACCEPTED", ["IN_PROGRESS", "WAITING_ON_CX"]),
        ("IN_PROGRESS", "RUNNING", ["WAITING_ON_CX"]),
        ("WAITING_ON_CX", "RUNNING", ["WAITING_ON_CX"]),
        ("IN_PROGRESS", "SUCCEEDED", ["COMPLETED"]),
        ("WAITING_ON_CX", "FAILED", ["FAILED"]),
        ("PROPOSED", "CANCELLED", ["CANCELLED"]),
    ],
)
def test_handoff_plan_status_paths(
    current_status: str,
    cx_status: str,
    expected_updates: list[str],
) -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(action_status=current_status),
        cx_execution_result(execution_status=cx_status),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    assert [update["action_status"] for update in plan["status_updates"]] == (
        expected_updates
    )
    assert plan["cx_execution_status"] == cx_status


def test_result_ref_uses_supplied_cx_result_ref_and_repair_generation_id() -> None:
    result_ref = build_generation_remediation_execution_result_ref(
        cx_execution_result(
            execution_status="SUCCEEDED",
            repair_cx_generation_id="cx-gen-repair-001",
            result_ref={
                "source_service": "nex-cx",
                "ref_type": "repair_execution",
                "ref_id": "cx-repair-run-001",
                "relation": "result_of",
            },
        ),
        record=remediation_record(action_status="WAITING_ON_CX"),
    )

    assert result_ref["ref_id"] == "cx-repair-run-001"
    assert result_ref["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert result_ref["cx_execution_status"] == "SUCCEEDED"


@pytest.mark.parametrize(
    ("record_overrides", "result_overrides", "error_code"),
    [
        (
            {"action_schema_version": "old"},
            {},
            "ag.remediation_execution_record_schema_invalid",
        ),
        (
            {"action_type": "operator_followup"},
            {},
            "ag.remediation_execution_action_not_executable",
        ),
        (
            {"action_status": "UNKNOWN"},
            {},
            "ag.remediation_execution_status_invalid",
        ),
        (
            {"action_status": "COMPLETED"},
            {},
            "ag.remediation_execution_terminal_task",
        ),
        (
            {},
            {"result_schema_version": "old"},
            "ag.remediation_execution_cx_result_schema_invalid",
        ),
        (
            {},
            {"remediation_action_id": "other"},
            "ag.remediation_execution_action_mismatch",
        ),
        (
            {},
            {"parent_cx_generation_id": "other"},
            "ag.remediation_execution_generation_mismatch",
        ),
        (
            {},
            {"execution_status": "UNKNOWN"},
            "ag.remediation_execution_cx_status_invalid",
        ),
    ],
)
def test_handoff_plan_rejects_invalid_record_or_result(
    record_overrides: dict[str, Any],
    result_overrides: dict[str, Any],
    error_code: str,
) -> None:
    record = remediation_record()
    record.update(record_overrides)
    result = cx_execution_result(**result_overrides)

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        build_generation_remediation_execution_handoff_plan(
            record,
            result,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            planned_at=NOW,
        )

    assert exc_info.value.error_code == error_code


def test_handoff_plan_redaction_guard_rejects_sensitive_record() -> None:
    record = remediation_record()
    record["raw_prompt"] = "hidden prompt"

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        build_generation_remediation_execution_handoff_plan(
            record,
            cx_execution_result(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            planned_at=NOW,
        )

    assert exc_info.value.error_code == "ag.cx_remediation_execution_sensitive_payload"


def test_apply_handoff_plan_validates_plan_shape() -> None:
    record = remediation_record()

    with pytest.raises(GenerationRemediationExecutionError) as schema_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {"plan_schema_version": "old", "status_updates": []},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert schema_error.value.error_code == (
        "ag.remediation_execution_plan_schema_invalid"
    )

    with pytest.raises(GenerationRemediationExecutionError) as updates_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": [],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert updates_error.value.error_code == (
        "ag.remediation_execution_plan_updates_invalid"
    )


def test_apply_handoff_plan_rejects_bad_update_and_transition() -> None:
    record = remediation_record(action_status="ASSIGNED")

    with pytest.raises(GenerationRemediationExecutionError) as object_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": ["WAITING_ON_CX"],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert object_error.value.error_code == "ag.remediation_execution_plan_update_invalid"

    with pytest.raises(GenerationRemediationExecutionError) as transition_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": [{"action_status": "WAITING_ON_CX"}],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert transition_error.value.error_code == (
        "ag.generation_remediation_status_transition_invalid"
    )


def test_dispatch_generation_remediation_execution_reports_missing_task() -> None:
    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        dispatch_generation_remediation_execution(
            store=FakeRemediationTaskStore(None),
            cx_client=FakeCxExecutionClient(),
            remediation_action_id="missing",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "ag.remediation_execution_task_not_found"


def test_dispatch_generation_remediation_execution_collapses_generation_mismatch() -> None:
    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        dispatch_generation_remediation_execution(
            store=FakeRemediationTaskStore(remediation_record()),
            cx_client=FakeCxExecutionClient(),
            remediation_action_id="ag-remediation-action-001",
            cx_generation_id="other",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "ag.remediation_execution_task_not_found"


def test_dispatch_generation_remediation_execution_maps_client_failure() -> None:
    class FailingCxClient(FakeCxExecutionClient):
        def submit_remediation_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="cx down",
                retryable=True,
            )

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        dispatch_generation_remediation_execution(
            store=FakeRemediationTaskStore(remediation_record()),
            cx_client=FailingCxClient(),
            remediation_action_id="ag-remediation-action-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "ag.cx_remediation_execution_unavailable"
    assert exc_info.value.retryable is True


def test_sync_generation_remediation_execution_status_maps_client_failure() -> None:
    class FailingStatusClient(FakeCxExecutionStatusClient):
        def get_remediation_execution_detail(
            self,
            *,
            parent_cx_generation_id: str,
            remediation_action_id: str,
            request_id: str | None = None,
            trace_id: str | None = None,
        ) -> dict[str, Any]:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="cx detail down",
                retryable=True,
            )

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        sync_generation_remediation_execution_status(
            store=FakeRemediationTaskStore(
                remediation_record(action_status="WAITING_ON_CX")
            ),
            cx_status_client=FailingStatusClient(),
            remediation_action_id="ag-remediation-action-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "ag.cx_remediation_execution_unavailable"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    ("detail_overrides", "error_code"),
    [
        (
            {"detail_schema_version": "old"},
            "ag.remediation_execution_cx_detail_schema_invalid",
        ),
        (
            {"execution": ["not-an-object"]},
            "ag.remediation_execution_cx_detail_execution_invalid",
        ),
        (
            {"execution_status": "FAILED"},
            "ag.remediation_execution_cx_detail_status_mismatch",
        ),
        (
            {
                "execution": cx_execution_result(
                    execution_status="SUCCEEDED",
                    remediation_action_id="other",
                )
            },
            "ag.remediation_execution_action_mismatch",
        ),
    ],
)
def test_sync_generation_remediation_execution_status_rejects_invalid_detail(
    detail_overrides: dict[str, Any],
    error_code: str,
) -> None:
    detail = cx_execution_detail()
    detail.update(detail_overrides)

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        sync_generation_remediation_execution_status(
            store=FakeRemediationTaskStore(
                remediation_record(action_status="WAITING_ON_CX")
            ),
            cx_status_client=FakeCxExecutionStatusClient(detail),
            remediation_action_id="ag-remediation-action-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.error_code == error_code


def test_dispatch_generation_remediation_execution_maps_store_failures() -> None:
    class FailingGetStore(FakeRemediationTaskStore):
        def get(self, remediation_action_id: str) -> dict[str, Any] | None:
            from nex_ag.generation_remediation import GenerationRemediationError

            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    class FailingSaveStore(FakeRemediationTaskStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            from nex_ag.generation_remediation import GenerationRemediationError

            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    for store in (
        FailingGetStore(remediation_record()),
        FailingSaveStore(remediation_record()),
    ):
        with pytest.raises(GenerationRemediationExecutionError) as exc_info:
            dispatch_generation_remediation_execution(
                store=store,
                cx_client=FakeCxExecutionClient(),
                remediation_action_id="ag-remediation-action-001",
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
                planned_at=NOW,
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.retryable is True


def test_sync_generation_remediation_execution_status_maps_store_and_lookup_failures() -> None:
    class FailingGetStore(FakeRemediationTaskStore):
        def get(self, remediation_action_id: str) -> dict[str, Any] | None:
            from nex_ag.generation_remediation import GenerationRemediationError

            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    class FailingSaveStore(FakeRemediationTaskStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            from nex_ag.generation_remediation import GenerationRemediationError

            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    for store in (
        FailingGetStore(remediation_record(action_status="WAITING_ON_CX")),
        FailingSaveStore(remediation_record(action_status="WAITING_ON_CX")),
    ):
        with pytest.raises(GenerationRemediationExecutionError) as exc_info:
            sync_generation_remediation_execution_status(
                store=store,
                cx_status_client=FakeCxExecutionStatusClient(),
                remediation_action_id="ag-remediation-action-001",
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
                observed_at=NOW,
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.retryable is True

    with pytest.raises(GenerationRemediationExecutionError) as missing:
        sync_generation_remediation_execution_status(
            store=FakeRemediationTaskStore(None),
            cx_status_client=FakeCxExecutionStatusClient(),
            remediation_action_id="missing",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert missing.value.status_code == 404

    with pytest.raises(GenerationRemediationExecutionError) as mismatch:
        sync_generation_remediation_execution_status(
            store=FakeRemediationTaskStore(remediation_record()),
            cx_status_client=FakeCxExecutionStatusClient(),
            remediation_action_id="ag-remediation-action-001",
            cx_generation_id="other",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert mismatch.value.error_code == "ag.remediation_execution_task_not_found"


def test_clone_plan_returns_independent_copy() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    cloned = clone_plan(plan)
    cloned["status_updates"][0]["action_status"] = "CHANGED"

    assert plan["status_updates"][0]["action_status"] == "IN_PROGRESS"


def test_handoff_plan_default_clock_and_error_string() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(action_status="IN_PROGRESS"),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    error = GenerationRemediationExecutionError(
        status_code=409,
        error_code="example",
        detail="readable detail",
    )

    assert str(error) == "readable detail"
    assert str(plan["planned_at"]).endswith("Z")


def test_private_status_path_reports_unreachable_transition() -> None:
    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        _status_path("IN_PROGRESS", "PROPOSED")

    assert exc_info.value.error_code == (
        "ag.remediation_execution_status_transition_invalid"
    )
