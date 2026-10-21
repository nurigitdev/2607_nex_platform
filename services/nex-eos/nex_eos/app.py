from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI
from nex_runtime import SERVICE_SPECS, build_service_app

from .config import EosSettings, load_eos_settings
from .dependencies import build_eos_dependencies

SERVICE_SPEC = SERVICE_SPECS["nex-eos"]
CONTRACT_CATALOG_VERSION = "p8-s07"


def create_eos_app(
    *,
    environ: Mapping[str, str] | None = None,
    settings: EosSettings | None = None,
) -> FastAPI:
    env = dict(os.environ if environ is None else environ)
    resolved = settings or load_eos_settings(env)
    env.update(
        {
            "NEX_PROFILE": resolved.profile,
            "NEX_VERSION": resolved.version,
            "NEX_BUILD_SHA": resolved.build_sha,
        }
    )
    dependencies = build_eos_dependencies(resolved, environ=env)
    app = build_service_app(
        SERVICE_SPEC,
        readiness_checks=dependencies.readiness_checks,
        include_oa_mock_auth_routes=False,
        service_token_admission=dependencies.service_token_admission,
        environ=env,
        contract_catalog_version=CONTRACT_CATALOG_VERSION,
        description=(
            "NeX Enterprise Operations System service runtime. Business domain "
            "routes are intentionally activated only by their owning slices."
        ),
    )
    app.state.eos_settings = resolved
    app.state.eos_dependencies = dependencies
    app.state.eos_database_runtime = dependencies.database_runtime
    app.state.eos_business_transactions = dependencies.business_transactions
    app.state.eos_organization = dependencies.organization
    return app
