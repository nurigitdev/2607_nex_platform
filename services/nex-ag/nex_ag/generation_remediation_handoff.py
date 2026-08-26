from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from nex_runtime import issue_mock_service_token


CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION = (
    "cx_remediation_execution_request.v1"
)
CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION = (
    "cx_remediation_execution_result.v1"
)
CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION = (
    "cx_remediation_execution_detail.v1"
)
AG_CX_REMEDIATION_HANDOFF_SCHEMA_VERSION = (
    "ag_cx_remediation_handoff_client.v1"
)
AG_CX_REMEDIATION_TIMEOUT_ENV = "NEX_AG_CX_REMEDIATION_TIMEOUT_SECONDS"
DEFAULT_CX_BASE_URL = "http://127.0.0.1:8104"

CX_EXECUTABLE_ACTION_TYPES = (
    "retry_generation",
    "retrieval_repair",
    "citation_repair",
)
ACTION_EXECUTION_POLICIES = {
    "retry_generation": {
        "lineage_type": "retry",
        "retrieval_package_policy": "reuse_original_retrieval_package",
        "prompt_package_policy": "rebuild_with_retry_instruction_ref",
    },
    "retrieval_repair": {
        "lineage_type": "fresh_retrieval_regenerate",
        "retrieval_package_policy": "fresh_retrieval_required",
        "prompt_package_policy": "rebuild_with_retrieval_repair_instruction_ref",
    },
    "citation_repair": {
        "lineage_type": "repair",
        "retrieval_package_policy": "reuse_or_expand_cited_evidence",
        "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
    },
}
SAFE_FALSE_REDACTION_FLAGS = {
    "raw_prompt_stored",
    "raw_generation_output_stored",
    "raw_source_document_text_stored",
    "raw_feedback_comment_stored",
    "raw_operator_note_stored",
    "raw_evidence_stored",
}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "model_path",
    "password",
    "passwd",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_feedback_comment",
    "raw_generation_output",
    "raw_note",
    "raw_operator_note",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "raw_user_message",
    "secret",
    "source_text",
    "storage_path",
    "token",
)

HttpRequester = Callable[..., httpx.Response]


class CxRemediationExecutionClient(Protocol):
    def submit_remediation_action(
        self,
        action: Mapping[str, Any],
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        requested_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        ...


class CxRemediationExecutionStatusClient(Protocol):
    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class CxRemediationExecutionClientError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpCxRemediationExecutionClient:
    base_url: str = DEFAULT_CX_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 10.0
    requester: HttpRequester = httpx.request

    def submit_remediation_action(
        self,
        action: Mapping[str, Any],
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        requested_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = build_cx_remediation_execution_request(
            action,
            request_id=request_id,
            trace_id=trace_id,
            requested_at=requested_at,
            idempotency_key=idempotency_key,
        )
        return self._post_execution(payload)

    def _post_execution(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        trace_id = required_text(payload, "trace_id")
        request_id = required_text(payload, "request_id")
        parent_generation_id = required_text(payload, "parent_cx_generation_id")
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-cx",
        ).access_token
        try:
            response = self.requester(
                "POST",
                (
                    f"{self.base_url.rstrip('/')}/api/v1/generations/"
                    f"{parent_generation_id}/remediation-executions"
                ),
                json=dict(payload),
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ag",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="CX remediation execution endpoint is unavailable.",
                retryable=True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise CxRemediationExecutionClientError(
                status_code=response.status_code,
                error_code=str(
                    body.get(
                        "error_code",
                        "ag.cx_remediation_execution_request_failed",
                    )
                ),
                detail=str(body.get("detail", "CX remediation execution failed.")),
                retryable=bool(body.get("retryable", response.status_code >= 500)),
            )
        if (
            body.get("result_schema_version")
            != CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION
        ):
            raise CxRemediationExecutionClientError(
                status_code=502,
                error_code="ag.cx_remediation_execution_response_invalid",
                detail="CX remediation execution response schema version is invalid.",
                retryable=True,
            )
        return body

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        parent_id = required_text(
            {"parent_cx_generation_id": parent_cx_generation_id},
            "parent_cx_generation_id",
        )
        action_id = required_text(
            {"remediation_action_id": remediation_action_id},
            "remediation_action_id",
        )
        selected_request_id = request_id or f"ag-cx-remediation-status:{action_id}"
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-cx",
        ).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": selected_request_id,
            "X-Service-ID": "nex-ag",
        }
        selected_trace_id = optional_text(trace_id)
        if selected_trace_id is not None:
            headers["traceparent"] = f"00-{selected_trace_id}-00f067aa0ba902b7-01"
        try:
            response = self.requester(
                "GET",
                (
                    f"{self.base_url.rstrip('/')}/api/v1/generations/{parent_id}"
                    f"/remediation-executions/{action_id}"
                ),
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="CX remediation execution read-model endpoint is unavailable.",
                retryable=True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise CxRemediationExecutionClientError(
                status_code=response.status_code,
                error_code=str(
                    body.get(
                        "error_code",
                        "ag.cx_remediation_execution_detail_request_failed",
                    )
                ),
                detail=str(
                    body.get("detail", "CX remediation execution detail failed.")
                ),
                retryable=bool(body.get("retryable", response.status_code >= 500)),
            )
        if (
            body.get("detail_schema_version")
            != CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
        ):
            raise CxRemediationExecutionClientError(
                status_code=502,
                error_code="ag.cx_remediation_execution_response_invalid",
                detail=(
                    "CX remediation execution detail response schema version "
                    "is invalid."
                ),
                retryable=True,
            )
        return body


def build_default_cx_remediation_execution_client(
    environ: Mapping[str, str] | None = None,
) -> HttpCxRemediationExecutionClient:
    env = environ or os.environ
    return HttpCxRemediationExecutionClient(
        base_url=env.get("NEX_CX_BASE_URL", DEFAULT_CX_BASE_URL).rstrip("/"),
        service_token=env.get("NEX_AG_TO_CX_SERVICE_TOKEN") or None,
        timeout_seconds=_float_env(
            env,
            AG_CX_REMEDIATION_TIMEOUT_ENV,
            default=10.0,
        ),
    )


def build_cx_remediation_execution_request(
    action: Mapping[str, Any],
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    requested_at: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    assert_remediation_action_handoff_safe(action)
    action_type = required_text(action, "action_type")
    policy = ACTION_EXECUTION_POLICIES.get(action_type)
    if policy is None:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_action_not_executable",
            detail=f"Remediation action is not executable by CX: {action_type}",
            retryable=False,
        )

    action_id = required_text(action, "remediation_action_id")
    selected_request_id = request_id or required_text(action, "request_id")
    selected_trace_id = trace_id or required_text(action, "trace_id")
    parent_generation_id = required_text(action, "cx_generation_id")
    tenant_id = optional_text(action.get("tenant_id"))
    evidence = _evidence(action.get("evidence"))
    owner = _owner_ref(action.get("owner_ref"), tenant_id=tenant_id)
    return {
        "request_schema_version": CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION,
        "remediation_action_id": action_id,
        "parent_cx_generation_id": parent_generation_id,
        "tenant_id": tenant_id,
        "trace_id": selected_trace_id,
        "request_id": selected_request_id,
        "action_type": action_type,
        "lineage_type": policy["lineage_type"],
        "reason_codes": _text_list(action.get("reason_codes"), field="reason_codes"),
        "source_refs": _source_refs(action.get("source_refs")),
        "evidence": evidence,
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": policy["retrieval_package_policy"],
            "prompt_package_policy": policy["prompt_package_policy"],
            "provider_boundary": "cx_to_mo_service_api_only",
        },
        "idempotency_key": (
            idempotency_key
            or f"cx-remediation-execution:{action_id}:{selected_request_id}"
        ),
        "requested_by": {
            "source_service": "nex-ag",
            "owner_ref": owner,
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
        "requested_at": requested_at or _utc_now(),
    }


def assert_remediation_action_handoff_safe(action: Mapping[str, Any]) -> None:
    sensitive_paths: list[str] = []
    _collect_sensitive_paths(action, path="", matches=sensitive_paths)
    if sensitive_paths:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_sensitive_payload",
            detail=(
                "Remediation handoff payload contains sensitive keys: "
                f"{', '.join(sensitive_paths)}"
            ),
            retryable=False,
        )


def _collect_sensitive_paths(
    value: Any,
    *,
    path: str,
    matches: list[str],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key_value(key_text, child):
                matches.append(child_path)
            _collect_sensitive_paths(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_paths(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key_value(key: str, value: Any) -> bool:
    normalized = key.strip().lower()
    if normalized in SAFE_FALSE_REDACTION_FLAGS:
        return value is not False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _evidence(value: Any) -> dict[str, Any]:
    evidence = dict(value) if isinstance(value, Mapping) else {}
    if evidence.get("raw_evidence_stored") is not False:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_evidence_invalid",
            detail="CX remediation handoff requires raw_evidence_stored=false.",
            retryable=False,
        )
    hashes = _text_list(evidence.get("evidence_hashes"), field="evidence_hashes")
    previews = _text_list(evidence.get("evidence_previews"), field="evidence_previews")
    return {
        "evidence_hashes": hashes,
        "evidence_previews": previews,
        "raw_evidence_stored": False,
    }


def _source_refs(value: Any) -> list[dict[str, str]]:
    refs = []
    if not isinstance(value, list):
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_source_refs_invalid",
            detail="CX remediation handoff requires source_refs.",
            retryable=False,
        )
    for index, item in enumerate(value):
        ref = dict(item) if isinstance(item, Mapping) else {}
        refs.append(
            {
                "source_service": required_text(
                    ref,
                    "source_service",
                    error_detail=f"source_refs[{index}].source_service is required.",
                ),
                "ref_type": required_text(
                    ref,
                    "ref_type",
                    error_detail=f"source_refs[{index}].ref_type is required.",
                ),
                "ref_id": required_text(
                    ref,
                    "ref_id",
                    error_detail=f"source_refs[{index}].ref_id is required.",
                ),
                "relation": required_text(
                    ref,
                    "relation",
                    error_detail=f"source_refs[{index}].relation is required.",
                ),
            }
        )
    if not refs:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_source_refs_invalid",
            detail="CX remediation handoff requires at least one source ref.",
            retryable=False,
        )
    return refs


def _owner_ref(value: Any, *, tenant_id: str | None) -> dict[str, str | None]:
    owner = dict(value) if isinstance(value, Mapping) else {}
    return {
        "owner_type": optional_text(owner.get("owner_type")) or "service",
        "owner_id": optional_text(owner.get("owner_id")) or "nex-ag",
        "tenant_id": optional_text(owner.get("tenant_id")) or tenant_id,
    }


def _text_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code=f"ag.cx_remediation_execution_{field}_invalid",
            detail=f"CX remediation handoff requires {field}.",
            retryable=False,
        )
    texts = [str(item) for item in value if isinstance(item, str) and item]
    if not texts:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code=f"ag.cx_remediation_execution_{field}_invalid",
            detail=f"CX remediation handoff requires at least one {field} value.",
            retryable=False,
        )
    return list(dict.fromkeys(texts))


def required_text(
    payload: Mapping[str, Any],
    key: str,
    *,
    error_detail: str | None = None,
) -> str:
    value = optional_text(payload.get(key))
    if value is None:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code=f"ag.cx_remediation_execution_{key}_required",
            detail=error_detail or f"CX remediation handoff requires {key}.",
            retryable=False,
        )
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CxRemediationExecutionClientError(
            status_code=response.status_code,
            error_code="ag.cx_remediation_execution_response_invalid",
            detail="CX remediation execution endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise CxRemediationExecutionClientError(
            status_code=response.status_code,
            error_code="ag.cx_remediation_execution_response_invalid",
            detail="CX remediation execution endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _float_env(env: Mapping[str, str], key: str, *, default: float) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        ) from exc
    if value <= 0:
        raise CxRemediationExecutionClientError(
            status_code=422,
            error_code="ag.cx_remediation_execution_timeout_invalid",
            detail=f"{key} must be a positive number.",
            retryable=False,
        )
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
