from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventEmitResult,
    OperationalEventStore,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


DISPOSITION_SCHEMA_VERSION = "ag_generation_quality_operator_disposition.v1"
DISPOSITION_LIST_SCHEMA_VERSION = "ag_generation_quality_operator_disposition_list.v1"
DISPOSITION_RECORDED_EVENT_TYPE = "ag.generation_quality.disposition_recorded"
MAX_OPERATOR_NOTE_PREVIEW_LENGTH = 240

ALLOWED_OPERATOR_ACTIONS = (
    "acknowledged",
    "false_positive",
    "needs_cx_repair",
    "needs_ae_followup",
    "escalated",
    "resolved",
)
ACTION_STATUS = {
    "acknowledged": "ACKNOWLEDGED",
    "false_positive": "DISMISSED",
    "needs_cx_repair": "IN_REPAIR",
    "needs_ae_followup": "IN_REPAIR",
    "escalated": "ESCALATED",
    "resolved": "RESOLVED",
}
ALLOWED_REASON_CODES = (
    "metadata_gap",
    "citation_quality",
    "retrieval_quality",
    "generation_quality",
    "user_feedback",
    "duplicate",
    "not_reproducible",
    "other",
)
ALLOWED_QUALITY_ISSUE_TYPES = (
    "retrieval_quality",
    "generation_quality",
    "citation_quality",
    "artifact_quality",
    "user_feedback",
    "operator_review",
)
ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES = (
    "nex-ae-api",
    "nex-cx",
    "nex-ag",
)
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
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
    "token",
)


@dataclass
class GenerationQualityDispositionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    disposition_ids_by_generation: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        disposition_id = record["disposition_id"]
        self.records[disposition_id] = record
        ids = self.disposition_ids_by_generation.setdefault(
            record["cx_generation_id"],
            [],
        )
        if disposition_id not in ids:
            ids.append(disposition_id)
        return record

    def get(self, disposition_id: str) -> dict[str, Any] | None:
        return self.records.get(disposition_id)

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        return [
            self.records[disposition_id]
            for disposition_id in self.disposition_ids_by_generation.get(
                cx_generation_id,
                [],
            )
            if disposition_id in self.records
        ]


@dataclass(frozen=True)
class GenerationQualityDispositionError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


DEFAULT_DISPOSITION_STORE = GenerationQualityDispositionStore()
DEFAULT_AUDIT_EVENT_STORE = InMemoryOperationalEventStore()


def register_generation_quality_disposition_routes(
    app: FastAPI,
    *,
    store: GenerationQualityDispositionStore | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    selected_store = store or GenerationQualityDispositionStore()
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_AUDIT_EVENT_STORE,
    )

    @app.post(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions",
        response_model=None,
    )
    def create_generation_quality_disposition(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            record = build_generation_quality_disposition_record(
                payload,
                cx_generation_id=cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except GenerationQualityDispositionError as exc:
            return _disposition_problem_response(request, exc)

        selected_store.save(record)
        emit_generation_quality_disposition_event(audit_emitter, record)
        return JSONResponse(status_code=202, content=record)

    @app.get(
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions",
        response_model=None,
    )
    def list_generation_quality_dispositions(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        return build_generation_quality_disposition_list_response(
            selected_store.list_for_generation(cx_generation_id),
            cx_generation_id=cx_generation_id,
            request_id=request_id_from_headers(request),
            trace_id=trace_id_from_headers(request),
        )

    @app.get(
        (
            "/admin/v1/generation-audit/generations/{cx_generation_id}"
            "/quality-dispositions/{disposition_id}"
        ),
        response_model=None,
    )
    def get_generation_quality_disposition(
        cx_generation_id: str,
        disposition_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = selected_store.get(disposition_id)
        if record is None or record.get("cx_generation_id") != cx_generation_id:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.generation_quality_disposition_not_found",
                title="Generation quality disposition not found",
                detail=f"Disposition was not found: {disposition_id}",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "generation-quality-disposition-not-found"
                ),
            )
        return record


def build_generation_quality_disposition_list_response(
    records: list[dict[str, Any]],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    items = sorted(
        records,
        key=lambda record: (str(record.get("updated_at")), str(record.get("disposition_id"))),
        reverse=True,
    )
    by_status: dict[str, int] = {}
    for record in items:
        status = str(record.get("disposition_status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "disposition_list_schema_version": DISPOSITION_LIST_SCHEMA_VERSION,
        "cx_generation_id": cx_generation_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": by_status,
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
    }


def emit_generation_quality_disposition_event(
    audit_emitter: OperationalEventEmitter,
    record: dict[str, Any],
) -> OperationalEventEmitResult:
    operator_ref = record.get("operator_ref") if isinstance(record.get("operator_ref"), dict) else {}
    return audit_emitter.safe_emit(
        event_type=DISPOSITION_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="Generation quality operator disposition recorded.",
        trace_id=record.get("trace_id"),
        request_id=record.get("request_id"),
        subject_ref={
            "type": "generation_quality_disposition",
            "id": str(record["disposition_id"]),
        },
        details={
            "cx_generation_id": record.get("cx_generation_id"),
            "disposition_id": record.get("disposition_id"),
            "operator_action": record.get("operator_action"),
            "disposition_status": record.get("disposition_status"),
            "operator_type": operator_ref.get("operator_type"),
            "operator_id": operator_ref.get("operator_id"),
            "reason_count": len(record.get("reason_codes") or []),
            "quality_issue_ref_count": len(record.get("quality_issue_refs") or []),
        },
    )


def build_generation_quality_disposition_record(
    payload: dict[str, Any],
    *,
    cx_generation_id: str,
    request_id: str,
    trace_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    assert_disposition_payload_redaction_safe(payload)
    generation_id = required_text({"cx_generation_id": cx_generation_id}, "cx_generation_id")
    operator_action = required_choice(
        payload,
        "operator_action",
        choices=ALLOWED_OPERATOR_ACTIONS,
    )
    operator = operator_ref(payload.get("operator_ref"))
    reason_codes = reason_code_list(payload.get("reason_codes"))
    note = optional_text(payload.get("operator_note"))
    note_hash = sha256_text(note) if note is not None else None
    now = created_at or _utc_now()
    disposition_id = optional_text(payload.get("disposition_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ag-generation-quality-disposition:"
                f"{generation_id}:{operator['operator_id']}:{operator_action}:"
                f"{','.join(reason_codes)}:{note_hash or 'no-note'}:{request_id}"
            ),
        )
    )
    return {
        "disposition_schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_id": disposition_id,
        "cx_generation_id": generation_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "operator_ref": operator,
        "operator_action": operator_action,
        "disposition_status": ACTION_STATUS[operator_action],
        "reason_codes": reason_codes,
        "operator_note_hash": note_hash,
        "operator_note_preview": operator_note_preview(note),
        "quality_issue_refs": quality_issue_refs(payload.get("quality_issue_refs")),
        "metadata": {
            "raw_note_stored": False,
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "operator_note_storage": "hash_and_short_preview_only",
        },
        "created_at": now,
        "updated_at": now,
    }


def operator_ref(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_operator_ref_required",
            detail="operator_ref is required.",
        )
    return {
        "operator_type": required_choice(
            value,
            "operator_type",
            choices=("service", "user"),
        ),
        "operator_id": required_text(value, "operator_id"),
        "tenant_id": optional_text(value.get("tenant_id")),
    }


def reason_code_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_reasons_invalid",
            detail="reason_codes must be a list when supplied.",
        )
    reason_codes: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason.strip():
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_reason_invalid",
                detail="reason code must be a non-empty string.",
            )
        normalized = reason.strip()
        if normalized not in ALLOWED_REASON_CODES:
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_reason_unsupported",
                detail=f"unsupported reason code: {normalized}",
            )
        if normalized not in reason_codes:
            reason_codes.append(normalized)
    return reason_codes


def quality_issue_refs(value: Any) -> list[dict[str, str | None]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_quality_refs_invalid",
            detail="quality_issue_refs must be a list when supplied.",
        )
    refs: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            raise GenerationQualityDispositionError(
                status_code=422,
                error_code="ag.generation_quality_disposition_quality_ref_invalid",
                detail="quality issue reference must be an object.",
            )
        refs.append(
            {
                "source_service": required_choice(
                    item,
                    "source_service",
                    choices=ALLOWED_QUALITY_ISSUE_SOURCE_SERVICES,
                ),
                "issue_type": required_choice(
                    item,
                    "issue_type",
                    choices=ALLOWED_QUALITY_ISSUE_TYPES,
                ),
                "issue_code": required_text(item, "issue_code"),
                "issue_ref_id": optional_text(item.get("issue_ref_id")),
            }
        )
    return refs


def operator_note_preview(note: str | None) -> str | None:
    if note is None:
        return None
    return note.strip()[:MAX_OPERATOR_NOTE_PREVIEW_LENGTH]


def required_choice(
    payload: dict[str, Any],
    key: str,
    *,
    choices: tuple[str, ...],
) -> str:
    value = required_text(payload, key)
    if value not in choices:
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code=f"ag.generation_quality_disposition_{key}_unsupported",
            detail=f"unsupported {key}: {value}",
        )
    return value


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code=f"ag.generation_quality_disposition_{key}_required",
            detail=f"{key} is required.",
        )
    return value.strip()


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def find_sensitive_disposition_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_disposition_payload_redaction_safe(payload: dict[str, Any]) -> None:
    sensitive_keys = find_sensitive_disposition_keys(payload)
    if sensitive_keys:
        raise GenerationQualityDispositionError(
            status_code=422,
            error_code="ag.generation_quality_disposition_sensitive_payload",
            detail=f"Disposition payload contains sensitive keys: {', '.join(sensitive_keys)}",
        )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _collect_sensitive_keys(value: Any, *, path: str, matches: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _authorize_ag_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _disposition_problem_response(
    request: Request,
    exc: GenerationQualityDispositionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation quality disposition rejected",
        detail=exc.detail,
        type_uri=(
            "https://nex-platform.local/problems/"
            "generation-quality-disposition-rejected"
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
