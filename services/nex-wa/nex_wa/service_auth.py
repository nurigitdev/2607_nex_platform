from __future__ import annotations

import os
from collections.abc import Mapping

from nex_runtime import issue_mock_service_token

WA_OUTBOUND_TOKEN_ENV_BY_AUDIENCE = {
    "nex-ae-api": "NEX_WA_TO_AE_SERVICE_TOKEN",
    "nex-wc": "NEX_WA_TO_WC_SERVICE_TOKEN",
    "nex-oa": "NEX_WA_TO_OA_SERVICE_TOKEN",
    "nex-eos": "NEX_WA_TO_EOS_SERVICE_TOKEN",
}


def resolve_wa_outbound_service_token(
    configured_token: str | None,
    *,
    audience: str,
    scopes: tuple[str, ...],
    environ: Mapping[str, str] | None = None,
) -> str:
    if configured_token is not None:
        if not configured_token or configured_token != configured_token.strip():
            raise ValueError("configured WA outbound service token is invalid")
        return configured_token
    env = os.environ if environ is None else environ
    profile = env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK").strip().upper()
    if profile == "TEST_MOCK":
        return issue_mock_service_token(
            service_id="nex-wa",
            audience=audience,
            scopes=scopes,
        ).access_token
    if profile not in {"DUAL_READ", "SIGNED_ONLY"}:
        raise ValueError("service-token rollout profile is invalid")
    env_name = WA_OUTBOUND_TOKEN_ENV_BY_AUDIENCE.get(audience)
    candidate = env.get(env_name) if env_name else None
    if candidate and candidate == candidate.strip():
        return candidate
    raise ValueError("signed WA outbound service token is required")
