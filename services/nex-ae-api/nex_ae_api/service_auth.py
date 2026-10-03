from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from nex_runtime import issue_mock_service_token


AE_OUTBOUND_TOKEN_ENV_BY_AUDIENCE = {
    "nex-oa": "NEX_AE_TO_OA_SERVICE_TOKEN",
    "nex-cx": "NEX_AE_TO_CX_SERVICE_TOKEN",
    "nex-mo": "NEX_AE_TO_MO_SERVICE_TOKEN",
    "nex-ag": "NEX_AE_TO_AG_SERVICE_TOKEN",
}


@dataclass
class AeOutboundServiceTokenError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def resolve_ae_outbound_service_token(
    configured_token: str | None,
    *,
    audience: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    if configured_token is not None:
        if not configured_token or configured_token != configured_token.strip():
            raise AeOutboundServiceTokenError(
                "ae.outbound_service_token_invalid",
                "configured outbound service token is invalid",
            )
        return configured_token
    env = os.environ if environ is None else environ
    profile = env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK").strip().upper()
    if profile == "TEST_MOCK":
        return issue_mock_service_token(
            service_id="nex-ae-api", audience=audience
        ).access_token
    if profile not in {"DUAL_READ", "SIGNED_ONLY"}:
        raise AeOutboundServiceTokenError(
            "ae.service_token_rollout_profile_invalid",
            "service-token rollout profile is invalid",
        )
    env_name = AE_OUTBOUND_TOKEN_ENV_BY_AUDIENCE.get(audience)
    candidate = env.get(env_name) if env_name else None
    if candidate and candidate == candidate.strip():
        return candidate
    raise AeOutboundServiceTokenError(
        "ae.outbound_service_token_missing",
        "signed outbound service token is required",
    )
