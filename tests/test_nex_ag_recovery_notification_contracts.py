from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

import nex_ag.operations as operations
from nex_ag.recovery_notification_policy import (
    RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV,
    RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV,
    RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV,
    RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV,
    RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV,
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
DELIVERY_SCHEMA_PATH = (
    ROOT
    / "contracts"
    / "schemas"
    / "service"
    / "nex_ag"
    / "recovery_notification_delivery.v1.schema.json"
)
FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "operations"
    / "ag_operations_dashboard_snapshot.mock_success.json"
)
DELIVERY_FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "operations"
    / "ag_recovery_notification_delivery.mock_success.json"
)
DELIVERY_NEGATIVE_FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "tests"
    / "negative"
    / "operations"
    / "ag_recovery_notification_delivery.raw_payload_leak.json"
)
LIVE_DELIVERY_FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "operations"
    / "ag_recovery_notification_live_delivery.mock_success.json"
)
LIVE_MUTATION_FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "operations"
    / "ag_recovery_notification_live_mutation.mock_success.json"
)
LIVE_ENDPOINT_NEGATIVE_FIXTURE_PATH = (
    ROOT
    / "contracts"
    / "tests"
    / "negative"
    / "operations"
    / "ag_recovery_notification_live_delivery.endpoint_leak.json"
)
PREVIEW_PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-preview"
)
DELIVERY_PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-deliveries"
)
POLICY_ENV_NAMES = (
    RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV,
    RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV,
    RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV,
    RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV,
    RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV,
)


def _clear_policy_environment(monkeypatch) -> None:
    for name in POLICY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_dashboard_includes_recovery_notification_projection(monkeypatch) -> None:
    _clear_policy_environment(monkeypatch)

    dashboard = operations.build_operations_dashboard_snapshot_projection(
        recent_limit=5,
        request_trace_id="trace-0837",
    )
    dispatches = dashboard["operator_review_escalation_dispatches"]
    notification = dispatches["recovery_notification"]

    assert notification["projection_status"] == "READY"
    assert notification["notification_status"] == "PREVIEW_ONLY"
    assert notification["summary"]["severity"] == "ERROR"
    assert notification["summary"]["provider_invocation_performed"] is False
    assert notification["preview"]["safe_payload"]["liveness_status"] == (
        "MISSING"
    )
    assert notification["preview_path"] == PREVIEW_PATH
    assert notification["request_trace_id"] == "trace-0837"


def test_empty_dashboard_dispatch_projection_includes_notification(
    monkeypatch,
) -> None:
    _clear_policy_environment(monkeypatch)

    dispatches = (
        operations._empty_dashboard_operator_review_escalation_dispatch_section({})
    )

    assert dispatches["recovery_notification"]["projection_status"] == "READY"
    assert dispatches["recovery_notification"]["new_tables_required"] is False


def test_dashboard_schema_and_fixture_freeze_recovery_notification() -> None:
    schema = json.loads(OPERATIONS_SCHEMA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)
    dispatch_schema = schema["$defs"][
        "dashboard_operator_review_escalation_dispatches"
    ]
    notification = fixture["operator_review_escalation_dispatches"][
        "recovery_notification"
    ]

    assert "recovery_notification" in dispatch_schema["required"]
    assert dispatch_schema["properties"]["recovery_notification"] == {
        "$ref": "#/$defs/dashboard_recovery_notification"
    }
    assert notification["notification_status"] == "PREVIEW_ONLY"
    assert notification["preview"]["delivery"]["performed"] is False
    assert "delivery" in schema["$defs"]["dashboard_recovery_notification"][
        "required"
    ]
    assert notification["delivery"]["delivery_status"] == "EMPTY"


def test_openapi_freezes_recovery_notification_preview_contract() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = contract["paths"][PREVIEW_PATH]["get"]
    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    component = contract["components"]["schemas"]["AgRecoveryNotificationPlan"]

    assert operation["operationId"] == (
        "getAgOperatorReviewDispatchDaemonRecoveryNotificationPreview"
    )
    assert operation["tags"] == ["Operations"]
    assert set(operation["responses"]) == {"200", "400", "401"}
    assert response_schema == {
        "$ref": "#/components/schemas/AgRecoveryNotificationPlan"
    }
    assert component["additionalProperties"] is False
    assert component["properties"]["preview_route"]["properties"]["path"][
        "const"
    ] == PREVIEW_PATH
    assert component["properties"]["delivery"]["properties"][
        "provider_invocation_performed"
    ]["const"] is False


def test_delivery_schema_accepts_safe_fixture_and_rejects_raw_payload() -> None:
    schema = json.loads(DELIVERY_SCHEMA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(DELIVERY_FIXTURE_PATH.read_text(encoding="utf-8"))
    negative = json.loads(
        DELIVERY_NEGATIVE_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(fixture)
    assert list(validator.iter_errors(negative))
    assert fixture["source_statuses"]["nex-ag"]["source_table"] == (
        "ag_op_esc_dispatches"
    )
    assert fixture["redaction"]["request_signatures_included"] is False


def test_delivery_schema_freezes_live_mutation_execution_and_endpoint_guard() -> None:
    schema = json.loads(DELIVERY_SCHEMA_PATH.read_text(encoding="utf-8"))
    live_delivery = json.loads(
        LIVE_DELIVERY_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    live_mutation = json.loads(
        LIVE_MUTATION_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    endpoint_leak = json.loads(
        LIVE_ENDPOINT_NEGATIVE_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    validator.validate(live_delivery)
    validator.validate(live_mutation)
    assert list(validator.iter_errors(endpoint_leak))
    execution = live_delivery["recent"][0]["execution"]
    assert execution["provider_mode"] == "live_http"
    assert execution["http_status_code"] == 202
    assert live_mutation["live_delivery"]["provider_invocation_performed"] is False
    assert '"provider_endpoint":' not in json.dumps(live_delivery)
    assert '"provider_token":' not in json.dumps(live_mutation)


def test_openapi_freezes_recovery_notification_delivery_contract() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    path_item = contract["paths"][DELIVERY_PATH]
    get_operation = path_item["get"]
    post_operation = path_item["post"]
    schemas = contract["components"]["schemas"]

    assert get_operation["operationId"] == (
        "listAgOperatorReviewDispatchDaemonRecoveryNotificationDeliveries"
    )
    assert get_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AgRecoveryNotificationDeliveryProjection"}
    assert post_operation["operationId"] == (
        "postAgOperatorReviewDispatchDaemonRecoveryNotificationDelivery"
    )
    assert post_operation["requestBody"]["required"] is True
    assert post_operation["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AgRecoveryNotificationDeliveryRequest"}
    assert set(post_operation["responses"]) == {
        "200",
        "201",
        "400",
        "401",
        "404",
        "409",
        "422",
        "503",
    }
    assert schemas["AgRecoveryNotificationDeliveryRequest"][
        "additionalProperties"
    ] is False
    assert schemas["AgRecoveryNotificationDeliveryRequest"]["properties"][
        "confirm_live_delivery"
    ] == {"type": "boolean", "default": False}
    assert schemas["AgRecoveryNotificationDeliveryMutation"][
        "additionalProperties"
    ] is False
    assert "live_delivery" in schemas["AgRecoveryNotificationDeliveryMutation"][
        "required"
    ]
    assert schemas["AgRecoveryNotificationDeliveryProjection"][
        "additionalProperties"
    ] is False
    recent = schemas["AgRecoveryNotificationDeliveryProjection"]["properties"][
        "recent"
    ]["items"]
    assert "execution" in recent["required"]
    assert recent["properties"]["execution"]["additionalProperties"] is False
