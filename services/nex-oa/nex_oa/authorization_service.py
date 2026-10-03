from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import OaAuthorizationRepository
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.memberships import OaMembershipError, OaTenantMembershipRegistry
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_AUTHORIZATION_ADMIN_SCOPE = "authorization:admin"
OA_AUTHORIZATION_READ_SCOPE = "authorization:read"
OA_AUTHORIZATION_MUTATION_RESPONSE_SCHEMA_VERSION = "oa_authz_mutation_response.v1"
OA_AUTHORIZATION_READ_RESPONSE_SCHEMA_VERSION = "oa_authz_read_response.v1"
OA_AUTHORIZATION_EVENT_LIST_SCHEMA_VERSION = "oa_authz_event_list.v1"

_ROLE_FIELDS = frozenset(
    {"display_name", "description", "status", "scopes", "metadata", "expected_revision"}
)
_GROUP_FIELDS = frozenset(
    {"display_name", "description", "status", "metadata", "expected_revision"}
)
_ASSIGNMENT_FIELDS = frozenset({"status", "expected_revision"})


@dataclass
class OaAuthorizationService:
    repository: OaAuthorizationRepository
    resolver: OaEffectiveAuthorizationResolver
    membership_registry: OaTenantMembershipRegistry

    def upsert_role(
        self,
        *,
        tenant_id: str,
        role_id: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _bound_payload(
            payload,
            allowed_fields=_ROLE_FIELDS,
            tenant_id=tenant_id,
            role_id=role_id,
        )
        return _mutation_response(
            self.repository.upsert_role(request, context=context)
        )

    def upsert_group(
        self,
        *,
        tenant_id: str,
        group_id: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _bound_payload(
            payload,
            allowed_fields=_GROUP_FIELDS,
            tenant_id=tenant_id,
            group_id=group_id,
        )
        return _mutation_response(
            self.repository.upsert_group(request, context=context)
        )

    def upsert_group_member(
        self,
        *,
        tenant_id: str,
        group_id: str,
        subject_id: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _bound_payload(
            payload,
            allowed_fields=_ASSIGNMENT_FIELDS,
            tenant_id=tenant_id,
            group_id=group_id,
            subject_id=subject_id,
        )
        return _mutation_response(
            self.repository.upsert_group_member(request, context=context)
        )

    def upsert_group_role(
        self,
        *,
        tenant_id: str,
        group_id: str,
        role_id: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _bound_payload(
            payload,
            allowed_fields=_ASSIGNMENT_FIELDS,
            tenant_id=tenant_id,
            group_id=group_id,
            role_id=role_id,
        )
        return _mutation_response(
            self.repository.upsert_group_role(request, context=context)
        )

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> dict[str, Any]:
        try:
            membership = self.membership_registry.get_membership(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except OaMembershipError as exc:
            raise OaAuthorizationError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
            ) from exc
        if membership is None:
            raise OaAuthorizationError(
                status_code=404,
                error_code="oa.authorization_membership_not_found",
                detail="authorization membership was not found.",
            )
        return {
            "response_schema_version": OA_AUTHORIZATION_READ_RESPONSE_SCHEMA_VERSION,
            "service_id": "nex-oa",
            "authorization": self.resolver.resolve(membership),
        }

    def list_events(self, *, tenant_id: str, limit: object = 100) -> dict[str, Any]:
        events = self.repository.list_events(tenant_id=tenant_id, limit=limit)
        return {
            "event_list_schema_version": OA_AUTHORIZATION_EVENT_LIST_SCHEMA_VERSION,
            "service_id": "nex-oa",
            "tenant_id": tenant_id,
            "events": events,
            "count": len(events),
        }


def register_authorization_routes(
    app: FastAPI, *, service: OaAuthorizationService
) -> None:
    @app.put(
        "/internal/v1/auth/tenants/{tenant_id}/roles/{role_id}",
        response_model=None,
    )
    def upsert_role(
        tenant_id: str,
        role_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _mutation_route(
            request,
            authorization,
            lambda context: service.upsert_role(
                tenant_id=tenant_id,
                role_id=role_id,
                payload=payload,
                context=context,
            ),
        )

    @app.put(
        "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}",
        response_model=None,
    )
    def upsert_group(
        tenant_id: str,
        group_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _mutation_route(
            request,
            authorization,
            lambda context: service.upsert_group(
                tenant_id=tenant_id,
                group_id=group_id,
                payload=payload,
                context=context,
            ),
        )

    @app.put(
        "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/members/{subject_id}",
        response_model=None,
    )
    def upsert_group_member(
        tenant_id: str,
        group_id: str,
        subject_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _mutation_route(
            request,
            authorization,
            lambda context: service.upsert_group_member(
                tenant_id=tenant_id,
                group_id=group_id,
                subject_id=subject_id,
                payload=payload,
                context=context,
            ),
        )

    @app.put(
        "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/roles/{role_id}",
        response_model=None,
    )
    def upsert_group_role(
        tenant_id: str,
        group_id: str,
        role_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _mutation_route(
            request,
            authorization,
            lambda context: service.upsert_group_role(
                tenant_id=tenant_id,
                group_id=group_id,
                role_id=role_id,
                payload=payload,
                context=context,
            ),
        )

    @app.get(
        "/internal/v1/auth/tenants/{tenant_id}/subjects/{subject_id}/authorization",
        response_model=None,
    )
    def get_effective_authorization(
        tenant_id: str,
        subject_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _read_route(
            request,
            authorization,
            lambda: service.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            ),
        )

    @app.get(
        "/internal/v1/auth/tenants/{tenant_id}/authorization-events",
        response_model=None,
    )
    def list_authorization_events(
        tenant_id: str,
        request: Request,
        limit: str = "100",
        authorization: str | None = Header(default=None),
    ):
        return _read_route(
            request,
            authorization,
            lambda: service.list_events(tenant_id=tenant_id, limit=limit),
        )


def _mutation_route(
    request: Request,
    authorization: str | None,
    operation: Any,
) -> dict[str, Any] | JSONResponse:
    claims, auth_problem = _authorize(
        request,
        authorization,
        required_scope=OA_AUTHORIZATION_ADMIN_SCOPE,
    )
    if auth_problem is not None:
        return auth_problem
    assert claims is not None
    context = {
        "actor_ref": f"nex.service:{claims.service_id}",
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }
    try:
        response = operation(context)
    except OaAuthorizationError as exc:
        return _problem(request, exc)
    return {**response, "request_id": context["request_id"], "trace_id": context["trace_id"]}


def _read_route(
    request: Request,
    authorization: str | None,
    operation: Any,
) -> dict[str, Any] | JSONResponse:
    _, auth_problem = _authorize(
        request,
        authorization,
        required_scope=OA_AUTHORIZATION_READ_SCOPE,
    )
    if auth_problem is not None:
        return auth_problem
    try:
        response = operation()
    except OaAuthorizationError as exc:
        return _problem(request, exc)
    return {
        **response,
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }


def _authorize(
    request: Request,
    authorization: str | None,
    *,
    required_scope: str,
) -> tuple[Any | None, JSONResponse | None]:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE, required_scope],
    )
    if result.ok:
        return result.claims, None
    status_code = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return None, problem_response(
        request,
        status_code=status_code,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status_code == 403 else "Authentication failed",
        detail=result.detail or "OA authorization administration requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authorization-admin-access",
    )


def _bound_payload(
    payload: Mapping[str, Any],
    *,
    allowed_fields: frozenset[str],
    **identity: str,
) -> dict[str, Any]:
    unexpected = sorted(set(payload) - allowed_fields)
    if unexpected:
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_payload_invalid",
            detail=f"unsupported authorization field: {unexpected[0]}",
        )
    return {**dict(payload), **identity}


def _mutation_response(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_schema_version": OA_AUTHORIZATION_MUTATION_RESPONSE_SCHEMA_VERSION,
        "service_id": "nex-oa",
        **dict(result),
    }


def _problem(request: Request, exc: OaAuthorizationError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Authorization administration request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/authorization-administration",
    )
