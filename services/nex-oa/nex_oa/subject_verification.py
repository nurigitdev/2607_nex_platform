from __future__ import annotations

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

from nex_oa.memberships import OaMembershipError, OaTenantMembershipRegistry
from nex_oa.service_auth import (
    authenticated_oa_service_claims,
    authorize_oa_service_request,
)
from nex_oa.subjects import (
    OaSubjectRegistry,
    SubjectRegistryError,
    normalize_registry_id,
)

OA_SUBJECT_VERIFICATION_SCHEMA_VERSION = "oa_subject_verification.v1"
OA_SUBJECT_VERIFY_SCOPE = "identity:subject:verify"
MAX_SUBJECT_VERIFY_BATCH_SIZE = 50
SUBJECT_VERIFICATION_STATUSES = frozenset(
    {
        "VERIFIED",
        "SUBJECT_NOT_FOUND",
        "SUBJECT_INACTIVE",
        "TENANT_MEMBERSHIP_MISSING",
    }
)
_REQUEST_FIELDS = frozenset({"tenant_id", "subject_ids"})


@dataclass(frozen=True)
class OaSubjectVerificationError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class OaHumanSubjectVerifier:
    subject_registry: OaSubjectRegistry
    membership_registry: OaTenantMembershipRegistry

    def verify_batch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id, subject_ids = _normalize_request(payload)
        results = [
            self._verify_subject(tenant_id=tenant_id, subject_id=subject_id)
            for subject_id in subject_ids
        ]
        evidence = {
            "schema_version": OA_SUBJECT_VERIFICATION_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "results": results,
        }
        return {
            "verification_schema_version": OA_SUBJECT_VERIFICATION_SCHEMA_VERSION,
            "service_id": "nex-oa",
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

    def _verify_subject(self, *, tenant_id: str, subject_id: str) -> dict[str, Any]:
        try:
            snapshot = self.subject_registry.get_subject(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except SubjectRegistryError as exc:
            raise _dependency_error(exc) from exc
        if snapshot is None:
            return _item(subject_id, "SUBJECT_NOT_FOUND")

        subject = _mapping(snapshot.get("subject"), "subject")
        subject_revision = _positive_revision(subject.get("revision"), "subject")
        if subject.get("status") != "ACTIVE":
            return _item(
                subject_id,
                "SUBJECT_INACTIVE",
                subject_revision=subject_revision,
            )

        try:
            membership_snapshot = self.membership_registry.get_membership(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except OaMembershipError as exc:
            raise _dependency_error(exc) from exc
        if membership_snapshot is None:
            return _item(
                subject_id,
                "TENANT_MEMBERSHIP_MISSING",
                subject_revision=subject_revision,
            )
        membership = _mapping(membership_snapshot.get("membership"), "membership")
        if membership.get("status") != "ACTIVE":
            return _item(
                subject_id,
                "TENANT_MEMBERSHIP_MISSING",
                subject_revision=subject_revision,
            )
        return _item(
            subject_id,
            "VERIFIED",
            subject_revision=subject_revision,
            tenant_membership_revision=_positive_revision(
                membership.get("revision"),
                "tenant membership",
            ),
        )


def register_subject_verification_routes(
    app: FastAPI,
    *,
    verifier: OaHumanSubjectVerifier,
) -> None:
    @app.post("/internal/v1/identity/subjects:verify-batch", response_model=None)
    def verify_subject_batch(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = authorize_oa_service_request(
            request,
            authorization,
            required_scopes=(DEFAULT_SERVICE_SCOPE, OA_SUBJECT_VERIFY_SCOPE),
            route_class="READ",
        )
        if auth_problem is not None:
            return auth_problem
        if authenticated_oa_service_claims(request).service_id != "nex-wa":
            return problem_response(
                request,
                status_code=403,
                error_code="OA_SUBJECT_VERIFY_CALLER_FORBIDDEN",
                title="Authorization failed",
                detail="OA subject verification is available only to NeX-WA.",
                type_uri=(
                    "https://nex-platform.local/problems/authorization-failed"
                ),
            )
        try:
            result = verifier.verify_batch(payload)
        except OaSubjectVerificationError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="OA subject verification failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "oa-subject-verification-failed"
                ),
            )
        return {
            **result,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }


def _normalize_request(payload: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        raise _invalid("request must be an object")
    unexpected = sorted(set(payload) - _REQUEST_FIELDS)
    if unexpected:
        raise _invalid(f"request contains unsupported fields: {unexpected}")
    try:
        tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    except Exception as exc:
        raise _invalid("tenant_id is invalid") from exc
    raw_subject_ids = payload.get("subject_ids")
    if not isinstance(raw_subject_ids, Sequence) or isinstance(
        raw_subject_ids, (str, bytes)
    ):
        raise _invalid("subject_ids must be an array")
    if not 1 <= len(raw_subject_ids) <= MAX_SUBJECT_VERIFY_BATCH_SIZE:
        raise _invalid("subject_ids must contain between 1 and 50 items")
    subject_ids: list[str] = []
    try:
        for raw_subject_id in raw_subject_ids:
            subject_ids.append(
                normalize_registry_id(raw_subject_id, field_name="subject_id")
            )
    except Exception as exc:
        raise _invalid("subject_ids contains an invalid subject identifier") from exc
    if len(set(subject_ids)) != len(subject_ids):
        raise _invalid("subject_ids must contain unique values")
    return tenant_id, tuple(subject_ids)


def _item(subject_id: str, status: str, **values: Any) -> dict[str, Any]:
    if status not in SUBJECT_VERIFICATION_STATUSES:
        raise ValueError(f"unknown subject verification status: {status}")
    return {"subject_id": subject_id, "verification_status": status, **values}


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _unavailable(f"OA {field_name} projection is malformed")
    return value


def _positive_revision(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _unavailable(f"OA {field_name} revision is malformed")
    return value


def _invalid(detail: str) -> OaSubjectVerificationError:
    return OaSubjectVerificationError(
        status_code=400,
        error_code="oa.subject_verification_request_invalid",
        detail=detail,
    )


def _unavailable(detail: str) -> OaSubjectVerificationError:
    return OaSubjectVerificationError(
        status_code=503,
        error_code="oa.subject_verification_unavailable",
        detail=detail,
        retryable=True,
    )


def _dependency_error(exc: Exception) -> OaSubjectVerificationError:
    return _unavailable(f"OA identity authority is unavailable: {type(exc).__name__}")
