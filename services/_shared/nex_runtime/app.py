from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware


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
        check = _check_database(spec.database_env)
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
            "contract_catalog_version": "slice-0000",
            "build_sha": os.getenv("NEX_BUILD_SHA", "local"),
        }

    return app


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
        allow_methods=["GET"],
        allow_headers=["*"],
    )


def _check_database(database_env: str) -> dict[str, Any]:
    database_url = os.getenv(database_env)
    started = time.perf_counter()
    if not database_url:
        return {
            "name": "database",
            "ok": False,
            "database_env": database_env,
            "error_code": "DATABASE_URL_MISSING",
            "latency_ms": 0,
        }

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except Exception:
        return {
            "name": "database",
            "ok": False,
            "database_env": database_env,
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": _elapsed_ms(started),
        }

    return {
        "name": "database",
        "ok": True,
        "database_env": database_env,
        "latency_ms": _elapsed_ms(started),
    }


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
