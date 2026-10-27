from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.agent_results import AgentResultAggregate, AgentResultError
from nex_ae_api.wa_source_projections import (
    SqlAlchemyAgentResultWaProjectionSource,
    WaSourceProjectionError,
    build_agent_result_wa_projection,
    register_wa_agent_result_source_routes,
)
from nex_runtime import issue_mock_service_token

TENANT = "VO00"
RESULT_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
AGENT_ID = "33333333-3333-4333-8333-333333333333"
DELIVERY_ID = "44444444-4444-4444-8444-444444444444"


def _aggregate(*, acknowledged: bool, agent_type: str = "IA") -> AgentResultAggregate:
    background = agent_type != "IA"
    result = {
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": agent_type,
        "project_id": "project-7" if background else None,
        "status": "PARTIAL" if background else "SUCCEEDED",
        "result_hash": "sha256:" + "a" * 64,
        "artifact_refs": ["artifact:1"],
        "evidence_refs": ["evidence:1"],
        "business_refs": ["business:1"],
        "source_work_item_ref": "work:1" if background else None,
        "source_claim_ref": "claim:1" if background else None,
        "source_claim_generation": 3 if background else None,
        "source_assignment_ref": "assignment:1" if background else None,
        "created_at": "2026-10-28T00:00:00Z",
        "structured_result": {"raw_output": "must-not-leak"},
    }
    delivery = {
        "tenant_id": TENANT,
        "delivery_id": DELIVERY_ID,
        "result_id": RESULT_ID,
        "required": True,
        "target_type": "WC_WORK_RESULT" if background else "WORKSPACE_RESULT",
        "state": "ACKNOWLEDGED" if acknowledged else "PENDING",
        "acknowledged_at": "2026-10-28T00:00:01Z" if acknowledged else None,
    }
    execution = {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "state": "SUCCEEDED" if acknowledged else "RUNNING",
    }
    return AgentResultAggregate(result, delivery, execution)


class _Source:
    def __init__(self, aggregate: AgentResultAggregate | None) -> None:
        self.aggregate = aggregate

    def get_projection(self, *, tenant_id: str, result_id: str):
        if tenant_id != TENANT or result_id != RESULT_ID or self.aggregate is None:
            return None
        return build_agent_result_wa_projection(self.aggregate)


class _ErrorSource:
    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable

    def get_projection(self, *, tenant_id: str, result_id: str):
        raise WaSourceProjectionError(
            "ae.wa_source_failed",
            "source failed",
            self.retryable,
        )


def _client(source) -> TestClient:
    app = FastAPI()
    register_wa_agent_result_source_routes(app, source=source)
    return TestClient(app)


def _headers(*, service_id: str = "nex-wa", scopes=None, tenant: str = TENANT):
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-ae-api",
        scopes=scopes or ["service:call", "work:source:read"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NeX-Tenant-Id": tenant,
    }


@pytest.mark.parametrize("acknowledged", [False, True])
def test_projection_exposes_completion_barrier_without_raw_result(acknowledged) -> None:
    response = _client(_Source(_aggregate(acknowledged=acknowledged))).get(
        f"/internal/v1/wa-sources/agent-results/{RESULT_ID}",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_execution_state"] == (
        "SUCCEEDED" if acknowledged else "RUNNING"
    )
    assert payload["required_delivery_state"] == (
        "ACKNOWLEDGED" if acknowledged else "PENDING"
    )
    assert payload["delivery_acknowledged_at"] == (
        "2026-10-28T00:00:01Z" if acknowledged else None
    )
    assert "structured_result" not in payload
    assert "raw_output" not in json.dumps(payload)


def test_background_projection_preserves_exact_claim_lineage() -> None:
    projection = build_agent_result_wa_projection(
        _aggregate(acknowledged=True, agent_type="PA")
    )

    assert projection["project_id"] == "project-7"
    assert projection["source_work_item_ref"] == "work:1"
    assert projection["source_claim_ref"] == "claim:1"
    assert projection["source_claim_generation"] == 3
    assert projection["source_assignment_ref"] == "assignment:1"
    assert projection["required_delivery_target_type"] == "WC_WORK_RESULT"


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-NeX-Tenant-Id": TENANT}, 401),
        (_headers(scopes=["service:call"]), 401),
        (_headers(service_id="nex-ag"), 403),
        (_headers(tenant="other-tenant"), 404),
    ],
)
def test_route_fails_closed_for_auth_scope_caller_and_tenant(headers, status) -> None:
    response = _client(_Source(_aggregate(acknowledged=True))).get(
        f"/internal/v1/wa-sources/agent-results/{RESULT_ID}",
        headers=headers,
    )
    assert response.status_code == status


def test_route_requires_tenant_and_available_source() -> None:
    no_tenant = _headers()
    no_tenant.pop("X-NeX-Tenant-Id")
    assert (
        _client(_Source(_aggregate(acknowledged=True)))
        .get(
            f"/internal/v1/wa-sources/agent-results/{RESULT_ID}",
            headers=no_tenant,
        )
        .status_code
        == 400
    )
    assert (
        _client(None)
        .get(
            f"/internal/v1/wa-sources/agent-results/{RESULT_ID}",
            headers=_headers(),
        )
        .status_code
        == 503
    )


def test_projection_rejects_delivery_and_execution_lineage_drift() -> None:
    aggregate = _aggregate(acknowledged=True)
    invalid_delivery = deepcopy(aggregate.delivery)
    invalid_delivery["result_id"] = "other-result"
    with pytest.raises(WaSourceProjectionError, match="delivery"):
        build_agent_result_wa_projection(
            AgentResultAggregate(aggregate.result, invalid_delivery, aggregate.execution)
        )

    invalid_execution = deepcopy(aggregate.execution)
    invalid_execution["agent_execution_id"] = "other-execution"
    with pytest.raises(WaSourceProjectionError, match="execution"):
        build_agent_result_wa_projection(
            AgentResultAggregate(aggregate.result, aggregate.delivery, invalid_execution)
        )


def test_projection_requires_authoritative_delivery_and_bounded_refs() -> None:
    aggregate = _aggregate(acknowledged=True)
    missing_delivery = deepcopy(aggregate.delivery)
    missing_delivery["required"] = False
    with pytest.raises(WaSourceProjectionError, match="authoritative delivery"):
        build_agent_result_wa_projection(
            AgentResultAggregate(aggregate.result, missing_delivery, aggregate.execution)
        )

    invalid_refs = deepcopy(aggregate.result)
    invalid_refs["artifact_refs"] = "artifact:1"
    with pytest.raises(WaSourceProjectionError, match="arrays"):
        build_agent_result_wa_projection(
            AgentResultAggregate(invalid_refs, aggregate.delivery, aggregate.execution)
        )

    invalid_refs["artifact_refs"] = [""]
    with pytest.raises(WaSourceProjectionError, match="bounded refs"):
        build_agent_result_wa_projection(
            AgentResultAggregate(invalid_refs, aggregate.delivery, aggregate.execution)
        )


@pytest.mark.parametrize(("retryable", "status"), [(False, 409), (True, 503)])
def test_route_maps_typed_source_failures(retryable, status) -> None:
    response = _client(_ErrorSource(retryable=retryable)).get(
        f"/internal/v1/wa-sources/agent-results/{RESULT_ID}",
        headers=_headers(),
    )
    assert response.status_code == status
    assert response.json()["error_code"] == "ae.wa_source_failed"


def test_sqlalchemy_source_maps_repository_errors_and_not_found() -> None:
    class _Repository:
        def __init__(self, value=None, error=None) -> None:
            self.value = value
            self.error = error

        def get(self, tenant_id, result_id):
            if self.error:
                raise self.error
            return self.value

    assert (
        SqlAlchemyAgentResultWaProjectionSource(_Repository()).get_projection(
            tenant_id=TENANT,
            result_id=RESULT_ID,
        )
        is None
    )
    projection = SqlAlchemyAgentResultWaProjectionSource(
        _Repository(value=_aggregate(acknowledged=True))
    ).get_projection(tenant_id=TENANT, result_id=RESULT_ID)
    assert projection is not None
    assert projection["result_id"] == RESULT_ID
    source = SqlAlchemyAgentResultWaProjectionSource(
        _Repository(error=AgentResultError("ae.store_unavailable", "offline", True))
    )
    with pytest.raises(WaSourceProjectionError, match="offline") as exc_info:
        source.get_projection(tenant_id=TENANT, result_id=RESULT_ID)
    assert exc_info.value.error_code == "ae.store_unavailable"
    assert exc_info.value.retryable is True
