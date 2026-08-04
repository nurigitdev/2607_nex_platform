from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_runtime.retrieval_policies import (
    RetrievalPolicyError,
    active_retrieval_policy_record,
    list_retrieval_policy_records,
    retrieval_policy_by_id,
)


def register_retrieval_policy_routes(
    app: FastAPI,
    *,
    policies: tuple[dict[str, Any], ...] | None = None,
) -> None:
    configured_policies = policies

    @app.get("/admin/v1/policies/retrieval", response_model=None)
    def list_retrieval_policies(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            records = _list_policy_records(configured_policies)
            active = _active_policy_record(configured_policies)
        except RetrievalPolicyError as exc:
            return _retrieval_policy_problem_response(request, exc)
        return {
            "projection_schema_version": "ag_retrieval_policy_registry.v1",
            "trace_id": trace_id_from_headers(request),
            "active_policy_id": active["policy_id"],
            "active_policy_version": active["version"],
            "policies": records,
            "summary": summarize_retrieval_policies(records),
        }

    @app.get("/admin/v1/policies/retrieval/active", response_model=None)
    def get_active_retrieval_policy(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            policy = _active_policy_record(configured_policies)
        except RetrievalPolicyError as exc:
            return _retrieval_policy_problem_response(request, exc)
        return {
            "projection_schema_version": "ag_retrieval_policy_detail.v1",
            "trace_id": trace_id_from_headers(request),
            "policy": policy,
        }

    @app.get("/admin/v1/policies/retrieval/{policy_id}", response_model=None)
    def get_retrieval_policy(
        policy_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            policy = _policy_by_id(policy_id, configured_policies)
        except RetrievalPolicyError as exc:
            return _retrieval_policy_problem_response(request, exc)
        return {
            "projection_schema_version": "ag_retrieval_policy_detail.v1",
            "trace_id": trace_id_from_headers(request),
            "policy": policy,
        }


def summarize_retrieval_policies(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(records),
        "active": sum(1 for record in records if record["status"] == "ACTIVE"),
        "candidate": sum(1 for record in records if record["status"] == "CANDIDATE"),
        "retired": sum(1 for record in records if record["status"] == "RETIRED"),
    }


def _list_policy_records(
    policies: tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    if policies is None:
        return list_retrieval_policy_records()
    return list_retrieval_policy_records(policies)


def _active_policy_record(
    policies: tuple[dict[str, Any], ...] | None,
) -> dict[str, Any]:
    if policies is None:
        return active_retrieval_policy_record()
    return active_retrieval_policy_record(policies)


def _policy_by_id(
    policy_id: str,
    policies: tuple[dict[str, Any], ...] | None,
) -> dict[str, Any]:
    if policies is None:
        return retrieval_policy_by_id(policy_id)
    return retrieval_policy_by_id(policy_id, policies)


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


def _retrieval_policy_problem_response(
    request: Request,
    exc: RetrievalPolicyError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Retrieval policy request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/retrieval-policy-failed",
    )
