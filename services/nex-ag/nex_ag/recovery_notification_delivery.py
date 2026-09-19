from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from .operator_review_cases import build_operator_review_escalation_dispatch_plan
from .operator_review_dispatch_execution import run_dispatch_execution_worker_once
from .recovery_notification_policy import RECOVERY_NOTIFICATION_PLAN_SCHEMA_VERSION


RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION = (
    "ag_recovery_notification_delivery_admission.v1"
)
RECOVERY_NOTIFICATION_DISPATCH_HANDOFF_SCHEMA_VERSION = (
    "ag_recovery_notification_dispatch_handoff.v1"
)
RECOVERY_NOTIFICATION_DELIVERY_MUTATION_SCHEMA_VERSION = (
    "ag_recovery_notification_delivery_mutation.v1"
)
RECOVERY_NOTIFICATION_DELIVERY_EXECUTION_SCHEMA_VERSION = (
    "ag_recovery_notification_delivery_execution.v1"
)
RECOVERY_NOTIFICATION_LIVE_ADMISSION_SCHEMA_VERSION = (
    "ag_recovery_notification_live_admission.v1"
)
RECOVERY_NOTIFICATION_DELIVERY_CHANNELS = (
    "MOCK",
    "NOTIFICATION",
    "EMAIL",
    "WEBHOOK",
    "INCIDENT",
)
DEFAULT_RECOVERY_NOTIFICATION_DELIVERY_CHANNEL = "MOCK"
DEFAULT_RECOVERY_NOTIFICATION_PROVIDER_PROFILE = "mock-default"
DEFAULT_RECOVERY_NOTIFICATION_DELIVERY_WORKER_ID = (
    "ag-recovery-notification-delivery-worker"
)
RECOVERY_NOTIFICATION_LIVE_CHANNELS = (
    "NOTIFICATION",
    "EMAIL",
    "WEBHOOK",
)


class RecoveryNotificationDeliveryError(ValueError):
    def __init__(
        self,
        detail: str,
        *,
        error_code: str,
        status_code: int = 422,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.error_code = error_code
        self.status_code = status_code


def build_recovery_notification_delivery_admission(
    notification_plan: Mapping[str, Any],
    case_record: Mapping[str, Any],
    escalation_record: Mapping[str, Any],
    *,
    channel_type: str | None = None,
    provider_profile: str | None = None,
    admitted_at: object | None = None,
) -> dict[str, Any]:
    plan = _mapping(
        notification_plan,
        field="notification_plan",
        error_code="ag.recovery_notification_delivery_plan_invalid",
    )
    case = _mapping(
        case_record,
        field="case_record",
        error_code="ag.recovery_notification_delivery_case_invalid",
    )
    escalation = _mapping(
        escalation_record,
        field="escalation_record",
        error_code="ag.recovery_notification_delivery_escalation_invalid",
    )
    _assert_plan_admissible(plan)

    case_id = _required_text(
        case.get("case_id"),
        field="case_record.case_id",
        error_code="ag.recovery_notification_delivery_case_id_required",
    )
    escalation_id = _required_text(
        escalation.get("escalation_id"),
        field="escalation_record.escalation_id",
        error_code="ag.recovery_notification_delivery_escalation_id_required",
    )
    escalation_case_id = _required_text(
        escalation.get("case_id"),
        field="escalation_record.case_id",
        error_code="ag.recovery_notification_delivery_escalation_case_id_required",
    )
    if case_id != escalation_case_id:
        raise RecoveryNotificationDeliveryError(
            "escalation_record.case_id must match case_record.case_id.",
            error_code="ag.recovery_notification_delivery_context_mismatch",
            status_code=409,
        )

    target = _verified_target(case, escalation)
    normalized_channel = _channel_type(channel_type)
    normalized_profile = _required_text(
        provider_profile or DEFAULT_RECOVERY_NOTIFICATION_PROVIDER_PROFILE,
        field="provider_profile",
        error_code="ag.recovery_notification_delivery_provider_profile_required",
        maximum=128,
    )
    decision = _mapping(
        plan.get("decision"),
        field="notification_plan.decision",
        error_code="ag.recovery_notification_delivery_decision_invalid",
    )
    safe_payload = _mapping(
        plan.get("safe_payload"),
        field="notification_plan.safe_payload",
        error_code="ag.recovery_notification_delivery_safe_payload_invalid",
    )
    return {
        "delivery_admission_schema_version": (
            RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION
        ),
        "admission_status": "ADMITTED",
        "notification_plan_id": _required_text(
            plan.get("notification_plan_id"),
            field="notification_plan.notification_plan_id",
            error_code="ag.recovery_notification_delivery_plan_id_required",
        ),
        "case_id": case_id,
        "escalation_id": escalation_id,
        "target": target,
        "delivery": {
            "channel_type": normalized_channel,
            "provider_profile": normalized_profile,
            "dispatch_intent": "NOTIFY_OPERATOR",
        },
        "notification": {
            "severity": str(decision.get("severity") or "UNKNOWN"),
            "service_id": _optional_text(safe_payload.get("service_id")),
            "worker_id": _optional_text(safe_payload.get("worker_id")),
        },
        "reason_codes": [
            "delivery_policy_authorized",
            "case_escalation_context_verified",
            "target_context_verified",
        ],
        "admitted_at": _datetime_value(admitted_at),
        "guardrails": {
            "existing_dispatch_outbox_required": True,
            "case_and_escalation_context_required": True,
            "case_or_escalation_auto_create_allowed": False,
            "dispatch_persistence_performed": False,
            "provider_invocation_performed": False,
            "raw_notification_payload_included": False,
            "provider_secrets_included": False,
        },
    }


def build_recovery_notification_live_admission(
    delivery_admission: Mapping[str, Any],
    provider_config: Mapping[str, Any],
    *,
    confirm_live_delivery: bool = False,
    admitted_at: object | None = None,
) -> dict[str, Any]:
    admission = _mapping(
        delivery_admission,
        field="delivery_admission",
        error_code="ag.recovery_notification_live_admission_invalid",
    )
    config = _mapping(
        provider_config,
        field="provider_config",
        error_code="ag.recovery_notification_live_provider_config_invalid",
    )
    if admission.get("delivery_admission_schema_version") != (
        RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION
    ) or admission.get("admission_status") != "ADMITTED":
        raise RecoveryNotificationDeliveryError(
            "delivery_admission must be an admitted S85 delivery contract.",
            error_code="ag.recovery_notification_live_base_admission_required",
            status_code=409,
        )
    selection = _mapping(
        admission.get("delivery"),
        field="delivery_admission.delivery",
        error_code="ag.recovery_notification_live_selection_invalid",
    )
    channel_type = _channel_type(selection.get("channel_type"))
    if channel_type not in RECOVERY_NOTIFICATION_LIVE_CHANNELS:
        raise RecoveryNotificationDeliveryError(
            "Recovery notification live delivery requires a notification channel.",
            error_code="ag.recovery_notification_live_channel_unsupported",
            status_code=409,
        )
    provider_profile = _required_text(
        selection.get("provider_profile"),
        field="delivery_admission.delivery.provider_profile",
        error_code="ag.recovery_notification_live_provider_profile_required",
        maximum=128,
    )
    if not confirm_live_delivery:
        raise RecoveryNotificationDeliveryError(
            "Recovery notification live delivery requires explicit confirmation.",
            error_code="ag.recovery_notification_live_confirmation_required",
            status_code=409,
        )
    if (
        config.get("configured_provider_mode") != "live_http"
        or config.get("effective_provider_mode") != "live_http"
        or config.get("live_network_calls_enabled") is not True
    ):
        raise RecoveryNotificationDeliveryError(
            "Recovery notification live HTTP provider is not enabled.",
            error_code="ag.recovery_notification_live_provider_not_enabled",
            status_code=409,
        )
    endpoint = _nested_mapping(
        config,
        "endpoints",
        "notification",
        error_code="ag.recovery_notification_live_endpoint_config_invalid",
    )
    if endpoint.get("configured") is not True:
        raise RecoveryNotificationDeliveryError(
            "Recovery notification live HTTP endpoint is not configured.",
            error_code="ag.recovery_notification_live_endpoint_required",
            status_code=409,
        )
    profile = _nested_mapping(
        config,
        "profiles",
        "live_readiness",
        provider_profile,
        error_code="ag.recovery_notification_live_provider_profile_unknown",
    )
    channel_types = profile.get("channel_types")
    if not isinstance(channel_types, list) or channel_type not in channel_types:
        raise RecoveryNotificationDeliveryError(
            "Recovery notification channel is not supported by provider profile.",
            error_code="ag.recovery_notification_live_profile_channel_mismatch",
            status_code=409,
        )
    target = _mapping(
        admission.get("target"),
        field="delivery_admission.target",
        error_code="ag.recovery_notification_live_target_invalid",
    )
    return {
        "live_admission_schema_version": (
            RECOVERY_NOTIFICATION_LIVE_ADMISSION_SCHEMA_VERSION
        ),
        "admission_status": "ADMITTED",
        "notification_plan_id": admission.get("notification_plan_id"),
        "case_id": admission.get("case_id"),
        "escalation_id": admission.get("escalation_id"),
        "target": dict(target),
        "delivery": {
            "channel_type": channel_type,
            "provider_profile": provider_profile,
            "provider_mode": "live_http",
            "dispatch_intent": "NOTIFY_OPERATOR",
        },
        "readiness": {
            "live_network_calls_enabled": True,
            "endpoint_configured": True,
            "token_configured": bool(endpoint.get("token_configured")),
            "explicit_confirmation": True,
        },
        "admitted_at": _datetime_value(admitted_at),
        "guardrails": {
            "generic_live_planner_default_closed": True,
            "injected_transport_required": True,
            "targeted_dispatch_filter_required": True,
            "dispatch_persistence_performed": False,
            "provider_invocation_performed": False,
            "endpoint_value_included": False,
            "provider_secret_included": False,
            "raw_notification_payload_included": False,
        },
    }


def build_recovery_notification_dispatch_handoff(
    notification_plan: Mapping[str, Any],
    delivery_admission: Mapping[str, Any],
    escalation_record: Mapping[str, Any],
    *,
    request_id: str,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    plan = _mapping(
        notification_plan,
        field="notification_plan",
        error_code="ag.recovery_notification_delivery_plan_invalid",
    )
    admission = _mapping(
        delivery_admission,
        field="delivery_admission",
        error_code="ag.recovery_notification_delivery_admission_invalid",
    )
    escalation = _mapping(
        escalation_record,
        field="escalation_record",
        error_code="ag.recovery_notification_delivery_escalation_invalid",
    )
    _assert_plan_admissible(plan)
    _assert_admission_matches_plan(admission, plan, escalation)

    safe_payload = _mapping(
        plan.get("safe_payload"),
        field="notification_plan.safe_payload",
        error_code="ag.recovery_notification_delivery_safe_payload_invalid",
    )
    selection = _mapping(
        admission.get("delivery"),
        field="delivery_admission.delivery",
        error_code="ag.recovery_notification_delivery_selection_invalid",
    )
    channel_type = _channel_type(selection.get("channel_type"))
    provider_profile = _required_text(
        selection.get("provider_profile"),
        field="delivery_admission.delivery.provider_profile",
        error_code="ag.recovery_notification_delivery_provider_profile_required",
        maximum=128,
    )
    dispatch_intent = _required_text(
        selection.get("dispatch_intent"),
        field="delivery_admission.delivery.dispatch_intent",
        error_code="ag.recovery_notification_delivery_dispatch_intent_required",
    )
    if dispatch_intent != "NOTIFY_OPERATOR":
        raise RecoveryNotificationDeliveryError(
            "delivery admission dispatch_intent must be NOTIFY_OPERATOR.",
            error_code="ag.recovery_notification_delivery_dispatch_intent_invalid",
        )
    notification_plan_id = _required_text(
        plan.get("notification_plan_id"),
        field="notification_plan.notification_plan_id",
        error_code="ag.recovery_notification_delivery_plan_id_required",
    )
    dispatch_plan = build_operator_review_escalation_dispatch_plan(
        dict(escalation),
        {
            "channel_type": channel_type,
            "provider_profile": provider_profile,
            "dispatch_intent": dispatch_intent,
            "reason_codes": _safe_reason_codes(admission.get("reason_codes")),
            "safe_subject": _required_text(
                safe_payload.get("title"),
                field="notification_plan.safe_payload.title",
                error_code="ag.recovery_notification_delivery_title_required",
                maximum=200,
            ),
            "safe_body": _required_text(
                safe_payload.get("summary"),
                field="notification_plan.safe_payload.summary",
                error_code="ag.recovery_notification_delivery_summary_required",
                maximum=240,
            ),
            "metadata": {
                "source_kind": "recovery_notification_delivery",
                "notification_plan_id": notification_plan_id,
                "delivery_admission_schema_version": admission.get(
                    "delivery_admission_schema_version"
                ),
                "recovery_notification_payload_redacted": True,
            },
        },
        request_id=_required_text(
            request_id,
            field="request_id",
            error_code="ag.recovery_notification_delivery_request_id_required",
        ),
        trace_id=_optional_text(trace_id),
        idempotency_key=_optional_text(idempotency_key),
        created_at=created_at,
    )
    dispatch_required = bool(
        dispatch_plan.get("decision", {}).get("dispatch_required")
    )
    return {
        "dispatch_handoff_schema_version": (
            RECOVERY_NOTIFICATION_DISPATCH_HANDOFF_SCHEMA_VERSION
        ),
        "handoff_status": "READY_TO_PERSIST" if dispatch_required else "BLOCKED",
        "notification_plan_id": notification_plan_id,
        "case_id": admission["case_id"],
        "escalation_id": admission["escalation_id"],
        "dispatch_plan": dispatch_plan,
        "dispatch_record": dispatch_plan.get("dispatch_record"),
        "blocking_reasons": list(
            dispatch_plan.get("decision", {}).get("blocking_reasons") or []
        ),
        "guardrails": {
            "existing_dispatch_planner_reused": True,
            "existing_dispatch_outbox_required": True,
            "dispatch_persistence_performed": False,
            "provider_invocation_performed": False,
            "live_channel_guardrail_preserved": channel_type != "MOCK",
            "raw_notification_payload_included": False,
        },
    }


def persist_recovery_notification_dispatch_handoff(
    dispatch_handoff: Mapping[str, Any],
    dispatch_store: Any,
) -> dict[str, Any]:
    handoff = _mapping(
        dispatch_handoff,
        field="dispatch_handoff",
        error_code="ag.recovery_notification_dispatch_handoff_invalid",
    )
    if handoff.get("dispatch_handoff_schema_version") != (
        RECOVERY_NOTIFICATION_DISPATCH_HANDOFF_SCHEMA_VERSION
    ):
        raise RecoveryNotificationDeliveryError(
            "dispatch_handoff has an unsupported schema version.",
            error_code="ag.recovery_notification_dispatch_handoff_schema_unsupported",
        )
    dispatch_record = handoff.get("dispatch_record")
    if handoff.get("handoff_status") != "READY_TO_PERSIST" or not isinstance(
        dispatch_record, Mapping
    ):
        raise RecoveryNotificationDeliveryError(
            "dispatch_handoff is not ready to persist.",
            error_code="ag.recovery_notification_dispatch_handoff_blocked",
            status_code=409,
        )
    if dispatch_store is None:
        raise RecoveryNotificationDeliveryError(
            "operator review escalation dispatch store is unavailable.",
            error_code="ag.recovery_notification_dispatch_store_unavailable",
            status_code=503,
        )

    record = dict(dispatch_record)
    metadata = dict(record.get("metadata") or {})
    request_signature = {
        "case_id": handoff.get("case_id"),
        "escalation_id": handoff.get("escalation_id"),
        "channel_type": record.get("channel_type"),
        "provider_profile": record.get("provider_profile"),
        "safe_body_hash": record.get("safe_body_hash"),
        "provider_payload_hash": record.get("provider_payload_hash"),
    }
    delivery_summary = {
        "delivery_mutation_schema_version": (
            RECOVERY_NOTIFICATION_DELIVERY_MUTATION_SCHEMA_VERSION
        ),
        "notification_plan_id": handoff.get("notification_plan_id"),
        "request_signature": request_signature,
        "provider_invocation_performed": False,
    }
    existing = dispatch_store.get(record["dispatch_id"])
    if existing is not None:
        existing_metadata = existing.get("metadata")
        existing_summary = (
            existing_metadata.get("recovery_notification_delivery")
            if isinstance(existing_metadata, Mapping)
            else None
        )
        if not isinstance(existing_summary, Mapping) or (
            existing_summary.get("request_signature") != request_signature
        ):
            raise RecoveryNotificationDeliveryError(
                "Idempotency key already maps to a different recovery notification.",
                error_code=(
                    "ag.recovery_notification_delivery_idempotency_conflict"
                ),
                status_code=409,
            )
        return _delivery_mutation_response(
            handoff,
            dict(existing),
            idempotency_status="REPLAYED",
            notification_plan_id=existing_summary.get("notification_plan_id"),
        )

    metadata["recovery_notification_delivery"] = delivery_summary
    record["metadata"] = metadata
    saved = dispatch_store.save(record)
    return _delivery_mutation_response(
        handoff,
        dict(saved),
        idempotency_status="NEW",
    )


def run_recovery_notification_delivery_mock_once(
    service: Any,
    *,
    dispatch_id: str,
    request_id: str,
    trace_id: str | None = None,
    worker_id: str = DEFAULT_RECOVERY_NOTIFICATION_DELIVERY_WORKER_ID,
    confirm_run: bool = False,
    executed_at: str | None = None,
) -> dict[str, Any]:
    normalized_dispatch_id = _required_text(
        dispatch_id,
        field="dispatch_id",
        error_code="ag.recovery_notification_delivery_dispatch_id_required",
    )
    dispatch = service.get_escalation_dispatch(normalized_dispatch_id)
    metadata = _mapping(
        dispatch.get("metadata"),
        field="dispatch.metadata",
        error_code="ag.recovery_notification_delivery_execution_metadata_invalid",
    )
    marker = metadata.get("recovery_notification_delivery")
    if not isinstance(marker, Mapping):
        raise RecoveryNotificationDeliveryError(
            "dispatch is not a recovery notification delivery.",
            error_code="ag.recovery_notification_delivery_execution_marker_required",
            status_code=409,
        )
    if str(dispatch.get("channel_type") or "").upper() != "MOCK":
        raise RecoveryNotificationDeliveryError(
            "bounded recovery notification execution supports MOCK only.",
            error_code="ag.recovery_notification_delivery_execution_mock_only",
            status_code=409,
        )

    worker_run = run_dispatch_execution_worker_once(
        service,
        request_id=_required_text(
            request_id,
            field="request_id",
            error_code="ag.recovery_notification_delivery_request_id_required",
        ),
        trace_id=_optional_text(trace_id),
        worker_id=_required_text(
            worker_id,
            field="worker_id",
            error_code="ag.recovery_notification_delivery_worker_id_required",
        ),
        batch_limit=1,
        provider_profile=_optional_text(dispatch.get("provider_profile")),
        provider_mode="mock_first_only",
        confirm_run=confirm_run,
        executed_at=executed_at,
        candidate_dispatch_ids={normalized_dispatch_id},
    )
    processed_count = int(worker_run.get("processed_count") or 0)
    execution_status = (
        "BLOCKED"
        if worker_run.get("run_status") == "BLOCKED"
        else "COMPLETED" if processed_count else "NOOP"
    )
    return {
        "delivery_execution_schema_version": (
            RECOVERY_NOTIFICATION_DELIVERY_EXECUTION_SCHEMA_VERSION
        ),
        "execution_status": execution_status,
        "dispatch_id": normalized_dispatch_id,
        "case_id": dispatch.get("case_id"),
        "escalation_id": dispatch.get("escalation_id"),
        "notification_plan_id": marker.get("notification_plan_id"),
        "worker_run": worker_run,
        "guardrails": {
            "existing_dispatch_execution_worker_reused": True,
            "target_dispatch_filter_applied": True,
            "batch_limit": 1,
            "provider_mode": "mock_first_only",
            "external_network_allowed": False,
            "live_channel_allowed": False,
            "new_tables_required": False,
        },
        "redaction": {
            "raw_notification_payload_included": False,
            "request_signature_included": False,
            "idempotency_key_included": False,
            "provider_secrets_included": False,
            "database_urls_included": False,
        },
    }


def _delivery_mutation_response(
    handoff: Mapping[str, Any],
    dispatch_record: dict[str, Any],
    *,
    idempotency_status: str,
    notification_plan_id: object | None = None,
) -> dict[str, Any]:
    return {
        "delivery_mutation_schema_version": (
            RECOVERY_NOTIFICATION_DELIVERY_MUTATION_SCHEMA_VERSION
        ),
        "mutation_status": "PERSISTED",
        "idempotency_status": idempotency_status,
        "notification_plan_id": (
            notification_plan_id or handoff.get("notification_plan_id")
        ),
        "case_id": handoff.get("case_id"),
        "escalation_id": handoff.get("escalation_id"),
        "dispatch_record": _without_private_request_signatures(dispatch_record),
        "delivery": {
            "dispatch_persistence_performed": idempotency_status == "NEW",
            "provider_invocation_performed": False,
        },
    }


def _without_private_request_signatures(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_private_request_signatures(child)
            for key, child in value.items()
            if str(key) != "request_signature"
        }
    if isinstance(value, list):
        return [_without_private_request_signatures(child) for child in value]
    return value


def _nested_mapping(
    value: Mapping[str, Any],
    *keys: str,
    error_code: str,
) -> dict[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            break
        current = current.get(key)
    if not isinstance(current, Mapping):
        raise RecoveryNotificationDeliveryError(
            f"{'.'.join(keys)} must be an object.",
            error_code=error_code,
        )
    return dict(current)


def _assert_admission_matches_plan(
    admission: Mapping[str, Any],
    plan: Mapping[str, Any],
    escalation: Mapping[str, Any],
) -> None:
    if admission.get("delivery_admission_schema_version") != (
        RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION
    ) or admission.get("admission_status") != "ADMITTED":
        raise RecoveryNotificationDeliveryError(
            "delivery_admission is not admitted or has an unsupported schema.",
            error_code="ag.recovery_notification_delivery_admission_not_admitted",
            status_code=409,
        )
    if admission.get("notification_plan_id") != plan.get("notification_plan_id"):
        raise RecoveryNotificationDeliveryError(
            "delivery_admission notification_plan_id does not match the plan.",
            error_code="ag.recovery_notification_delivery_plan_context_mismatch",
            status_code=409,
        )
    for field in ("case_id", "escalation_id"):
        if admission.get(field) != escalation.get(field):
            raise RecoveryNotificationDeliveryError(
                f"delivery_admission {field} does not match escalation_record.",
                error_code="ag.recovery_notification_delivery_context_mismatch",
                status_code=409,
            )
    target = _mapping(
        admission.get("target"),
        field="delivery_admission.target",
        error_code="ag.recovery_notification_delivery_target_invalid",
    )
    for field in ("target_service", "target_kind", "target_id"):
        if target.get(field) != escalation.get(field):
            raise RecoveryNotificationDeliveryError(
                f"delivery_admission target {field} does not match escalation_record.",
                error_code="ag.recovery_notification_delivery_target_mismatch",
                status_code=409,
            )


def _safe_reason_codes(value: object) -> list[str]:
    supplied = value if isinstance(value, list) else []
    normalized = [
        text
        for item in supplied
        if (text := _optional_text(item)) is not None
    ]
    return list(dict.fromkeys(["recovery_notification_delivery", *normalized]))


def _assert_plan_admissible(plan: Mapping[str, Any]) -> None:
    if plan.get("notification_plan_schema_version") != (
        RECOVERY_NOTIFICATION_PLAN_SCHEMA_VERSION
    ):
        raise RecoveryNotificationDeliveryError(
            "notification_plan has an unsupported schema version.",
            error_code="ag.recovery_notification_delivery_plan_schema_unsupported",
        )
    decision = _mapping(
        plan.get("decision"),
        field="notification_plan.decision",
        error_code="ag.recovery_notification_delivery_decision_invalid",
    )
    delivery = _mapping(
        plan.get("delivery"),
        field="notification_plan.delivery",
        error_code="ag.recovery_notification_delivery_state_invalid",
    )
    if plan.get("plan_status") != "READY" or not bool(
        decision.get("delivery_authorized_by_policy")
    ):
        raise RecoveryNotificationDeliveryError(
            "notification_plan is not authorized for delivery.",
            error_code="ag.recovery_notification_delivery_not_authorized",
            status_code=409,
        )
    if bool(delivery.get("performed")) or bool(
        delivery.get("provider_invocation_performed")
    ):
        raise RecoveryNotificationDeliveryError(
            "notification_plan already reports delivery activity.",
            error_code="ag.recovery_notification_delivery_already_performed",
            status_code=409,
        )


def _verified_target(
    case: Mapping[str, Any],
    escalation: Mapping[str, Any],
) -> dict[str, str]:
    target: dict[str, str] = {}
    for field in ("target_service", "target_kind", "target_id"):
        case_value = _required_text(
            case.get(field),
            field=f"case_record.{field}",
            error_code=f"ag.recovery_notification_delivery_case_{field}_required",
        )
        escalation_value = _required_text(
            escalation.get(field),
            field=f"escalation_record.{field}",
            error_code=(
                f"ag.recovery_notification_delivery_escalation_{field}_required"
            ),
        )
        if case_value != escalation_value:
            raise RecoveryNotificationDeliveryError(
                f"escalation_record.{field} must match case_record.{field}.",
                error_code="ag.recovery_notification_delivery_target_mismatch",
                status_code=409,
            )
        target[field] = case_value
    return target


def _mapping(
    value: object,
    *,
    field: str,
    error_code: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecoveryNotificationDeliveryError(
            f"{field} must be an object.",
            error_code=error_code,
        )
    return value


def _required_text(
    value: object,
    *,
    field: str,
    error_code: str,
    maximum: int = 200,
) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise RecoveryNotificationDeliveryError(
            f"{field} is required.",
            error_code=error_code,
        )
    if len(normalized) > maximum:
        raise RecoveryNotificationDeliveryError(
            f"{field} must be at most {maximum} characters.",
            error_code=error_code,
        )
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _channel_type(value: object) -> str:
    normalized = str(
        value or DEFAULT_RECOVERY_NOTIFICATION_DELIVERY_CHANNEL
    ).strip().upper()
    if normalized not in RECOVERY_NOTIFICATION_DELIVERY_CHANNELS:
        raise RecoveryNotificationDeliveryError(
            f"unsupported channel_type: {normalized}",
            error_code="ag.recovery_notification_delivery_channel_unsupported",
        )
    return normalized


def _datetime_value(value: object | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecoveryNotificationDeliveryError(
                "admitted_at must be an ISO-8601 timestamp.",
                error_code="ag.recovery_notification_delivery_admitted_at_invalid",
            ) from exc
    else:
        raise RecoveryNotificationDeliveryError(
            "admitted_at must be an ISO-8601 timestamp.",
            error_code="ag.recovery_notification_delivery_admitted_at_invalid",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
