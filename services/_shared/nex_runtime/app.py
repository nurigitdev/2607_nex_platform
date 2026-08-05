from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import (
    DEFAULT_SERVICE_SCOPE,
    ClaimValidationResult,
    issue_mock_service_token,
    validate_authorization_header,
    validate_mock_service_token,
)
from .database import check_database_readiness
from .problem import problem_response


@dataclass(frozen=True)
class ServiceSpec:
    service_id: str
    package_name: str
    display_name: str
    database_env: str
    default_port: int


SERVICE_SPECS: dict[str, ServiceSpec] = {
    "nex-oa": ServiceSpec(
        service_id="nex-oa",
        package_name="nex_oa",
        display_name="NeX Open Auth",
        database_env="NEX_OA_DATABASE_URL",
        default_port=8101,
    ),
    "nex-ag": ServiceSpec(
        service_id="nex-ag",
        package_name="nex_ag",
        display_name="NeX Admin and Governance",
        database_env="NEX_AG_DATABASE_URL",
        default_port=8102,
    ),
    "nex-ae-api": ServiceSpec(
        service_id="nex-ae-api",
        package_name="nex_ae_api",
        display_name="NeX Agent Experience API",
        database_env="NEX_AE_DATABASE_URL",
        default_port=8103,
    ),
    "nex-cx": ServiceSpec(
        service_id="nex-cx",
        package_name="nex_cx",
        display_name="NeX Content Experience",
        database_env="NEX_CX_DATABASE_URL",
        default_port=8104,
    ),
    "nex-mo": ServiceSpec(
        service_id="nex-mo",
        package_name="nex_mo",
        display_name="NeX Model Operations",
        database_env="NEX_MO_DATABASE_URL",
        default_port=8105,
    ),
}


def build_service_app(spec: ServiceSpec) -> FastAPI:
    version = os.getenv("NEX_VERSION", "0.0.0-slice0001")
    profile = os.getenv("NEX_PROFILE", "local_mock")
    started_at = _utc_now()

    app = FastAPI(
        title=f"{spec.display_name} Service",
        version=version,
        description=f"Slice 0001 service shell for {spec.service_id}.",
    )
    _configure_cors(app)

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service_id": spec.service_id,
            "service_name": spec.display_name,
            "profile": profile,
            "links": {
                "health": "/health",
                "ready": "/ready",
                "version": "/version",
            },
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "service_id": spec.service_id,
            "health_status": "HEALTHY",
            "profile": profile,
            "started_at": started_at,
            "checked_at": _utc_now(),
        }

    @app.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        check = check_database_readiness(spec.database_env)
        readiness_status = "READY" if check["ok"] else "NOT_READY"
        if readiness_status != "READY":
            response.status_code = 503

        return {
            "service_id": spec.service_id,
            "readiness_status": readiness_status,
            "profile": profile,
            "checked_at": _utc_now(),
            "checks": [check],
        }

    @app.get("/version")
    def version_info() -> dict[str, Any]:
        return {
            "service_id": spec.service_id,
            "service_name": spec.display_name,
            "version": version,
            "api_version": "v1",
            "contract_catalog_version": "slice-0022",
            "build_sha": os.getenv("NEX_BUILD_SHA", "local"),
        }

    @app.get("/internal/v1/auth/service-claim", response_model=None)
    def validate_service_claim(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        result = validate_authorization_header(
            authorization,
            expected_audience=spec.service_id,
            required_scopes=[DEFAULT_SERVICE_SCOPE],
        )
        if not result.ok:
            return _auth_problem_response(request, result)

        assert result.claims is not None
        return {
            "service_id": spec.service_id,
            "claim_status": "VALID",
            "claims": result.claims.to_wire(),
        }

    if spec.service_id == "nex-oa":
        _register_oa_mock_auth_routes(app)

    return app


def _register_oa_mock_auth_routes(app: FastAPI) -> None:
    @app.post("/api/v1/auth/service-token", response_model=None)
    def create_service_token(
        payload: dict[str, Any],
        request: Request,
    ) -> dict[str, Any] | JSONResponse:
        try:
            issued = issue_mock_service_token(
                service_id=payload.get("service_id", ""),
                audience=payload.get("audience", ""),
                scopes=payload.get("scopes"),
                ttl_seconds=payload.get("ttl_seconds", 3600),
            )
        except (TypeError, ValueError) as exc:
            result = ClaimValidationResult(
                ok=False,
                error_code="SERVICE_TOKEN_REQUEST_INVALID",
                detail=str(exc),
            )
            return _auth_problem_response(request, result, status_code=400)

        return {
            "token_type": "Bearer",
            "access_token": issued.access_token,
            "claims": issued.claims.to_wire(),
        }

    @app.post("/api/v1/auth/introspect")
    def introspect_service_token(payload: dict[str, Any]) -> dict[str, Any]:
        result = validate_mock_service_token(
            payload.get("token", ""),
            expected_audience=payload.get("audience"),
            required_scopes=payload.get("required_scopes", []),
        )
        if not result.ok:
            return {
                "active": False,
                "error_code": result.error_code,
                "detail": result.detail,
            }

        assert result.claims is not None
        return {
            "active": True,
            "claims": result.claims.to_wire(),
        }


def _configure_cors(app: FastAPI) -> None:
    origins = [
        origin.strip()
        for origin in os.getenv(
            "NEX_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


def _auth_problem_response(
    request: Request,
    result: ClaimValidationResult,
    *,
    status_code: int = 401,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "Service claim validation failed.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )

def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
