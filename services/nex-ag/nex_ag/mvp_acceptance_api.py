from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_ag.mvp_acceptance import (
    build_ag_mvp_acceptance_policy,
    build_ag_mvp_evidence_inventory,
)
from nex_ag.mvp_acceptance_evaluation import evaluate_ag_mvp_acceptance
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    problem_response,
    trace_id_from_headers,
    validate_authorization_header,
    validate_user_authorization_header,
)


AG_MVP_ACCEPTANCE_OPERATIONS_PATH = "/admin/v1/operations/mvp-acceptance"


class AgMvpAcceptanceEvidenceProvider(Protocol):
    def collect(self, *, observed_at: datetime) -> Mapping[str, Any]:
        ...


class RepositoryAgMvpAcceptanceEvidenceProvider:
    def collect(self, *, observed_at: datetime) -> Mapping[str, Any]:
        inventory = build_ag_mvp_evidence_inventory()
        return {
            "ag_requirement_closures": {
                "status": inventory["status"],
                "observed_at": _timestamp(observed_at),
                "requirement_count": inventory["scope"][
                    "included_requirement_count"
                ],
                "issue_count": len(inventory["issues"]),
            }
        }


def register_ag_mvp_acceptance_routes(
    app: FastAPI,
    *,
    evidence_provider: AgMvpAcceptanceEvidenceProvider | None = None,
    policy: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_provider = (
        evidence_provider or RepositoryAgMvpAcceptanceEvidenceProvider()
    )
    selected_policy = dict(policy or build_ag_mvp_acceptance_policy())
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(AG_MVP_ACCEPTANCE_OPERATIONS_PATH, response_model=None)
    def get_ag_mvp_acceptance(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        observed_at = selected_clock()
        source_status = "COLLECTED"
        try:
            evidence = selected_provider.collect(observed_at=observed_at)
        except Exception:
            evidence = {}
            source_status = "UNAVAILABLE"
        report = evaluate_ag_mvp_acceptance(
            evidence,
            policy=selected_policy,
            now=observed_at,
        )
        return {
            **report,
            "request_trace_id": trace_id_from_headers(request),
            "evidence_source_status": source_status,
            "server_selected": True,
        }


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
            error_code="AG_MVP_ACCEPTANCE_ADMIN_ROLE_REQUIRED",
            title="Authorization failed",
            detail="AG MVP acceptance routes require an admin user role.",
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


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
