from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_cx.remediation_execution_boundary import (
    RemediationExecutionBoundaryError,
    assert_cx_remediation_execution_payload_redaction_safe,
    remediation_action_executable_by_cx,
    remediation_lineage_type_for_action,
)


CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION = (
    "cx_remediation_execution_request.v1"
)
CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION = (
    "cx_remediation_execution_result.v1"
)
CX_REMEDIATION_EXECUTION_ACCEPTED_STATUS = "ACCEPTED"
PROVIDER_BOUNDARY = "cx_to_mo_service_api_only"
REDACTION_EXCLUDED_FIELDS = (
    "raw_prompt",
    "messages",
    "source_text",
    "output_text",
    "raw_output",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "storage_path",
    "api_key",
)


class ParentGenerationStore(Protocol):
    def get(self, cx_generation_id: str) -> dict[str, Any] | None:
        ...


@dataclass
class RemediationExecutionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_ids_by_parent: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        action_id = record["remediation_action_id"]
        previous = self.records.get(action_id)
        if previous is not None:
            self._remove_parent_index(previous["parent_cx_generation_id"], action_id)
        self.records[action_id] = record
        parent_ids = self.action_ids_by_parent.setdefault(
            record["parent_cx_generation_id"],
            [],
        )
        if action_id not in parent_ids:
            parent_ids.append(action_id)
        return record

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        return self.records.get(remediation_action_id)

    def list_for_parent(self, parent_cx_generation_id: str) -> list[dict[str, Any]]:
        return [
            self.records[action_id]
            for action_id in self.action_ids_by_parent.get(parent_cx_generation_id, [])
            if action_id in self.records
        ]

    def _remove_parent_index(self, parent_cx_generation_id: str, action_id: str) -> None:
        ids = self.action_ids_by_parent.get(parent_cx_generation_id, [])
        self.action_ids_by_parent[parent_cx_generation_id] = [
            existing_id for existing_id in ids if existing_id != action_id
        ]


DEFAULT_REMEDIATION_EXECUTION_STORE = RemediationExecutionStore()


@dataclass(frozen=True)
class RemediationExecutionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def register_remediation_execution_routes(
    app: FastAPI,
    *,
    generation_store: ParentGenerationStore,
    execution_store: RemediationExecutionStore | None = None,
) -> None:
    selected_execution_store = execution_store or DEFAULT_REMEDIATION_EXECUTION_STORE

    @app.post(
        "/api/v1/generations/{cx_generation_id}/remediation-executions",
        response_model=None,
        status_code=202,
    )
    def create_remediation_execution(
        cx_generation_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            validated_payload = validate_cx_remediation_execution_request(payload)
            parent_id = required_text(
                validated_payload,
                "parent_cx_generation_id",
            )
            if parent_id != cx_generation_id:
                raise RemediationExecutionError(
                    status_code=400,
                    error_code="cx.remediation_execution_parent_mismatch",
                    detail=(
                        "Remediation execution path generation id does not match "
                        "the request parent_cx_generation_id."
                    ),
                    retryable=False,
                )
            parent_record = generation_store.get(cx_generation_id)
            if parent_record is None:
                raise RemediationExecutionError(
                    status_code=404,
                    error_code="cx.remediation_execution_parent_not_found",
                    detail=(
                        "Parent CX generation record was not found: "
                        f"{cx_generation_id}"
                    ),
                    retryable=False,
                )
            result = build_cx_remediation_execution_result(
                validated_payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            selected_execution_store.save(result)
            return JSONResponse(status_code=202, content=result)
        except RemediationExecutionError as exc:
            return _remediation_execution_problem_response(request, exc)


def validate_cx_remediation_execution_request(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        assert_cx_remediation_execution_payload_redaction_safe(payload)
    except RemediationExecutionBoundaryError as exc:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_sensitive_payload",
            detail=str(exc),
            retryable=False,
        ) from exc

    if (
        payload.get("request_schema_version")
        != CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION
    ):
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_request_schema_invalid",
            detail="CX remediation execution request schema version is invalid.",
            retryable=False,
        )

    action_type = required_text(payload, "action_type")
    if not remediation_action_executable_by_cx(action_type):
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_action_not_executable",
            detail=f"Remediation action is not executable by CX: {action_type}",
            retryable=False,
        )

    lineage_type = required_text(payload, "lineage_type")
    expected_lineage_type = remediation_lineage_type_for_action(action_type)
    if lineage_type != expected_lineage_type:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_lineage_invalid",
            detail=(
                "Remediation execution lineage_type does not match action_type: "
                f"{action_type}"
            ),
            retryable=False,
        )

    policy = _mapping(payload.get("execution_policy"))
    if policy.get("parent_generation_mutation_allowed") is not False:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_parent_mutation_forbidden",
            detail="CX remediation execution cannot mutate the parent generation.",
            retryable=False,
        )
    if policy.get("provider_boundary") != PROVIDER_BOUNDARY:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_provider_boundary_invalid",
            detail="CX remediation execution must call MO service APIs only.",
            retryable=False,
        )

    evidence = _mapping(payload.get("evidence"))
    if evidence.get("raw_evidence_stored") is not False:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_evidence_invalid",
            detail="CX remediation execution requires raw_evidence_stored=false.",
            retryable=False,
        )

    required_text(payload, "remediation_action_id")
    required_text(payload, "parent_cx_generation_id")
    required_text(payload, "trace_id")
    required_text(payload, "request_id")
    return dict(payload)


def build_cx_remediation_execution_result(
    payload: Mapping[str, Any],
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = created_at or _utc_now()
    return {
        "result_schema_version": CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
        "remediation_action_id": required_text(payload, "remediation_action_id"),
        "parent_cx_generation_id": required_text(payload, "parent_cx_generation_id"),
        "repair_cx_generation_id": None,
        "tenant_id": optional_text(payload.get("tenant_id")),
        "trace_id": trace_id or required_text(payload, "trace_id"),
        "request_id": request_id or required_text(payload, "request_id"),
        "action_type": required_text(payload, "action_type"),
        "lineage_type": required_text(payload, "lineage_type"),
        "execution_status": CX_REMEDIATION_EXECUTION_ACCEPTED_STATUS,
        "result_ref": None,
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
            "excluded_fields": list(REDACTION_EXCLUDED_FIELDS),
        },
        "created_at": now,
        "updated_at": now,
    }


def required_text(payload: Mapping[str, Any], key: str) -> str:
    value = optional_text(payload.get(key))
    if value is None:
        raise RemediationExecutionError(
            status_code=422,
            error_code=f"cx.remediation_execution_{key}_required",
            detail=f"CX remediation execution requires {key}.",
            retryable=False,
        )
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _remediation_execution_problem_response(
    request: Request,
    exc: RemediationExecutionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX remediation execution request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-remediation-execution-request-failed"
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
