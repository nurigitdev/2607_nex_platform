from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .project_entitlement_reconciliation import (
    EosProjectEntitlementReconciliationError,
)


def register_project_entitlement_reconciliation_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v1/projects/{project_id}/authorization:reconcile",
        response_model=None,
        operation_id="PROJECT.AUTHORIZATION.RECONCILE",
    )
    def reconcile_project_authorization(
        project_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service = getattr(
            request.app.state, "eos_project_entitlement_reconciliation", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_PROJECT_ENTITLEMENT_RECONCILIATION_UNAVAILABLE",
                title="Project entitlement reconciliation unavailable",
                detail="EOS Project entitlement reconciliation is not configured",
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-project-entitlement-reconciliation-unavailable"
                ),
            )
        try:
            tenant_id = payload["tenant_id"]
            correlation_id = payload["correlation_id"]
            repair = payload.get("repair", False)
            if (
                not isinstance(tenant_id, str)
                or not tenant_id.strip()
                or not isinstance(correlation_id, str)
                or not correlation_id.strip()
                or not isinstance(repair, bool)
            ):
                raise TypeError
            return service.reconcile(
                tenant_id=tenant_id,
                project_id=project_id,
                correlation_id=correlation_id,
                repair=repair,
            )
        except (KeyError, TypeError):
            return _problem(
                request,
                EosProjectEntitlementReconciliationError(
                    "EOS_PROJECT_ENTITLEMENT_RECONCILIATION_INVALID",
                    "tenant_id and correlation_id are required",
                    status_code=422,
                ),
            )
        except EosProjectEntitlementReconciliationError as exc:
            return _problem(request, exc)


def _problem(
    request: Request, exc: EosProjectEntitlementReconciliationError
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Project entitlement reconciliation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-project-entitlement-reconciliation-failed"
        ),
    )
