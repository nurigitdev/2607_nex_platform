from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

WA_EVIDENCE_INGEST_JOB_TYPE = "WA_EVIDENCE_INGEST"
WA_EVIDENCE_INTAKE_REQUEST_SCHEMA = "wa_evidence_intake_request.v1"
WA_EVIDENCE_INTAKE_ADMISSION_SCHEMA = "wa_evidence_intake_admission.v1"
WA_ERROR_SCHEMA = "wa_error.v1"
WA_EXTERNAL_INTAKE_SOURCE_TYPES = ("AE_AGENT_RESULT", "AE_ARTIFACT")
WA_INTERNAL_SUPPORTING_SOURCE_TYPES = ("WC_WORK_RESULT",)
WA_EVIDENCE_INGEST_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "nex-wa-evidence-ingest-v1",
)

_REQUEST_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "correlation_id",
    }
)
_REQUEST_OPTIONAL_FIELDS = frozenset({"request_id", "trace_id"})
_REQUEST_ALLOWED_FIELDS = _REQUEST_REQUIRED_FIELDS | _REQUEST_OPTIONAL_FIELDS
_MAX_REQUEST_BYTES = 4096


class WaIntakeContractError(Exception):
    def __init__(self, error_code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class WaEvidenceIntakeRequest:
    schema_version: str
    tenant_id: str
    source_type: str
    source_ref: str
    source_revision_ref: str
    source_hash: str
    occurred_at: str
    correlation_id: str
    request_id: str | None = None
    trace_id: str | None = None

    def to_job_payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class WaEvidenceIntakeIdentity:
    job_id: str
    idempotency_key: str


@dataclass(frozen=True)
class WaEvidenceIntakeAdmission:
    schema_version: str
    job_id: str
    job_type: str
    status: str
    source_type: str
    source_ref: str
    source_revision_ref: str
    idempotent_reuse: bool
    request_id: str
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WaErrorResponse:
    schema_version: str
    error_code: str
    detail: str
    request_id: str
    trace_id: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_evidence_intake_request(
    value: Mapping[str, Any],
) -> WaEvidenceIntakeRequest:
    if not isinstance(value, Mapping):
        raise _invalid("request body must be an object")
    keys = set(value)
    forbidden = sorted(keys - _REQUEST_ALLOWED_FIELDS)
    if forbidden:
        raise WaIntakeContractError(
            "WA_INTAKE_PAYLOAD_FORBIDDEN",
            f"request contains forbidden fields: {', '.join(forbidden)}",
        )
    missing = sorted(_REQUEST_REQUIRED_FIELDS - keys)
    if missing:
        raise _invalid(f"request is missing required fields: {', '.join(missing)}")
    if len(canonical_json(dict(value)).encode("utf-8")) > _MAX_REQUEST_BYTES:
        raise WaIntakeContractError(
            "WA_INTAKE_PAYLOAD_TOO_LARGE",
            "request exceeds the bounded intake payload limit",
            413,
        )

    schema_version = _required_text(value["schema_version"], "schema_version", 64)
    if schema_version != WA_EVIDENCE_INTAKE_REQUEST_SCHEMA:
        raise _invalid("schema_version is unsupported")
    source_type = _required_text(value["source_type"], "source_type", 64)
    if source_type not in WA_EXTERNAL_INTAKE_SOURCE_TYPES:
        raise WaIntakeContractError(
            "WA_INTAKE_SOURCE_UNSUPPORTED",
            "source_type is not admitted for external intake",
        )
    try:
        source_hash = validate_hash_ref(value["source_hash"])
    except ValueError as exc:
        raise _invalid(
            "source_hash must be a lowercase SHA-256 hash reference"
        ) from exc

    return WaEvidenceIntakeRequest(
        schema_version=schema_version,
        tenant_id=_required_text(value["tenant_id"], "tenant_id", 128),
        source_type=source_type,
        source_ref=_required_text(value["source_ref"], "source_ref", 512),
        source_revision_ref=_required_text(
            value["source_revision_ref"],
            "source_revision_ref",
            256,
        ),
        source_hash=source_hash,
        occurred_at=_utc_timestamp(value["occurred_at"], "occurred_at"),
        correlation_id=_required_text(
            value["correlation_id"],
            "correlation_id",
            128,
        ),
        request_id=_optional_text(value.get("request_id"), "request_id", 128),
        trace_id=_optional_text(value.get("trace_id"), "trace_id", 128),
    )


def build_evidence_intake_identity(
    request: WaEvidenceIntakeRequest,
) -> WaEvidenceIntakeIdentity:
    source_identity = _source_identity(request)
    canonical_identity = canonical_json(source_identity)
    return WaEvidenceIntakeIdentity(
        job_id=str(uuid5(WA_EVIDENCE_INGEST_NAMESPACE, canonical_identity)),
        idempotency_key=semantic_sha256_hash_ref(source_identity),
    )


def require_compatible_intake_replay(
    existing: WaEvidenceIntakeRequest,
    candidate: WaEvidenceIntakeRequest,
) -> None:
    if _source_identity(existing) != _source_identity(candidate):
        raise WaIntakeContractError(
            "WA_SOURCE_IDEMPOTENCY_CONFLICT",
            "existing intake source identity does not match the request",
            409,
        )
    if existing.source_hash != candidate.source_hash:
        raise WaIntakeContractError(
            "WA_SOURCE_IDEMPOTENCY_CONFLICT",
            "source identity was reused with a different source hash",
            409,
        )


def build_evidence_intake_admission(
    request: WaEvidenceIntakeRequest,
    *,
    request_id: str,
    trace_id: str,
    idempotent_reuse: bool,
) -> WaEvidenceIntakeAdmission:
    identity = build_evidence_intake_identity(request)
    return WaEvidenceIntakeAdmission(
        schema_version=WA_EVIDENCE_INTAKE_ADMISSION_SCHEMA,
        job_id=identity.job_id,
        job_type=WA_EVIDENCE_INGEST_JOB_TYPE,
        status="QUEUED",
        source_type=request.source_type,
        source_ref=request.source_ref,
        source_revision_ref=request.source_revision_ref,
        idempotent_reuse=bool(idempotent_reuse),
        request_id=_required_text(request_id, "request_id", 128),
        trace_id=_required_text(trace_id, "trace_id", 128),
    )


def build_wa_error_response(
    error: WaIntakeContractError,
    *,
    request_id: str,
    trace_id: str,
) -> WaErrorResponse:
    return WaErrorResponse(
        schema_version=WA_ERROR_SCHEMA,
        error_code=_required_text(error.error_code, "error_code", 128),
        detail=_required_text(error.detail, "detail", 512),
        request_id=_required_text(request_id, "request_id", 128),
        trace_id=_required_text(trace_id, "trace_id", 128),
    )


def _source_identity(request: WaEvidenceIntakeRequest) -> dict[str, str]:
    return {
        "tenant_id": request.tenant_id,
        "source_type": request.source_type,
        "source_ref": request.source_ref,
        "source_revision_ref": request.source_revision_ref,
    }


def _required_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{field} must be a non-empty trimmed string")
    if len(value) > max_length:
        raise _invalid(f"{field} exceeds {max_length} characters")
    return value


def _optional_text(value: object, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    return _required_text(value, field, max_length)


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> WaIntakeContractError:
    return WaIntakeContractError("WA_INTAKE_REQUEST_INVALID", detail)
