from __future__ import annotations

import json
from pathlib import Path

import yaml

from nex_ag.operations import (
    build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan,
)


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts" / "openapi" / "nex-ag.openapi.yaml"
OPERATIONS_SCHEMA_PATH = (
    ROOT
    / "contracts"
    / "schemas"
    / "service"
    / "nex_ag"
    / "operations_projection.v1.schema.json"
)
ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "ack-states/reconcile-expired"
)


def _openapi() -> dict[str, object]:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def _operations_schema() -> dict[str, object]:
    return json.loads(OPERATIONS_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_expiry_reconciliation_openapi_freezes_protected_route() -> None:
    contract = _openapi()
    operation = contract["paths"][ROUTE]["post"]

    assert operation["operationId"] == (
        "postAgOperatorReviewDispatchDaemonLivenessAckExpiryReconcile"
    )
    assert operation["tags"] == ["Operations"]
    assert operation["requestBody"]["required"] is False
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgOperatorReviewDispatchDaemonLivenessAckExpiryReconciliationRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {
        "$ref": "#/components/schemas/AgOperatorReviewDispatchDaemonLivenessAckExpiryReconciliationProjection"
    }
    assert set(operation["responses"]) == {"200", "400", "401", "503"}


def test_expiry_reconciliation_openapi_freezes_request_and_response_bounds() -> None:
    schemas = _openapi()["components"]["schemas"]
    request = schemas[
        "AgOperatorReviewDispatchDaemonLivenessAckExpiryReconciliationRequest"
    ]
    response = schemas[
        "AgOperatorReviewDispatchDaemonLivenessAckExpiryReconciliationProjection"
    ]
    overlay = schemas[
        "AgOperatorReviewDispatchDaemonLivenessAckExpiryReconciliationOverlay"
    ]

    assert request["additionalProperties"] is False
    assert request["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
        "default": 50,
    }
    assert response["properties"]["run_status"]["enum"] == [
        "COMPLETED",
        "COMPLETED_WITH_CONFLICTS",
    ]
    assert response["properties"]["route"]["properties"]["path"]["const"] == ROUTE
    assert response["properties"]["route"]["properties"]["protected"][
        "const"
    ] is True
    assert overlay["properties"]["source_table"]["const"] == (
        "ag_op_review_ack_state"
    )
    assert overlay["properties"]["state_mutated"]["const"] is False


def test_operations_schema_requires_expiry_reconciliation_overlay() -> None:
    schema = _operations_schema()
    overlay = schema["$defs"][
        "dashboard_operator_review_dispatch_daemon_liveness_ack_state_overlay"
    ]
    expiry = schema["$defs"][
        "dashboard_operator_review_liveness_ack_expiry_reconciliation_overlay"
    ]

    assert "expiry_reconciliation" in overlay["required"]
    assert overlay["properties"]["expiry_reconciliation"] == {
        "$ref": "#/$defs/dashboard_operator_review_liveness_ack_expiry_reconciliation_overlay"
    }
    assert expiry["properties"]["reconcile_path"]["const"] == ROUTE
    assert expiry["properties"]["source_table"]["const"] == (
        "ag_op_review_ack_state"
    )
    assert "PENDING" in expiry["properties"]["reconciliation_status"]["enum"]
    assert "RECONCILED" in expiry["properties"]["reconciliation_status"]["enum"]


def test_recovery_policy_reports_active_ack_state_persistence() -> None:
    policy = (
        build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy(
            "STALE"
        )
    )
    recovery = build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
        {
            "status": "ok",
            "summary": {"status": "STALE"},
            "worker": {
                "service_id": "nex-ag",
                "worker_id": "ag-dispatch-execution-daemon",
            },
        }
    )

    assert policy["state_storage"] == {
        "status": "PERSISTED",
        "source_table": "ag_op_review_ack_state",
        "new_tables_required": False,
    }
    assert recovery["guardrails"][
        "acknowledgement_suppression_state_persistence_active"
    ] is True
    assert "acknowledgement_suppression_state_persistence_deferred" not in recovery[
        "guardrails"
    ]
