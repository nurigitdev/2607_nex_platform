from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .project_memberships import EosProjectMembershipError
from .projects import EosProjectError

EOS_PROJECT_VERIFICATION_SCHEMA_VERSION = "eos_project_verification.v1"
EOS_MEMBERSHIP_VERIFICATION_SCHEMA_VERSION = (
    "eos_project_membership_verification.v1"
)
EOS_PROJECT_VERIFY_SCOPE = "project:verify"
MAX_PROJECT_VERIFY_BATCH_SIZE = 50
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")


class ProjectVerificationRepository(Protocol):
    def get_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        ...

    def find_project_tenants(
        self,
        *,
        project_id: str,
        limit: int = 2,
    ) -> tuple[str, ...]:
        ...


class MembershipVerificationRepository(Protocol):
    def get_subject_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class EosWaVerificationError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class EosWaProjectVerifier:
    projects: ProjectVerificationRepository
    memberships: MembershipVerificationRepository

    def verify_projects(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id, project_ids = _normalize_project_request(payload)
        results = [
            self._verify_project(tenant_id=tenant_id, project_id=project_id)
            for project_id in project_ids
        ]
        evidence = {
            "schema_version": EOS_PROJECT_VERIFICATION_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "results": results,
        }
        return {
            "verification_schema_version": EOS_PROJECT_VERIFICATION_SCHEMA_VERSION,
            "service_id": "nex-eos",
            "tenant_id": tenant_id,
            "requested_count": len(results),
            "verified_count": sum(
                item["verification_status"] == "VERIFIED" for item in results
            ),
            "rejected_count": sum(
                item["verification_status"] != "VERIFIED" for item in results
            ),
            "results": results,
            "verification_evidence_hash": semantic_sha256_hash_ref(evidence),
        }

    def verify_membership_at(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id, project_id, subject_id, occurred_at = (
            _normalize_membership_request(payload)
        )
        project = self._get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            status = (
                "TENANT_MISMATCH"
                if self._find_project_tenants(project_id)
                else "PROJECT_NOT_FOUND"
            )
            return self._membership_result(
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=subject_id,
                occurred_at=occurred_at,
                status=status,
            )
        if project.get("status") != "ACTIVE":
            return self._membership_result(
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=subject_id,
                occurred_at=occurred_at,
                status="PROJECT_INACTIVE",
                project_version=_positive_int(project.get("version"), "project version"),
            )
        membership = self._get_membership(
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
        )
        if membership is None:
            return self._membership_result(
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=subject_id,
                occurred_at=occurred_at,
                status="MEMBERSHIP_NOT_FOUND",
            )
        valid_from = _aware_datetime(membership.get("valid_from"), "valid_from")
        valid_to = _optional_aware_datetime(membership.get("valid_to"), "valid_to")
        if occurred_at < valid_from:
            status = "MEMBERSHIP_NOT_YET_VALID"
        elif valid_to is not None and occurred_at >= valid_to:
            status = "MEMBERSHIP_EXPIRED"
        else:
            status = "VERIFIED"
        return self._membership_result(
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
            occurred_at=occurred_at,
            status=status,
            project_membership_id=_uuid_text(
                membership.get("project_membership_id"),
                "project_membership_id",
            ),
            member_role=_required_text(membership.get("member_role"), "member_role"),
            version=_positive_int(membership.get("version"), "membership version"),
            valid_from=_wire_datetime(valid_from),
            valid_to=_wire_datetime(valid_to) if valid_to is not None else None,
        )

    def _verify_project(self, *, tenant_id: str, project_id: str) -> dict[str, Any]:
        project = self._get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            status = (
                "TENANT_MISMATCH"
                if self._find_project_tenants(project_id)
                else "PROJECT_NOT_FOUND"
            )
            return {"project_id": project_id, "verification_status": status}
        version = _positive_int(project.get("version"), "project version")
        status = "VERIFIED" if project.get("status") == "ACTIVE" else "PROJECT_INACTIVE"
        return {
            "project_id": project_id,
            "verification_status": status,
            "project_version": version,
        }

    def _get_project(self, *, tenant_id: str, project_id: str) -> dict[str, Any] | None:
        try:
            return self.projects.get_project(
                tenant_id=tenant_id,
                project_id=project_id,
            )
        except EosProjectError as exc:
            raise _dependency_error(exc) from exc

    def _find_project_tenants(self, project_id: str) -> tuple[str, ...]:
        try:
            return self.projects.find_project_tenants(project_id=project_id, limit=2)
        except EosProjectError as exc:
            raise _dependency_error(exc) from exc

    def _get_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        try:
            return self.memberships.get_subject_membership(
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=subject_id,
            )
        except EosProjectMembershipError as exc:
            raise _dependency_error(exc) from exc

    @staticmethod
    def _membership_result(
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        occurred_at: datetime,
        status: str,
        **evidence: Any,
    ) -> dict[str, Any]:
        body = {
            "verification_schema_version": (
                EOS_MEMBERSHIP_VERIFICATION_SCHEMA_VERSION
            ),
            "service_id": "nex-eos",
            "tenant_id": tenant_id,
            "project_id": project_id,
            "subject_id": subject_id,
            "occurred_at": _wire_datetime(occurred_at),
            "membership_valid": status == "VERIFIED",
            "verification_status": status,
            **evidence,
        }
        return {
            **body,
            "verification_evidence_hash": semantic_sha256_hash_ref(body),
        }


def register_wa_project_verification_routes(
    app: FastAPI,
    *,
    verifier: EosWaProjectVerifier | None,
) -> None:
    @app.post("/internal/v1/projects:verify-batch", response_model=None)
    def verify_projects(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        admitted = _authorize(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        unavailable = _require_verifier(request, verifier)
        if unavailable is not None:
            return unavailable
        assert verifier is not None
        try:
            result = verifier.verify_projects(payload)
        except EosWaVerificationError as exc:
            return _problem(request, exc)
        return _with_context(request, result)

    @app.post("/internal/v1/project-memberships:verify-at", response_model=None)
    def verify_membership_at(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        admitted = _authorize(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        unavailable = _require_verifier(request, verifier)
        if unavailable is not None:
            return unavailable
        assert verifier is not None
        try:
            result = verifier.verify_membership_at(payload)
        except EosWaVerificationError as exc:
            return _problem(request, exc)
        return _with_context(request, result)


def _authorize(
    request: Request,
    authorization: str | None,
) -> Any:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE, EOS_PROJECT_VERIFY_SCOPE),
        route_class="READ",
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if admitted.service_id != "nex-wa":
        return problem_response(
            request,
            status_code=403,
            error_code="EOS_PROJECT_VERIFY_CALLER_DENIED",
            title="EOS project verification caller denied",
            detail="Only nex-wa may verify Project attribution.",
            retryable=False,
        )
    return admitted


def _require_verifier(
    request: Request,
    verifier: EosWaProjectVerifier | None,
) -> JSONResponse | None:
    if verifier is not None:
        return None
    return problem_response(
        request,
        status_code=503,
        error_code="EOS_PROJECT_VERIFICATION_UNAVAILABLE",
        title="EOS project verification unavailable",
        detail="EOS project verification dependencies are not configured.",
        retryable=True,
    )


def _normalize_project_request(
    payload: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]]:
    _require_fields(payload, {"tenant_id", "project_ids"})
    tenant_id = _scoped_id("tenant_id", payload.get("tenant_id"))
    raw_ids = payload.get("project_ids")
    if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
        raise _invalid("project_ids must be an array")
    if not 1 <= len(raw_ids) <= MAX_PROJECT_VERIFY_BATCH_SIZE:
        raise _invalid("project_ids must contain between 1 and 50 items")
    project_ids = tuple(_uuid_text(item, "project_id") for item in raw_ids)
    if len(set(project_ids)) != len(project_ids):
        raise _invalid("project_ids must contain unique values")
    return tenant_id, project_ids


def _normalize_membership_request(
    payload: Mapping[str, Any],
) -> tuple[str, str, str, datetime]:
    _require_fields(payload, {"tenant_id", "project_id", "subject_id", "occurred_at"})
    return (
        _scoped_id("tenant_id", payload.get("tenant_id")),
        _uuid_text(payload.get("project_id"), "project_id"),
        _scoped_id("subject_id", payload.get("subject_id")),
        _aware_datetime(payload.get("occurred_at"), "occurred_at"),
    )


def _require_fields(payload: Mapping[str, Any], expected: set[str]) -> None:
    if not isinstance(payload, Mapping):
        raise _invalid("request must be an object")
    if set(payload) != expected:
        raise _invalid(f"request fields must be exactly: {sorted(expected)}")


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field_name} is invalid")
    return value


def _uuid_text(value: object, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid(f"{field_name} must be an RFC3339 timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _optional_aware_datetime(value: object, field_name: str) -> datetime | None:
    return None if value is None else _aware_datetime(value, field_name)


def _wire_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _unavailable(f"{field_name} is malformed")
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _unavailable(f"{field_name} is malformed")
    return value.strip()


def _invalid(detail: str) -> EosWaVerificationError:
    return EosWaVerificationError(400, "EOS_PROJECT_VERIFY_INVALID", detail)


def _unavailable(detail: str) -> EosWaVerificationError:
    return EosWaVerificationError(
        503,
        "EOS_PROJECT_VERIFICATION_UNAVAILABLE",
        detail,
        True,
    )


def _dependency_error(exc: Exception) -> EosWaVerificationError:
    return _unavailable(f"EOS Project authority is unavailable: {type(exc).__name__}")


def _problem(request: Request, exc: EosWaVerificationError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS project verification failed",
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _with_context(request: Request, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }
