from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_oa.credentials import (
    OaCredentialError,
    OaCredentialRegistry,
    normalize_employee_id,
)
from nex_oa.memberships import OaMembershipError, OaTenantMembershipRegistry
from nex_oa.service_auth import authorize_oa_service_request
from nex_oa.subjects import normalize_registry_id

OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION = "oa_employee_batch_resolution.v1"
OA_EMPLOYEE_BATCH_RESOLVE_SCOPE = "identity:employee:resolve"
MAX_EMPLOYEE_BATCH_SIZE = 50
EMPLOYEE_RESOLUTION_STATUSES = frozenset(
    {
        "RESOLVED",
        "INVALID_EMPLOYEE_ID",
        "EMPLOYEE_NOT_FOUND",
        "SUBJECT_INACTIVE",
        "NAME_MISMATCH",
        "DUPLICATE_INPUT",
    }
)
_REQUEST_FIELDS = frozenset({"tenant_id", "candidates"})
_CANDIDATE_FIELDS = frozenset({"input_index", "employee_id", "expected_name"})
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class OaEmployeeBatchResolutionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class OaEmployeeBatchResolver:
    credential_registry: OaCredentialRegistry
    membership_registry: OaTenantMembershipRegistry

    def resolve(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id, candidates = _normalize_request(payload)
        seen: set[str] = set()
        results = [
            self._resolve_candidate(
                tenant_id=tenant_id,
                candidate=candidate,
                seen=seen,
            )
            for candidate in candidates
        ]
        evidence_payload = {
            "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "results": results,
        }
        return {
            "resolution_schema_version": (
                OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION
            ),
            "service_id": "nex-oa",
            "tenant_id": tenant_id,
            "requested_count": len(results),
            "resolved_count": sum(
                item["resolution_status"] == "RESOLVED" for item in results
            ),
            "rejected_count": sum(
                item["resolution_status"] != "RESOLVED" for item in results
            ),
            "results": results,
            "resolution_evidence_hash": semantic_sha256_hash_ref(evidence_payload),
        }

    def _resolve_candidate(
        self,
        *,
        tenant_id: str,
        candidate: Mapping[str, Any],
        seen: set[str],
    ) -> dict[str, Any]:
        input_index = int(candidate["input_index"])
        try:
            normalized_employee_id = normalize_employee_id(
                candidate.get("employee_id")
            )
        except OaCredentialError:
            return _item(input_index, "INVALID_EMPLOYEE_ID")
        if normalized_employee_id in seen:
            return _item(
                input_index,
                "DUPLICATE_INPUT",
                normalized_employee_id=normalized_employee_id,
            )
        seen.add(normalized_employee_id)

        try:
            credential = self.credential_registry.get_credential(
                tenant_id=tenant_id,
                employee_id=normalized_employee_id,
            )
        except OaCredentialError as exc:
            raise _dependency_error(exc) from exc
        if credential is None:
            return _item(
                input_index,
                "EMPLOYEE_NOT_FOUND",
                normalized_employee_id=normalized_employee_id,
            )

        subject_ref = _mapping(credential.get("subject_ref"), "subject_ref")
        subject_id = _required_text(subject_ref.get("id"), "subject_ref.id")
        subject_snapshot = _mapping(
            credential.get("subject_registry_snapshot"),
            "subject_registry_snapshot",
        )
        subject = _mapping(subject_snapshot.get("subject"), "subject")
        try:
            membership = self.membership_registry.get_membership(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except OaMembershipError as exc:
            raise _dependency_error(exc) from exc
        if membership is None:
            return _item(
                input_index,
                "EMPLOYEE_NOT_FOUND",
                normalized_employee_id=normalized_employee_id,
            )
        membership_record = _mapping(membership.get("membership"), "membership")
        if (
            subject.get("status") != "ACTIVE"
            or membership_record.get("status") != "ACTIVE"
        ):
            return _item(
                input_index,
                "SUBJECT_INACTIVE",
                normalized_employee_id=normalized_employee_id,
            )

        display_name = _required_text(subject.get("display_name"), "display_name")
        expected_name = candidate.get("expected_name")
        if expected_name is not None and _normalized_name(expected_name) != (
            _normalized_name(display_name)
        ):
            return _item(
                input_index,
                "NAME_MISMATCH",
                normalized_employee_id=normalized_employee_id,
            )
        return _item(
            input_index,
            "RESOLVED",
            normalized_employee_id=normalized_employee_id,
            subject_id=subject_id,
            display_name=display_name,
            subject_revision=_positive_revision(subject.get("revision"), "subject"),
            tenant_membership_revision=_positive_revision(
                membership_record.get("revision"),
                "tenant membership",
            ),
        )


def register_employee_batch_resolution_routes(
    app: FastAPI,
    *,
    resolver: OaEmployeeBatchResolver,
) -> None:
    @app.post("/internal/v1/identity/employees:resolve-batch", response_model=None)
    def resolve_employee_batch(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = authorize_oa_service_request(
            request,
            authorization,
            required_scopes=(
                DEFAULT_SERVICE_SCOPE,
                OA_EMPLOYEE_BATCH_RESOLVE_SCOPE,
            ),
            route_class="READ",
        )
        if auth_problem is not None:
            return auth_problem
        try:
            result = resolver.resolve(payload)
        except OaEmployeeBatchResolutionError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="OA employee batch resolution failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "oa-employee-batch-resolution-failed"
                ),
            )
        return {
            **result,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }


def _normalize_request(
    payload: Mapping[str, Any],
) -> tuple[str, tuple[Mapping[str, Any], ...]]:
    if not isinstance(payload, Mapping):
        raise _invalid("request must be an object")
    unexpected = sorted(set(payload) - _REQUEST_FIELDS)
    if unexpected:
        raise _invalid(f"request contains unsupported fields: {unexpected}")
    try:
        tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    except Exception as exc:
        raise _invalid("tenant_id is invalid") from exc
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates, (str, bytes)
    ):
        raise _invalid("candidates must be an array")
    if not 1 <= len(raw_candidates) <= MAX_EMPLOYEE_BATCH_SIZE:
        raise _invalid("candidates must contain between 1 and 50 items")

    candidates: list[Mapping[str, Any]] = []
    indexes: set[int] = set()
    for candidate in raw_candidates:
        if not isinstance(candidate, Mapping):
            raise _invalid("each candidate must be an object")
        unexpected = sorted(set(candidate) - _CANDIDATE_FIELDS)
        if unexpected:
            raise _invalid(f"candidate contains unsupported fields: {unexpected}")
        input_index = candidate.get("input_index")
        if (
            not isinstance(input_index, int)
            or isinstance(input_index, bool)
            or input_index < 0
            or input_index in indexes
        ):
            raise _invalid("candidate input_index must be a unique non-negative integer")
        indexes.add(input_index)
        candidates.append(candidate)
    return tenant_id, tuple(candidates)


def _item(
    input_index: int,
    status: str,
    **values: Any,
) -> dict[str, Any]:
    if status not in EMPLOYEE_RESOLUTION_STATUSES:
        raise ValueError(f"unknown employee resolution status: {status}")
    return {
        "input_index": input_index,
        "resolution_status": status,
        **values,
    }


def _normalized_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", value).strip()).casefold()


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _unavailable(f"OA {field_name} projection is malformed")
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _unavailable(f"OA {field_name} projection is malformed")
    return value.strip()


def _positive_revision(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _unavailable(f"OA {field_name} revision is malformed")
    return value


def _invalid(detail: str) -> OaEmployeeBatchResolutionError:
    return OaEmployeeBatchResolutionError(
        status_code=400,
        error_code="oa.employee_batch_request_invalid",
        detail=detail,
    )


def _unavailable(detail: str) -> OaEmployeeBatchResolutionError:
    return OaEmployeeBatchResolutionError(
        status_code=503,
        error_code="oa.employee_batch_resolution_unavailable",
        detail=detail,
        retryable=True,
    )


def _dependency_error(exc: Exception) -> OaEmployeeBatchResolutionError:
    return _unavailable(f"OA employee authority is unavailable: {type(exc).__name__}")
