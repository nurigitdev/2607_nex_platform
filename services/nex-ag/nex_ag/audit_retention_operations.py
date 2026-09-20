from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_ag.audit_retention import (
    AgAuditRetentionPolicyError,
    AgRetentionCandidateError,
    InMemoryAgRetentionCandidateStore,
    SqlAlchemyAgRetentionCandidateStore,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import (
    ALLOWED_ARCHIVE_STATUSES,
    AgArchiveReceiptError,
    InMemoryAgArchiveReceiptStore,
    SqlAlchemyAgArchiveReceiptStore,
)
from nex_ag.audit_retention_purge import (
    AgRetentionPurgeError,
    InMemoryAgRetentionPurgeStore,
    SqlAlchemyAgRetentionPurgeStore,
    execute_ag_retention_purge,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    problem_response,
    validate_authorization_header,
    validate_user_authorization_header,
)


AG_AUDIT_RETENTION_OPERATIONS_PATH = "/admin/v1/operations/audit-retention"
AG_AUDIT_RETENTION_PURGE_PATH = (
    "/admin/v1/operations/audit-retention/purge"
)
AG_AUDIT_RETENTION_OPERATIONS_SCHEMA_VERSION = (
    "ag_audit_retention_operations_projection.v1"
)
_PURGE_FIELDS = {"source_kind", "source_id", "as_of", "mode", "confirmation"}


def build_ag_audit_retention_runtime_stores(runtime: Any) -> dict[str, Any]:
    session_factory = getattr(runtime, "api_session_factory", None)
    if session_factory is None:
        receipt_store = InMemoryAgArchiveReceiptStore()
        return {
            "candidate_store": InMemoryAgRetentionCandidateStore(),
            "receipt_store": receipt_store,
            "purge_store": InMemoryAgRetentionPurgeStore(
                receipt_store=receipt_store
            ),
        }
    receipt_store = SqlAlchemyAgArchiveReceiptStore(session_factory)
    return {
        "candidate_store": SqlAlchemyAgRetentionCandidateStore(session_factory),
        "receipt_store": receipt_store,
        "purge_store": SqlAlchemyAgRetentionPurgeStore(session_factory),
    }


def build_ag_audit_retention_operations_projection(
    *,
    policy: Mapping[str, Any],
    candidate_store: Any,
    receipt_store: Any,
    as_of: str,
    limit: int = 100,
) -> dict[str, Any]:
    candidate_page = candidate_store.list_candidates(
        policy=policy,
        as_of=as_of,
        limit=limit,
    )
    receipts = receipt_store.list_receipts(limit=min(limit, 500))
    status_counts = {status: 0 for status in sorted(ALLOWED_ARCHIVE_STATUSES)}
    purge_ready_count = 0
    as_of_dt = _parse_timestamp(as_of)
    for receipt in receipts:
        status = receipt.get("archive_status")
        if status in status_counts:
            status_counts[status] += 1
        purge_after = receipt.get("purge_after")
        if (
            status == "SEALED"
            and purge_after is not None
            and _parse_timestamp(purge_after) <= as_of_dt
        ):
            purge_ready_count += 1
    attention_reasons: list[str] = []
    if candidate_page["candidate_count"] > 0:
        attention_reasons.append("UNARCHIVED_RETENTION_CANDIDATES")
    if candidate_page["invalid_record_count"] > 0:
        attention_reasons.append("INVALID_SOURCE_ROWS")
    if status_counts["FAILED"] > 0:
        attention_reasons.append("ARCHIVE_FAILURES")
    if purge_ready_count > 0:
        attention_reasons.append("PURGE_READY_RECEIPTS")
    return {
        "projection_schema_version": (
            AG_AUDIT_RETENTION_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": "ATTENTION" if attention_reasons else "READY",
        "service_id": "nex-ag",
        "policy": {
            "policy_id": policy["policy_id"],
            "sources": [
                {
                    "source_kind": item["source_kind"],
                    "retention_days": item["retention_days"],
                }
                for item in policy["sources"]
            ],
            "archive_provider_mode": policy["archive"]["provider_mode"],
            "archive_grace_days": policy["archive"]["grace_days"],
            "execute_enabled": policy["purge"]["execute_enabled"],
            "dry_run_default": policy["purge"]["dry_run_default"],
        },
        "checked_at": candidate_page["as_of"],
        "candidates": candidate_page,
        "receipts": {
            "returned_count": len(receipts),
            "status_counts": status_counts,
            "purge_ready_count": purge_ready_count,
            "recent": [_receipt_projection(item) for item in receipts],
        },
        "attention_reasons": attention_reasons,
        "privacy": {
            "raw_payload_included": False,
            "object_reference_included": False,
            "credentials_included": False,
            "confirmation_included": False,
        },
    }


def register_ag_audit_retention_routes(
    app: FastAPI,
    *,
    candidate_store: Any,
    receipt_store: Any,
    purge_store: Any,
    policy: Mapping[str, Any] | None = None,
) -> None:
    selected_policy = dict(policy or build_ag_audit_retention_policy())

    @app.get(AG_AUDIT_RETENTION_OPERATIONS_PATH, response_model=None)
    def get_ag_audit_retention_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        as_of: str | None = None,
        limit: int = 100,
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return build_ag_audit_retention_operations_projection(
                policy=selected_policy,
                candidate_store=candidate_store,
                receipt_store=receipt_store,
                as_of=as_of or _utc_now(),
                limit=limit,
            )
        except (
            AgArchiveReceiptError,
            AgAuditRetentionPolicyError,
            AgRetentionCandidateError,
            AgRetentionPurgeError,
        ) as exc:
            return _problem_response(request, exc)

    @app.post(AG_AUDIT_RETENTION_PURGE_PATH, response_model=None)
    def purge_ag_audit_retention_source(
        request: Request,
        authorization: str | None = Header(default=None),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            normalized = _purge_payload(payload)
            return execute_ag_retention_purge(
                store=purge_store,
                policy=selected_policy,
                **normalized,
            )
        except (AgRetentionPurgeError, AgArchiveReceiptError) as exc:
            return _problem_response(request, exc)


def _receipt_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "archive_id": receipt.get("archive_id"),
        "source_kind": receipt.get("source_kind"),
        "source_id": receipt.get("source_id"),
        "archive_provider_mode": receipt.get("archive_provider_mode"),
        "archive_status": receipt.get("archive_status"),
        "archived_at": receipt.get("archived_at"),
        "purge_after": receipt.get("purge_after"),
        "purged_at": receipt.get("purged_at"),
    }


def _purge_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - _PURGE_FIELDS)
    if unknown:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_fields_unsupported",
            detail=f"Unsupported purge fields: {', '.join(unknown)}",
        )
    return {
        "source_kind": payload.get("source_kind"),
        "source_id": payload.get("source_id"),
        "as_of": payload.get("as_of") or _utc_now(),
        "mode": payload.get("mode") or "DRY_RUN",
        "confirmation": payload.get("confirmation"),
    }


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgRetentionPurgeError(
                error_code="ag.retention.operations_timestamp_invalid",
                detail="Operations timestamp must be ISO-8601.",
            ) from exc
    else:
        raise AgRetentionPurgeError(
            error_code="ag.retention.operations_timestamp_invalid",
            detail="Operations timestamp must be ISO-8601.",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgRetentionPurgeError(
            error_code="ag.retention.operations_timestamp_timezone_required",
            detail="Operations timestamp must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _authorize_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    service_result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if service_result.ok:
        return None
    user_result = validate_user_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_USER_SCOPE],
    )
    if user_result.ok:
        roles = set(user_result.claims.roles if user_result.claims else ())
        if "admin" in roles:
            return None
        return problem_response(
            request,
            status_code=403,
            error_code="AG_AUDIT_RETENTION_ADMIN_ROLE_REQUIRED",
            title="Authorization failed",
            detail="AG audit retention routes require an admin user role.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    return problem_response(
        request,
        status_code=401,
        error_code=service_result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=service_result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _problem_response(request: Request, exc: Any) -> JSONResponse:
    return problem_response(
        request,
        status_code=getattr(exc, "status_code", 422),
        error_code=exc.error_code,
        title="Audit retention request rejected",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/audit-retention-rejected",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "AG_AUDIT_RETENTION_OPERATIONS_PATH",
    "AG_AUDIT_RETENTION_OPERATIONS_SCHEMA_VERSION",
    "AG_AUDIT_RETENTION_PURGE_PATH",
    "build_ag_audit_retention_operations_projection",
    "build_ag_audit_retention_runtime_stores",
    "register_ag_audit_retention_routes",
]
