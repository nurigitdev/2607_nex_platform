from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    build_service_token_admission_runtime,
)

from .config import WaSettings, load_wa_settings


SERVICE_SPEC = SERVICE_SPECS["nex-wa"]
CONTRACT_CATALOG_VERSION = "p9-s01"


def create_wa_app(
    *,
    environ: Mapping[str, str] | None = None,
    settings: WaSettings | None = None,
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
    app = build_service_app(
        SERVICE_SPEC,
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
    return app
