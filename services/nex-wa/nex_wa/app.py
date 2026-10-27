from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    build_service_token_admission_runtime,
    register_service_job_control_routes,
)

from .config import WaSettings, load_wa_settings
from .intake import WaEvidenceIntakeService
from .intake_api import register_evidence_intake_routes
from .persistence import WaPersistenceRuntime, build_wa_persistence_runtime
from .read_api import WaCoreReadService, register_core_read_routes

SERVICE_SPEC = SERVICE_SPECS["nex-wa"]
CONTRACT_CATALOG_VERSION = "p9-s23"
PersistenceBuilder = Callable[..., WaPersistenceRuntime]


def create_wa_app(
    *,
    environ: Mapping[str, str] | None = None,
    settings: WaSettings | None = None,
    persistence_builder: PersistenceBuilder = build_wa_persistence_runtime,
) -> FastAPI:
    env = dict(os.environ if environ is None else environ)
    resolved = settings or load_wa_settings(env)
    env.update(
        {
            "NEX_PROFILE": resolved.profile,
            "NEX_VERSION": resolved.version,
            "NEX_BUILD_SHA": resolved.build_sha,
        }
    )
    token_admission = build_service_token_admission_runtime(
        expected_audience=resolved.service_id,
        environ=env,
    )
    persistence = (
        persistence_builder(environ=env)
        if env.get(resolved.database_env)
        else None
    )
    readiness_checks: tuple[Callable[[], Mapping[str, Any]], ...] = (
        (persistence.migration_readiness,) if persistence is not None else ()
    )
    app = build_service_app(
        SERVICE_SPEC,
        readiness_checks=readiness_checks,
        include_oa_mock_auth_routes=False,
        service_token_admission=token_admission,
        environ=env,
        contract_catalog_version=CONTRACT_CATALOG_VERSION,
        description=(
            "NeX Work Asset service shell. WorkEvidence and WorkAsset domain "
            "behavior activates only in their owning P9 slices."
        ),
    )
    app.state.wa_settings = resolved
    app.state.wa_service_token_admission = token_admission
    app.state.wa_persistence = persistence
    app.state.wa_work_evidence_repository = (
        persistence.work_evidence_repository if persistence is not None else None
    )
    app.state.wa_work_asset_repository = (
        persistence.work_asset_repository if persistence is not None else None
    )
    app.state.wa_evidence_admission_service = (
        persistence.evidence_admission_service if persistence is not None else None
    )
    app.state.wa_core_read_service = (
        WaCoreReadService(
            persistence.work_evidence_repository,
            persistence.work_asset_repository,
        )
        if persistence is not None
        else None
    )
    job_queue = getattr(persistence, "job_queue", None)
    app.state.wa_evidence_intake_service = (
        WaEvidenceIntakeService(job_queue) if job_queue is not None else None
    )
    if job_queue is not None:
        register_service_job_control_routes(
            app,
            service_id=resolved.service_id,
            job_queue=job_queue,
        )
    register_evidence_intake_routes(app)
    register_core_read_routes(app)
    return app
