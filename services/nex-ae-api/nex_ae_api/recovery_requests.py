from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_runtime.recovery import (
    GenerationRecoveryPolicyError,
    recovery_action_allowed,
    recovery_policy_hash,
    select_generation_recovery_policy,
)


RECOVERY_ACTIONS = {
    "retry",
    "repair",
    "sectional_retry",
    "regenerate",
    "fresh_retrieval_regenerate",
    "manual_accept_with_warning",
    "cancel",
}
TARGET_SERVICE_BY_ACTION = {
    "retry": "nex-cx",
    "repair": "nex-cx",
    "sectional_retry": "nex-cx",
    "regenerate": "nex-cx",
    "fresh_retrieval_regenerate": "nex-cx",
    "manual_accept_with_warning": "nex-ae-api",
    "cancel": "nex-ae-api",
}


class CxRecoverySourceClient(Protocol):
    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpCxRecoverySourceClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
        ).access_token
        response = httpx.get(
            f"{self.base_url}/api/v1/generations/{cx_generation_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ae-api",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise RecoveryRequestError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.generation_lookup_failed"),
                detail=body.get("detail", "CX generation lookup failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class GenerationRecoveryRequestStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["recovery_request_id"]] = record
        return record

    def get(self, recovery_request_id: str) -> dict[str, Any] | None:
        return self.records.get(recovery_request_id)


@dataclass(frozen=True)
class RecoveryRequestError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_RECOVERY_REQUEST_STORE = GenerationRecoveryRequestStore()


def build_default_cx_recovery_source_client() -> HttpCxRecoverySourceClient:
    return HttpCxRecoverySourceClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_generation_recovery_request_routes(
    app: FastAPI,
    *,
    store: GenerationRecoveryRequestStore | None = None,
    cx_client: CxRecoverySourceClient | None = None,
) -> None:
    recovery_store = store or DEFAULT_RECOVERY_REQUEST_STORE
    client = cx_client or build_default_cx_recovery_source_client()

    @app.post("/api/v1/recovery/generation-requests", response_model=None, status_code=202)
    def create_generation_recovery_request(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            cx_generation_id = required_string(payload, "cx_generation_id")
            requested_action = required_action(payload)
            cx_record = client.get_generation(
                cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            recovery_record = build_generation_recovery_request_record(
                source_payload=payload,
                cx_record=cx_record,
                requested_action=requested_action,
                request_id=request_id,
                trace_id=trace_id,
            )
            return recovery_store.save(recovery_record)
        except RecoveryRequestError as exc:
            return _recovery_request_problem_response(request, exc)

    @app.get(
        "/api/v1/recovery/generation-requests/{recovery_request_id}",
        response_model=None,
    )
    def get_generation_recovery_request(
        recovery_request_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = recovery_store.get(recovery_request_id)
        if record is None:
            return _recovery_request_problem_response(
                request,
                RecoveryRequestError(
                    status_code=404,
                    error_code="ae.recovery_request_not_found",
                    detail=f"Recovery request was not found: {recovery_request_id}",
                ),
            )
        return record


def build_generation_recovery_request_record(
    *,
    source_payload: dict[str, Any],
    cx_record: dict[str, Any],
    requested_action: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    if cx_record.get("status") != "FAILED":
        raise RecoveryRequestError(
            status_code=409,
            error_code="ae.recovery_source_not_failed",
            detail="Generation recovery requires a failed CX generation record.",
        )
    failure = required_mapping(cx_record, "failure")
    lineage = required_mapping(cx_record, "recovery_lineage")
    policy = recovery_policy_for_failure(failure.get("failure_code"))
    if not recovery_action_is_allowed(policy, requested_action):
        raise RecoveryRequestError(
            status_code=409,
            error_code="ae.recovery_action_not_allowed",
            detail=f"Recovery action is not allowed: {requested_action}",
        )

    now = _utc_now()
    policy_hash = recovery_policy_hash(policy) if policy else None
    changed_fields = safe_changed_fields(source_payload.get("changed_fields"))
    recovery_request_id = source_payload.get("recovery_request_id") or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-recovery-request:"
                f"{cx_record['cx_generation_id']}:{requested_action}:"
                f"{lineage.get('attempt_no', 1)}:{','.join(changed_fields)}"
            ),
        )
    )
    return {
        "recovery_request_schema_version": "ae_generation_recovery_request.v1",
        "recovery_request_id": recovery_request_id,
        "status": "ACCEPTED",
        "trace_id": trace_id,
        "request_id": request_id,
        "interaction_id": optional_string(source_payload.get("interaction_id")),
        "chat_document_id": optional_string(source_payload.get("chat_document_id")),
        "cx_generation_id": cx_record["cx_generation_id"],
        "parent_generation_id": lineage.get("parent_generation_id")
        or cx_record["cx_generation_id"],
        "requested_action": requested_action,
        "failure": {
            "failure_code": failure["failure_code"],
            "failure_class": failure["failure_class"],
            "owner_service": failure["owner_service"],
            "failed_stage": failure["failed_stage"],
            "retryable": failure["retryable"],
            "recovery_policy_id": failure.get("recovery_policy_id"),
            "recovery_policy_hash": failure.get("recovery_policy_hash"),
        },
        "policy": {
            "recovery_policy_id": policy["recovery_policy_id"] if policy else None,
            "recovery_policy_hash": policy_hash,
            "hash_status": policy_hash_status(
                stored_hash=failure.get("recovery_policy_hash"),
                active_hash=policy_hash,
            ),
            "operator_override_allowed": bool(
                policy and policy["operator_override_allowed"]
            ),
        },
        "dispatch": {
            "target_service": TARGET_SERVICE_BY_ACTION[requested_action],
            "endpoint_hint": endpoint_hint_for_action(requested_action),
            "attempt_no": next_attempt_no(lineage),
            "retry_after_seconds": policy.get("retry_after_seconds") if policy else None,
            "reuse_retrieval_package": reuse_retrieval_package_for_action(
                requested_action,
                lineage,
            ),
            "changed_fields": changed_fields,
            "requires_user_confirmation": requested_action
            == "manual_accept_with_warning",
        },
        "created_at": now,
        "updated_at": now,
    }


def required_action(payload: dict[str, Any]) -> str:
    action = required_string(payload, "requested_action")
    if action not in RECOVERY_ACTIONS:
        raise RecoveryRequestError(
            status_code=422,
            error_code="ae.recovery_action_invalid",
            detail=f"Unsupported recovery action: {action}",
        )
    return action


def recovery_policy_for_failure(failure_code: Any) -> dict[str, Any] | None:
    if not isinstance(failure_code, str) or not failure_code.strip():
        return None
    try:
        return select_generation_recovery_policy(failure_code)
    except GenerationRecoveryPolicyError:
        return None


def recovery_action_is_allowed(policy: dict[str, Any] | None, action: str) -> bool:
    if policy is None:
        return action == "cancel"
    return recovery_action_allowed(policy, action)


def policy_hash_status(*, stored_hash: Any, active_hash: str | None) -> str:
    if active_hash is None or stored_hash is None:
        return "UNAVAILABLE"
    if stored_hash == active_hash:
        return "MATCHED"
    return "STALE"


def endpoint_hint_for_action(action: str) -> str:
    if action == "retry":
        return "/api/v1/generations"
    if action in {"repair", "sectional_retry", "regenerate", "fresh_retrieval_regenerate"}:
        return "/api/v1/generations"
    if action == "manual_accept_with_warning":
        return "/api/v1/recovery/manual-acceptances"
    return "/api/v1/recovery/cancellations"


def next_attempt_no(lineage: dict[str, Any]) -> int:
    attempt_no = lineage.get("attempt_no", 1)
    if isinstance(attempt_no, int) and attempt_no >= 1:
        return attempt_no + 1
    return 2


def reuse_retrieval_package_for_action(
    action: str,
    lineage: dict[str, Any],
) -> bool:
    if action == "fresh_retrieval_regenerate":
        return False
    return bool(lineage.get("reuse_retrieval_package", False))


def safe_changed_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip() and safe_field_name(item.strip())
        }
    )


def safe_field_name(value: str) -> bool:
    lowered = value.lower()
    unsafe_fragments = (
        "prompt",
        "message",
        "content",
        "source_text",
        "output_text",
        "api_key",
        "password",
        "secret",
        "provider_url",
        "model_path",
    )
    return not any(fragment in lowered for fragment in unsafe_fragments)


def required_mapping(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise RecoveryRequestError(
            status_code=409,
            error_code="ae.recovery_source_invalid",
            detail=f"CX generation record is missing {field_name}.",
        )
    return value


def required_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RecoveryRequestError(
            status_code=422,
            error_code="ae.recovery_request_invalid",
            detail=f"{field_name} is required.",
        )
    return value.strip()


def optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _authorize_ae_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AE API requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _recovery_request_problem_response(
    request: Request,
    exc: RecoveryRequestError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation recovery request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/generation-recovery-request-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
