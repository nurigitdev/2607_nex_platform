from __future__ import annotations

from fastapi import FastAPI, Header, Request

from nex_ag.federated_operator_authorization import (
    AG_FEDERATED_AUTHORIZATION_TELEMETRY_STATE_KEY,
    AgFederatedAuthorizationTelemetry,
)
from nex_ag.service_auth import authorize_ag_service_or_admin_request
from nex_runtime import trace_id_from_headers


AG_FEDERATED_AUTH_RUNTIME_PATH = "/admin/v1/auth/federated-operator-runtime"


def attach_ag_federated_authorization_telemetry(
    app: FastAPI,
) -> AgFederatedAuthorizationTelemetry:
    telemetry = AgFederatedAuthorizationTelemetry()
    setattr(
        app.state,
        AG_FEDERATED_AUTHORIZATION_TELEMETRY_STATE_KEY,
        telemetry,
    )
    return telemetry


def register_ag_federated_operator_runtime_routes(
    app: FastAPI,
    *,
    telemetry: AgFederatedAuthorizationTelemetry,
) -> None:
    @app.get(AG_FEDERATED_AUTH_RUNTIME_PATH, response_model=None)
    def get_federated_operator_runtime(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = authorize_ag_service_or_admin_request(
            request,
            authorization,
            admin_error_code="AG_FEDERATED_RUNTIME_ADMIN_ROLE_REQUIRED",
            admin_error_detail=(
                "AG federated authorization runtime requires an admin user role."
            ),
        )
        if denied is not None:
            return denied
        return {
            **telemetry.public_snapshot(),
            "trace_id": trace_id_from_headers(request),
        }
