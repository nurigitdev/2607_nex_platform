from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from nex_runtime import issue_mock_service_token
from nex_ae_api.repaired_responses import (
    CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    build_repaired_response_handoff_record,
    optional_text,
)


AE_CX_REPAIRED_RESPONSE_SOURCE_PACKAGE_SCHEMA_VERSION = (
    "ae_cx_repaired_response_source_package.v1"
)
AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV = (
    "NEX_AE_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS"
)
DEFAULT_CX_BASE_URL = "http://127.0.0.1:8104"
DEFAULT_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS = 10.0

HttpRequester = Callable[..., httpx.Response]

SOURCE_MATERIAL_SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "messages",
    "model_path",
    "password",
    "passwd",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
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
SAFE_SOURCE_MATERIAL_METADATA_FLAGS = {
    "completion_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_tokens",
    "source_has_messages",
    "source_has_prompt",
    "total_tokens",
}


class CxRepairedResponseSourceClient(Protocol):
    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        ...

    def get_repaired_generation_record(
        self,
        *,
        cx_generation_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class CxRepairedResponseSourceClientError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpCxRepairedResponseSourceClient:
    base_url: str = DEFAULT_CX_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = DEFAULT_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

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
        body = self._get(
            (
                f"/api/v1/generations/{_quote_path_segment(parent_id)}"
                f"/remediation-executions/{_quote_path_segment(action_id)}"
            ),
            request_id=(
                request_id or f"ae-cx-repaired-response-detail:{action_id}"
            ),
            trace_id=trace_id,
            failure_namespace="detail",
            failure_label="CX remediation execution detail",
        )
        if body.get("detail_schema_version") != (
            CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
        ):
            raise CxRepairedResponseSourceClientError(
                status_code=502,
                error_code="ae.cx_repaired_response_source_response_invalid",
                detail=(
                    "CX remediation execution detail schema version is invalid."
                ),
                retryable=True,
            )
        return body

    def get_repaired_generation_record(
        self,
        *,
        cx_generation_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        generation_id = required_text(
            {"cx_generation_id": cx_generation_id},
            "cx_generation_id",
        )
        body = self._get(
            f"/api/v1/generations/{_quote_path_segment(generation_id)}",
            request_id=request_id or f"ae-cx-repaired-generation:{generation_id}",
            trace_id=trace_id,
            failure_namespace="generation",
            failure_label="CX repaired generation",
        )
        if body.get("record_schema_version") != (
            CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION
        ):
            raise CxRepairedResponseSourceClientError(
                status_code=502,
                error_code="ae.cx_repaired_response_source_response_invalid",
                detail="CX repaired generation record schema version is invalid.",
                retryable=True,
            )
        return body

    def _get(
        self,
        path: str,
        *,
        request_id: str,
        trace_id: str | None,
        failure_namespace: str,
        failure_label: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
        ).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": request_id,
            "X-Service-ID": "nex-ae-api",
        }
        selected_trace_id = optional_text(trace_id)
        if selected_trace_id is not None:
            headers["traceparent"] = f"00-{selected_trace_id}-00f067aa0ba902b7-01"

        try:
            response = self.requester(
                "GET",
                f"{self.base_url.rstrip('/')}{path}",
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise CxRepairedResponseSourceClientError(
                status_code=504,
                error_code=f"ae.cx_repaired_response_{failure_namespace}_timeout",
                detail=f"{failure_label} request timed out.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CxRepairedResponseSourceClientError(
                status_code=503,
                error_code=(
                    f"ae.cx_repaired_response_{failure_namespace}_unavailable"
                ),
                detail=f"{failure_label} endpoint is unavailable.",
                retryable=True,
            ) from exc

        body = _safe_response_json(
            response,
            failure_namespace=failure_namespace,
            failure_label=failure_label,
        )
        if response.status_code >= 400:
            raise CxRepairedResponseSourceClientError(
                status_code=response.status_code,
                error_code=str(
                    body.get(
                        "error_code",
                        f"ae.cx_repaired_response_{failure_namespace}_request_failed",
                    )
                ),
                detail=str(body.get("detail", f"{failure_label} request failed.")),
                retryable=bool(body.get("retryable", response.status_code >= 500)),
            )
        assert_cx_repaired_response_source_material_safe(body)
        return body


def build_default_cx_repaired_response_source_client(
    environ: Mapping[str, str] | None = None,
) -> HttpCxRepairedResponseSourceClient:
    env = environ or os.environ
    return HttpCxRepairedResponseSourceClient(
        base_url=env.get("NEX_CX_BASE_URL", DEFAULT_CX_BASE_URL).rstrip("/"),
        service_token=env.get("NEX_AE_TO_CX_SERVICE_TOKEN") or None,
        timeout_seconds=_positive_float_env(
            env,
            AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV,
            default=DEFAULT_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS,
        ),
    )


def build_repaired_response_source_package(
    *,
    source_payload: Mapping[str, Any],
    client: CxRepairedResponseSourceClient,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    assert_cx_repaired_response_source_material_safe(source_payload)
    parent_generation_id = required_text(
        source_payload,
        "original_cx_generation_id",
        error_code="ae.repaired_response_original_generation_id_required",
    )
    remediation_action_id = required_text(
        source_payload,
        "remediation_action_id",
        error_code="ae.repaired_response_remediation_action_id_required",
    )
    detail = client.get_remediation_execution_detail(
        parent_cx_generation_id=parent_generation_id,
        remediation_action_id=remediation_action_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    safe_detail = sanitized_cx_remediation_detail(detail)
    lineage = _linked_lineage(safe_detail)
    repair_generation_id = required_text(
        lineage,
        "repair_cx_generation_id",
        error_code="ae.repaired_response_repair_generation_id_required",
        status_code=409,
    )
    generation = client.get_repaired_generation_record(
        cx_generation_id=repair_generation_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    safe_generation = sanitized_cx_generation_record(generation)
    if safe_generation.get("cx_generation_id") != repair_generation_id:
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_repair_generation_mismatch",
            detail="CX repaired generation id does not match repaired lineage.",
        )
    if safe_generation.get("status") != "COMPLETED":
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_generation_not_completed",
            detail="CX repaired generation must be COMPLETED before AE handoff.",
        )

    package = {
        "source_package_schema_version": (
            AE_CX_REPAIRED_RESPONSE_SOURCE_PACKAGE_SCHEMA_VERSION
        ),
        "status": "READY_FOR_HANDOFF",
        "source": {
            "source_service": "nex-cx",
            "parent_cx_generation_id": parent_generation_id,
            "repair_cx_generation_id": repair_generation_id,
            "remediation_action_id": remediation_action_id,
        },
        "cx_remediation_detail": safe_detail,
        "repaired_generation_record": safe_generation,
        "redaction_summary": {
            "raw_output_included": False,
            "raw_prompt_included": False,
            "raw_source_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
            "storage_path_included": False,
            "free_text_storage": "hash_and_short_preview_only",
        },
    }
    assert_cx_repaired_response_source_material_safe(package)
    return package


def build_repaired_response_handoff_from_source_package(
    *,
    source_payload: Mapping[str, Any],
    source_package: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    handoff_request_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    package = validate_repaired_response_source_package(source_package)
    return build_repaired_response_handoff_record(
        source_payload=source_payload,
        cx_remediation_detail=package["cx_remediation_detail"],
        repaired_generation_record=package["repaired_generation_record"],
        handoff_request_id=handoff_request_id,
        request_id=request_id,
        trace_id=trace_id,
        created_at=created_at,
    )


def validate_repaired_response_source_package(
    source_package: Mapping[str, Any],
) -> dict[str, Any]:
    if source_package.get("source_package_schema_version") != (
        AE_CX_REPAIRED_RESPONSE_SOURCE_PACKAGE_SCHEMA_VERSION
    ):
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.repaired_response_source_package_invalid",
            detail="AE repaired response source package schema version is invalid.",
        )
    if source_package.get("status") != "READY_FOR_HANDOFF":
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_source_package_not_ready",
            detail="AE repaired response source package is not ready for handoff.",
        )
    detail = sanitized_cx_remediation_detail(
        _mapping(source_package.get("cx_remediation_detail"))
    )
    generation = sanitized_cx_generation_record(
        _mapping(source_package.get("repaired_generation_record"))
    )
    lineage = _linked_lineage(detail)
    if lineage.get("repair_cx_generation_id") != generation.get("cx_generation_id"):
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_source_package_lineage_mismatch",
            detail="AE repaired response source package lineage is inconsistent.",
        )
    result = dict(source_package)
    result["cx_remediation_detail"] = detail
    result["repaired_generation_record"] = generation
    assert_cx_repaired_response_source_material_safe(result)
    return result


def sanitized_cx_remediation_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    assert_cx_repaired_response_source_material_safe(detail)
    if detail.get("detail_schema_version") != (
        CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
    ):
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.repaired_response_cx_detail_invalid",
            detail="CX remediation execution detail schema version is invalid.",
        )
    lineage = _mapping(detail.get("repaired_generation_lineage"))
    diagnostics = _mapping(lineage.get("diagnostics"))
    result_ref = _mapping(lineage.get("result_ref"))
    return {
        "detail_schema_version": detail.get("detail_schema_version"),
        "projection_status": detail.get("projection_status"),
        "checked_at": optional_text(detail.get("checked_at")),
        "parent_cx_generation_id": optional_text(detail.get("parent_cx_generation_id")),
        "remediation_action_id": optional_text(detail.get("remediation_action_id")),
        "trace_id": optional_text(detail.get("trace_id")),
        "request_id": optional_text(detail.get("request_id")),
        "execution_status": optional_text(detail.get("execution_status")),
        "execution": _safe_execution_summary(_mapping(detail.get("execution"))),
        "repaired_generation_lineage": {
            "lineage_schema_version": optional_text(
                lineage.get("lineage_schema_version")
            ),
            "lineage_status": optional_text(lineage.get("lineage_status")),
            "parent_cx_generation_id": optional_text(
                lineage.get("parent_cx_generation_id")
            ),
            "root_cx_generation_id": optional_text(
                lineage.get("root_cx_generation_id")
            ),
            "repair_cx_generation_id": optional_text(
                lineage.get("repair_cx_generation_id")
            ),
            "remediation_action_id": optional_text(
                lineage.get("remediation_action_id")
            ),
            "action_type": optional_text(lineage.get("action_type")),
            "lineage_type": optional_text(lineage.get("lineage_type")),
            "execution_status": optional_text(lineage.get("execution_status")),
            "attempt_no": _positive_int(lineage.get("attempt_no")),
            "result_ref": _safe_result_ref(result_ref),
            "diagnostics": {
                "lineage_consistent": diagnostics.get("lineage_consistent") is True,
                "repair_generation_linked": (
                    diagnostics.get("repair_generation_linked") is True
                ),
                "result_ref_present": diagnostics.get("result_ref_present") is True,
                "result_ref_matches_remediation_action": (
                    diagnostics.get("result_ref_matches_remediation_action") is True
                ),
                "parent_generation_mutated": (
                    diagnostics.get("parent_generation_mutated") is not False
                ),
            },
            "redaction_summary": _safe_redaction_summary(
                _mapping(lineage.get("redaction_summary"))
            ),
        },
        "attention_required": detail.get("attention_required") is True,
        "redaction_summary": _safe_redaction_summary(
            _mapping(detail.get("redaction_summary"))
        ),
    }


def sanitized_cx_generation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    assert_cx_repaired_response_source_material_safe(record)
    if record.get("record_schema_version") != CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION:
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.repaired_response_generation_invalid",
            detail="CX repaired generation record schema version is invalid.",
        )
    request_metadata = _mapping(record.get("request_metadata"))
    response_metadata = _mapping(record.get("response_metadata"))
    return {
        "record_schema_version": record.get("record_schema_version"),
        "cx_generation_id": optional_text(record.get("cx_generation_id")),
        "status": optional_text(record.get("status")),
        "trace_id": optional_text(record.get("trace_id")),
        "request_id": optional_text(record.get("request_id")),
        "alias": optional_text(record.get("alias")),
        "provider_capability": optional_text(record.get("provider_capability")),
        "mo_generation_id": optional_text(record.get("mo_generation_id")),
        "request_metadata": {
            "provider_prompt_package_hash": optional_text(
                request_metadata.get("provider_prompt_package_hash")
            ),
            "generation_request_hash": optional_text(
                request_metadata.get("generation_request_hash")
            ),
            "grounding_required": request_metadata.get("grounding_required") is True,
            "retrieval_package_id": optional_text(
                request_metadata.get("retrieval_package_id")
            ),
            "retrieval_package_hash": optional_text(
                request_metadata.get("retrieval_package_hash")
            ),
            "selected_evidence_count": _non_negative_int(
                request_metadata.get("selected_evidence_count")
            ),
            "structured_draft_id": optional_text(
                request_metadata.get("structured_draft_id")
            ),
            "draft_validation_status": optional_text(
                request_metadata.get("draft_validation_status")
            ),
            "grounded_response_quality_status": optional_text(
                request_metadata.get("grounded_response_quality_status")
            ),
            "grounded_response_quality_issue_count": _non_negative_int(
                request_metadata.get("grounded_response_quality_issue_count")
            ),
        },
        "response_metadata": {
            "finish_reason": optional_text(response_metadata.get("finish_reason")),
            "output_hash": optional_text(response_metadata.get("output_hash")),
            "output_preview": (
                optional_text(response_metadata.get("output_preview")) or ""
            )[:120],
        },
        "usage": dict(_mapping(record.get("usage"))),
        "created_at": optional_text(record.get("created_at")),
        "updated_at": optional_text(record.get("updated_at")),
    }


def assert_cx_repaired_response_source_material_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_cx_repaired_response_source_material_keys(payload)
    if sensitive_keys:
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.cx_repaired_response_source_sensitive_payload",
            detail=(
                "CX repaired response source material contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def find_sensitive_cx_repaired_response_source_material_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def required_text(
    payload: Mapping[str, Any],
    key: str,
    *,
    error_code: str | None = None,
    status_code: int = 422,
) -> str:
    value = optional_text(payload.get(key))
    if value is None:
        raise CxRepairedResponseSourceClientError(
            status_code=status_code,
            error_code=(
                error_code or f"ae.cx_repaired_response_{key}_required"
            ),
            detail=f"{key} is required.",
            retryable=False,
        )
    return value


def _linked_lineage(detail: Mapping[str, Any]) -> dict[str, Any]:
    if detail.get("execution_status") != "SUCCEEDED":
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_execution_not_succeeded",
            detail="CX remediation execution must be SUCCEEDED before AE handoff.",
        )
    lineage = _mapping(detail.get("repaired_generation_lineage"))
    diagnostics = _mapping(lineage.get("diagnostics"))
    if (
        lineage.get("lineage_schema_version")
        != "cx_repaired_generation_lineage.v1"
        or lineage.get("lineage_status") != "LINKED"
    ):
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_lineage_not_linked",
            detail="CX repaired generation lineage is not linked.",
        )
    if (
        diagnostics.get("lineage_consistent") is not True
        or diagnostics.get("parent_generation_mutated") is not False
    ):
        raise CxRepairedResponseSourceClientError(
            status_code=409,
            error_code="ae.repaired_response_lineage_invalid",
            detail="CX repaired generation lineage diagnostics are invalid.",
        )
    return dict(lineage)


def _safe_response_json(
    response: httpx.Response,
    *,
    failure_namespace: str,
    failure_label: str,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CxRepairedResponseSourceClientError(
            status_code=502,
            error_code="ae.cx_repaired_response_source_response_invalid",
            detail=f"{failure_label} endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise CxRepairedResponseSourceClientError(
            status_code=502,
            error_code="ae.cx_repaired_response_source_response_invalid",
            detail=f"{failure_label} endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _collect_sensitive_keys(
    value: Any,
    *,
    path: str,
    matches: list[str],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text, child):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str, value: Any) -> bool:
    normalized = key.strip().lower()
    if normalized in SAFE_SOURCE_MATERIAL_METADATA_FLAGS:
        return False
    if normalized.endswith(("_included", "_stored")):
        return value is not False
    return any(part in normalized for part in SOURCE_MATERIAL_SENSITIVE_KEY_PARTS)


def _safe_execution_summary(execution: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "result_schema_version": optional_text(execution.get("result_schema_version")),
        "remediation_action_id": optional_text(execution.get("remediation_action_id")),
        "parent_cx_generation_id": optional_text(
            execution.get("parent_cx_generation_id")
        ),
        "repair_cx_generation_id": optional_text(
            execution.get("repair_cx_generation_id")
        ),
        "execution_status": optional_text(execution.get("execution_status")),
    }


def _safe_result_ref(value: Mapping[str, Any]) -> dict[str, str] | None:
    safe_ref = {
        key: optional_text(value.get(key))
        for key in ("source_service", "ref_type", "ref_id", "relation")
    }
    if any(field is None for field in safe_ref.values()):
        return None
    return {
        "source_service": safe_ref["source_service"] or "",
        "ref_type": safe_ref["ref_type"] or "",
        "ref_id": safe_ref["ref_id"] or "",
        "relation": safe_ref["relation"] or "",
    }


def _safe_redaction_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "raw_content_included": value.get("raw_content_included") is True,
        "prompt_text_included": value.get("prompt_text_included") is True,
        "evidence_text_included": value.get("evidence_text_included") is True,
        "provider_detail_included": value.get("provider_detail_included") is True,
    }


def _positive_float_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: float,
) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.cx_repaired_response_timeout_invalid",
            detail=f"{key} must be a positive number.",
        ) from exc
    if value <= 0:
        raise CxRepairedResponseSourceClientError(
            status_code=422,
            error_code="ae.cx_repaired_response_timeout_invalid",
            detail=f"{key} must be a positive number.",
        )
    return value


def _quote_path_segment(value: str) -> str:
    return quote(value, safe="")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 1
    return value


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)
