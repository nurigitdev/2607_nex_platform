from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from nex_ae_api.product_planning_runtime import ProductPlanningRuntimeError
from nex_ae_api.route_auth import authorize_ae_internal_service_request


class ProductPlanningEventAdmission(Protocol):
    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def register_product_planning_event_routes(
    app: FastAPI,
    *,
    admission: ProductPlanningEventAdmission | None,
) -> None:
    @app.post("/internal/v1/product-planning-events", response_model=None)
    def ingest_product_planning_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        authorized = authorize_ae_internal_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-eos",),
            error_code="AE_PRODUCT_PLANNING_EVENT_CALLER_DENIED",
            title="AE Product planning event caller denied",
            detail="Only nex-eos may publish Product planning authority events.",
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        if admission is None:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_PRODUCT_PLANNING_EVENT_UNAVAILABLE",
                title="AE Product planning event admission unavailable",
                detail="The active Product coordinator is not installed.",
                retryable=True,
            )
        try:
            receipt = admission.ingest(payload)
        except ProductPlanningRuntimeError as exc:
            return problem_response(
                request,
                status_code=503 if exc.retryable else 409,
                error_code=exc.error_code,
                title="AE Product planning event admission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        return JSONResponse(receipt, status_code=202)


__all__ = [
    "ProductPlanningEventAdmission",
    "register_product_planning_event_routes",
]
