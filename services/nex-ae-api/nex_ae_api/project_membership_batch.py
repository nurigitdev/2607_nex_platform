from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

PROJECT_MEMBERSHIP_ADD_MANY = "PROJECT.MEMBERSHIP.ADD_MANY"
PROJECT_MEMBERSHIP_BATCH_ADMISSION_SCHEMA_VERSION = (
    "p8.project_membership_batch_admission.v1"
)
OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION = "oa_employee_batch_resolution.v1"
DEFAULT_OA_BASE_URL = "http://127.0.0.1:8101"
DEFAULT_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS = 15.0
MAX_PROJECT_MEMBERSHIP_BATCH_SIZE = 50

_MEMBER_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
_OA_STATUSES = frozenset(
    {
        "RESOLVED",
        "INVALID_EMPLOYEE_ID",
        "EMPLOYEE_NOT_FOUND",
        "SUBJECT_INACTIVE",
        "NAME_MISMATCH",
        "DUPLICATE_INPUT",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "tenant_id",
        "requester_subject_id",
        "project_id",
        "candidates",
        "member_role",
    }
)
_CANDIDATE_FIELDS = frozenset({"input_index", "employee_id", "expected_name"})
_OA_RESPONSE_FIELDS = frozenset(
    {
        "resolution_schema_version",
        "service_id",
        "tenant_id",
        "requested_count",
        "resolved_count",
        "rejected_count",
        "results",
        "resolution_evidence_hash",
        "request_id",
        "trace_id",
    }
)
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")

HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class ProjectMembershipBatchError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaEmployeeBatchResolutionSource(Protocol):
    def resolve_batch(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class HttpOaEmployeeBatchResolutionSource:
    base_url: str = DEFAULT_OA_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = DEFAULT_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

    def resolve_batch(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]:
        request_id = _text(request_id, "request_id", 200)
        trace_id = _trace_id_value(trace_id)
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-oa",
            )
            response = self.requester(
                "POST",
                (
                    f"{self.base_url.rstrip('/')}"
                    "/internal/v1/identity/employees:resolve-batch"
                ),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                    "X-NeX-Tenant-Id": str(payload.get("tenant_id", "")),
                },
                json=dict(payload),
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise _unavailable(
                "OA employee batch resolution timed out.",
                status_code=504,
                error_code="ae.oa_employee_batch_timeout",
            ) from exc
        except (httpx.HTTPError, AeOutboundServiceTokenError) as exc:
            raise _unavailable(
                "OA employee batch resolution is unavailable.",
                error_code="ae.oa_employee_batch_unavailable",
            ) from exc

        body = _response_object(response)
        if response.status_code >= 400:
            raise ProjectMembershipBatchError(
                status_code=response.status_code,
                error_code="ae.oa_employee_batch_rejected",
                detail="OA employee batch resolution was rejected.",
                retryable=response.status_code >= 500,
            )
        return body


def build_default_oa_employee_batch_resolution_source(
    environ: Mapping[str, str] | None = None,
) -> HttpOaEmployeeBatchResolutionSource:
    env = os.environ if environ is None else environ
    return HttpOaEmployeeBatchResolutionSource(
        base_url=env.get("NEX_OA_BASE_URL", DEFAULT_OA_BASE_URL),
        service_token=env.get("NEX_AE_TO_OA_SERVICE_TOKEN"),
        timeout_seconds=_positive_float(
            env.get("NEX_AE_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS"),
            default=DEFAULT_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS,
        ),
    )


def admit_project_membership_batch(
    request: Mapping[str, Any],
    *,
    source: OaEmployeeBatchResolutionSource,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    normalized = _normalize_request(request)
    oa_request = {
        "tenant_id": normalized["tenant_id"],
        "candidates": deepcopy(normalized["candidates"]),
    }
    try:
        raw_response = source.resolve_batch(
            oa_request,
            request_id=_text(request_id, "request_id", 200),
            trace_id=_trace_id_value(trace_id),
        )
    except ProjectMembershipBatchError:
        raise
    except Exception as exc:
        raise _unavailable("OA employee batch resolution is unavailable.") from exc
    resolution = _validate_resolution(raw_response, normalized)

    admitted_by_subject: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for result in resolution["results"]:
        if result["resolution_status"] != "RESOLVED":
            rejected.append(_rejected_candidate(result))
            continue
        subject_id = result["subject_id"]
        if subject_id in admitted_by_subject:
            rejected.append(
                {
                    "input_index": result["input_index"],
                    "outcome_code": "DUPLICATE_SUBJECT",
                    "normalized_employee_id": result["normalized_employee_id"],
                }
            )
            continue
        admitted_by_subject[subject_id] = {
            "subject_id": subject_id,
            "subject_revision": result["subject_revision"],
            "tenant_membership_revision": result["tenant_membership_revision"],
        }

    admitted = sorted(
        admitted_by_subject.values(),
        key=lambda item: item["subject_id"].encode("utf-8"),
    )
    target_subject_ids = [item["subject_id"] for item in admitted]
    governed_payload = None
    payload_hash = None
    approval_projection = None
    directive = "REJECTED"
    if admitted:
        directive = "CONTINUE"
        governed_payload = {
            "tenant_id": normalized["tenant_id"],
            "requester_subject_id": normalized["requester_subject_id"],
            "project_id": normalized["project_id"],
            "target_subject_ids": target_subject_ids,
            "member_role": normalized["member_role"],
            "resolution_evidence_hash": resolution["resolution_evidence_hash"],
        }
        payload_hash = nsl_write_payload_hash_ref(governed_payload)
        approval_projection = {
            "operation_id": PROJECT_MEMBERSHIP_ADD_MANY,
            "project_id": normalized["project_id"],
            "target_subject_ids": target_subject_ids,
            "target_count": len(target_subject_ids),
            "rejected_count": len(rejected),
            "member_role": normalized["member_role"],
            "resolution_evidence_hash": resolution["resolution_evidence_hash"],
            "payload_hash": payload_hash,
        }

    result = {
        "schema_version": PROJECT_MEMBERSHIP_BATCH_ADMISSION_SCHEMA_VERSION,
        "directive": directive,
        "operation_id": PROJECT_MEMBERSHIP_ADD_MANY,
        "tenant_id": normalized["tenant_id"],
        "requester_subject_id": normalized["requester_subject_id"],
        "project_id": normalized["project_id"],
        "member_role": normalized["member_role"],
        "requested_count": len(normalized["candidates"]),
        "admitted_count": len(admitted),
        "rejected_count": len(rejected),
        "admitted_members": admitted,
        "rejected_candidates": sorted(rejected, key=lambda item: item["input_index"]),
        "resolution_evidence_hash": resolution["resolution_evidence_hash"],
        "protected_intake_hash": semantic_sha256_hash_ref(normalized),
        "governed_payload": governed_payload,
        "payload_hash": payload_hash,
        "approval_projection": approval_projection,
    }
    result["admission_hash"] = semantic_sha256_hash_ref(result)
    return result


def batch_approval_display_summary(admission: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_project_membership_batch_admission(admission)
    projection = normalized["approval_projection"]
    if normalized["directive"] != "CONTINUE" or not isinstance(projection, Mapping):
        raise _invalid("Rejected membership batch cannot enter approval.")
    return deepcopy(dict(projection))


def require_project_membership_batch_approval_binding(
    admission: Mapping[str, Any],
    approval_request: object,
) -> str:
    normalized = validate_project_membership_batch_admission(admission)
    if normalized["directive"] != "CONTINUE":
        raise _invalid("Rejected membership batch cannot bind approval.")
    request = _approval_record(approval_request)
    summary = request.get("display_safe_summary")
    if (
        request.get("payload_hash") != normalized["payload_hash"]
        or not isinstance(summary, Mapping)
        or dict(summary) != normalized["approval_projection"]
    ):
        raise _invalid("ApprovalRequest does not bind the exact membership batch.")
    return normalized["payload_hash"]


def validate_project_membership_batch_admission(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Membership batch admission must be an object.")
    supplied = deepcopy(dict(value))
    if supplied.get("schema_version") != PROJECT_MEMBERSHIP_BATCH_ADMISSION_SCHEMA_VERSION:
        raise _invalid("Membership batch admission schema is invalid.")
    try:
        validate_hash_ref(supplied.get("admission_hash"))
        validate_hash_ref(supplied.get("resolution_evidence_hash"))
        validate_hash_ref(supplied.get("protected_intake_hash"))
    except ValueError as exc:
        raise _invalid("Membership batch admission digest is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in supplied.items() if key != "admission_hash"}
    )
    if supplied["admission_hash"] != expected:
        raise _invalid("Membership batch admission integrity failed.")
    if supplied.get("operation_id") != PROJECT_MEMBERSHIP_ADD_MANY:
        raise _invalid("Membership batch operation identity is invalid.")
    tenant_id = _text(supplied.get("tenant_id"), "tenant_id", 128)
    requester = _text(
        supplied.get("requester_subject_id"), "requester_subject_id", 128
    )
    project_id = _text(supplied.get("project_id"), "project_id", 128)
    role = supplied.get("member_role")
    if role not in _MEMBER_ROLES:
        raise _invalid("Membership batch role is invalid.")
    directive = supplied.get("directive")
    if directive not in {"CONTINUE", "REJECTED"}:
        raise _invalid("Membership batch directive is invalid.")
    admitted = supplied.get("admitted_members")
    rejected = supplied.get("rejected_candidates")
    if not isinstance(admitted, list) or not isinstance(rejected, list):
        raise _invalid("Membership batch item projections are invalid.")
    if (
        supplied.get("admitted_count") != len(admitted)
        or supplied.get("rejected_count") != len(rejected)
        or supplied.get("requested_count") != len(admitted) + len(rejected)
    ):
        raise _invalid("Membership batch counts are inconsistent.")
    subject_ids = []
    for item in admitted:
        if not isinstance(item, Mapping) or set(item) != {
            "subject_id",
            "subject_revision",
            "tenant_membership_revision",
        }:
            raise _invalid("Membership batch admitted member is invalid.")
        subject_ids.append(_text(item.get("subject_id"), "subject_id", 128))
        try:
            _positive_revision(item.get("subject_revision"))
            _positive_revision(item.get("tenant_membership_revision"))
        except ProjectMembershipBatchError as exc:
            raise _invalid("Membership batch authority revision is invalid.") from exc
    if len(subject_ids) != len(set(subject_ids)):
        raise _invalid("Membership batch admitted subjects are duplicated.")
    if admitted != sorted(admitted, key=lambda item: str(item.get("subject_id")).encode()):
        raise _invalid("Membership batch admitted subjects are not canonically sorted.")
    rejected_indexes = set()
    for item in rejected:
        if not isinstance(item, Mapping) or set(item) - {
            "input_index",
            "outcome_code",
            "normalized_employee_id",
        }:
            raise _invalid("Membership batch rejected candidate is invalid.")
        index = item.get("input_index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index in rejected_indexes
        ):
            raise _invalid("Membership batch rejected candidate index is invalid.")
        rejected_indexes.add(index)
        if item.get("outcome_code") not in _OA_STATUSES | {"DUPLICATE_SUBJECT"}:
            raise _invalid("Membership batch rejected outcome is invalid.")
        if "normalized_employee_id" in item:
            _text(item["normalized_employee_id"], "normalized_employee_id", 128)
    if directive == "REJECTED":
        if admitted:
            raise _invalid("Rejected membership batch must have no admitted subjects.")
        if any(
            supplied.get(field) is not None
            for field in ("governed_payload", "payload_hash", "approval_projection")
        ):
            raise _invalid("Rejected membership batch must not contain write authority.")
        return supplied
    governed = supplied.get("governed_payload")
    projection = supplied.get("approval_projection")
    if not admitted or not isinstance(governed, Mapping) or not isinstance(
        projection, Mapping
    ):
        raise _invalid("Executable membership batch authority is incomplete.")
    expected_governed = {
        "tenant_id": tenant_id,
        "requester_subject_id": requester,
        "project_id": project_id,
        "target_subject_ids": subject_ids,
        "member_role": role,
        "resolution_evidence_hash": supplied["resolution_evidence_hash"],
    }
    if dict(governed) != expected_governed:
        raise _invalid("Membership batch governed payload is stale.")
    expected_hash = nsl_write_payload_hash_ref(governed)
    if supplied.get("payload_hash") != expected_hash:
        raise _invalid("Membership batch payload hash is invalid.")
    if projection.get("payload_hash") != expected_hash:
        raise _invalid("Membership batch approval projection is stale.")
    expected_projection = {
        "operation_id": PROJECT_MEMBERSHIP_ADD_MANY,
        "project_id": project_id,
        "target_subject_ids": subject_ids,
        "target_count": len(subject_ids),
        "rejected_count": len(rejected),
        "member_role": role,
        "resolution_evidence_hash": supplied["resolution_evidence_hash"],
        "payload_hash": expected_hash,
    }
    if dict(projection) != expected_projection:
        raise _invalid("Membership batch approval projection is inconsistent.")
    return supplied


def _normalize_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _REQUEST_FIELDS:
        raise _invalid("Membership batch intake envelope is invalid.")
    tenant_id = _text(value.get("tenant_id"), "tenant_id", 128)
    requester = _text(value.get("requester_subject_id"), "requester_subject_id", 128)
    project_id = _text(value.get("project_id"), "project_id", 128)
    role = value.get("member_role", "MEMBER")
    if not isinstance(role, str) or role.strip().upper() not in _MEMBER_ROLES:
        raise _invalid("Membership batch role is invalid.")
    role = role.strip().upper()
    raw_candidates = value.get("candidates")
    if isinstance(raw_candidates, (str, bytes)) or not isinstance(
        raw_candidates, Sequence
    ):
        raise _invalid("Membership batch candidates must be an array.")
    if not 1 <= len(raw_candidates) <= MAX_PROJECT_MEMBERSHIP_BATCH_SIZE:
        raise _invalid("Membership batch requires between 1 and 50 candidates.")
    candidates = []
    indexes: set[int] = set()
    for raw in raw_candidates:
        if not isinstance(raw, Mapping) or set(raw) - _CANDIDATE_FIELDS:
            raise _invalid("Membership batch candidate is invalid.")
        index = raw.get("input_index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index in indexes
        ):
            raise _invalid("Membership batch input indexes must be unique and non-negative.")
        indexes.add(index)
        candidate: dict[str, Any] = {
            "input_index": index,
            "employee_id": deepcopy(raw.get("employee_id")),
        }
        if raw.get("expected_name") is not None:
            candidate["expected_name"] = _text(
                raw.get("expected_name"), "expected_name", 256
            )
        candidates.append(candidate)
    return {
        "tenant_id": tenant_id,
        "requester_subject_id": requester,
        "project_id": project_id,
        "member_role": role,
        "candidates": candidates,
    }


def _validate_resolution(
    value: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _OA_RESPONSE_FIELDS:
        raise _unavailable("OA employee batch response is malformed.")
    result = deepcopy(dict(value))
    if (
        result.get("resolution_schema_version")
        != OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION
        or result.get("service_id") != "nex-oa"
        or result.get("tenant_id") != request["tenant_id"]
    ):
        raise _unavailable("OA employee batch authority is unverifiable.")
    items = result.get("results")
    if not isinstance(items, list) or len(items) != len(request["candidates"]):
        raise _unavailable("OA employee batch item set is malformed.")
    normalized_items = [_validate_resolution_item(item) for item in items]
    expected_indexes = [item["input_index"] for item in request["candidates"]]
    if [item["input_index"] for item in normalized_items] != expected_indexes:
        raise _unavailable("OA employee batch item order is unverifiable.")
    resolved_count = sum(item["resolution_status"] == "RESOLVED" for item in items)
    if (
        result.get("requested_count") != len(items)
        or result.get("resolved_count") != resolved_count
        or result.get("rejected_count") != len(items) - resolved_count
    ):
        raise _unavailable("OA employee batch counts are malformed.")
    evidence_payload = {
        "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "tenant_id": request["tenant_id"],
        "results": normalized_items,
    }
    expected_hash = semantic_sha256_hash_ref(evidence_payload)
    if result.get("resolution_evidence_hash") != expected_hash:
        raise _unavailable("OA employee batch evidence integrity failed.")
    result["results"] = normalized_items
    return result


def _validate_resolution_item(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _unavailable("OA employee batch item is malformed.")
    item = deepcopy(dict(value))
    status = item.get("resolution_status")
    if status not in _OA_STATUSES:
        raise _unavailable("OA employee batch status is malformed.")
    index = item.get("input_index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise _unavailable("OA employee batch input index is malformed.")
    if status == "RESOLVED":
        required = {
            "input_index",
            "resolution_status",
            "normalized_employee_id",
            "subject_id",
            "display_name",
            "subject_revision",
            "tenant_membership_revision",
        }
        if set(item) != required:
            raise _unavailable("OA resolved employee projection is malformed.")
        _text(item.get("normalized_employee_id"), "normalized_employee_id", 128)
        _text(item.get("subject_id"), "subject_id", 128)
        _text(item.get("display_name"), "display_name", 256)
        _positive_revision(item.get("subject_revision"))
        _positive_revision(item.get("tenant_membership_revision"))
        return item
    allowed = {"input_index", "resolution_status", "normalized_employee_id"}
    if set(item) - allowed or "subject_id" in item or "display_name" in item:
        raise _unavailable("OA rejected employee projection leaks authority.")
    if "normalized_employee_id" in item:
        _text(item["normalized_employee_id"], "normalized_employee_id", 128)
    return item


def _rejected_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "input_index": value["input_index"],
        "outcome_code": value["resolution_status"],
    }
    if value.get("normalized_employee_id") is not None:
        result["normalized_employee_id"] = value["normalized_employee_id"]
    return result


def _approval_record(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_data = getattr(value, "to_data", None)
    if callable(to_data):
        raw = to_data()
        if isinstance(raw, Mapping):
            return dict(raw)
    raise _invalid("ApprovalRequest is invalid.")


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise _unavailable("OA employee batch response is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise _unavailable("OA employee batch response is not an object.")
    return value


def _positive_revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _unavailable("OA employee authority revision is malformed.")
    return value


def _positive_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("OA employee batch timeout must be numeric.") from exc
    if parsed <= 0:
        raise ValueError("OA employee batch timeout must be positive.")
    return parsed


def _trace_id_value(value: object) -> str:
    if not isinstance(value, str) or _TRACE_ID.fullmatch(value) is None:
        raise _invalid("trace_id must contain 32 lowercase hexadecimal characters.")
    return value


def _text(value: object, field_name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > limit
    ):
        raise _invalid(f"{field_name} must be bounded non-empty text.")
    return value


def _invalid(detail: str) -> ProjectMembershipBatchError:
    return ProjectMembershipBatchError(
        status_code=400,
        error_code="ae.project_membership_batch_invalid",
        detail=detail,
    )


def _unavailable(
    detail: str,
    *,
    status_code: int = 503,
    error_code: str = "ae.project_membership_batch_authority_unavailable",
) -> ProjectMembershipBatchError:
    return ProjectMembershipBatchError(
        status_code=status_code,
        error_code=error_code,
        detail=detail,
        retryable=True,
    )
