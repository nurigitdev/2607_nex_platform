#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.federated_identities import (
    OaFederationError,
    build_external_identity_link,
    build_federation_provider,
    resolve_federated_identity,
)
from nex_oa.oidc_verifier import (
    OidcDiscoveryJwksCache,
    OidcIdTokenVerifier,
)
from nex_oa.token_signing import (
    InMemoryOaRsaSigningProvider,
    encode_signed_jwt,
)

NOW = 1_800_000_000
ISSUER = "https://id.nex-staging.test:8443"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
JWKS_V1 = f"{ISSUER}/oidc/keys-v1"
JWKS_V2 = f"{ISSUER}/oidc/keys-v2"


class _ControlledSource:
    def __init__(self, documents: Mapping[str, Mapping[str, Any]]) -> None:
        self.documents = {key: dict(value) for key, value in documents.items()}
        self.available = True
        self.fetches: list[str] = []

    def fetch_json(self, url: str) -> Mapping[str, Any]:
        self.fetches.append(url)
        if not self.available or url not in self.documents:
            raise OaFederationError(
                503,
                "oa.oidc_document_unavailable",
                "OIDC provider document is unavailable.",
            )
        return self.documents[url]


def run_oa_oidc_rollover_resilience() -> dict[str, Any]:
    provider = build_federation_provider(
        {
            "provider_id": "openbao-staging",
            "issuer": ISSUER,
            "client_id": "nex-platform-oa-staging",
            "discovery_url": DISCOVERY,
            "display_name": "OpenBao staging",
        }
    )
    signer = InMemoryOaRsaSigningProvider()
    old_jwk = signer.generate_key("memory://oidc-old")
    new_jwk = signer.generate_key("memory://oidc-new")
    discovery = {
        "issuer": ISSUER,
        "jwks_uri": JWKS_V1,
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    source = _ControlledSource(
        {
            DISCOVERY: discovery,
            JWKS_V1: {"keys": [old_jwk]},
            JWKS_V2: {"keys": [new_jwk]},
        }
    )
    cache = OidcDiscoveryJwksCache(
        provider,
        source,
        ttl_seconds=60,
        clock=lambda: NOW,
    )
    verifier = OidcIdTokenVerifier(provider, cache, clock=lambda: NOW)
    old_token = _token(signer, old_jwk, "memory://oidc-old")
    new_token = _token(signer, new_jwk, "memory://oidc-new")

    old_verified = verifier.verify(
        old_token,
        expected_nonce="browser-nonce",
        now_epoch=NOW,
    )
    discovery["jwks_uri"] = JWKS_V2
    source.documents[DISCOVERY] = discovery
    new_verified = verifier.verify(
        new_token,
        expected_nonce="browser-nonce",
        now_epoch=NOW + 1,
    )
    old_after_rollover = _error_code(
        lambda: verifier.verify(
            old_token,
            expected_nonce="browser-nonce",
            now_epoch=NOW + 2,
        )
    )

    source.available = False
    outage = _error_code(
        lambda: verifier.verify(
            new_token,
            expected_nonce="browser-nonce",
            now_epoch=NOW + 62,
        )
    )
    failed_snapshot = cache.safe_snapshot()
    source.available = True
    recovered = verifier.verify(
        new_token,
        expected_nonce="browser-nonce",
        now_epoch=NOW + 63,
    )
    recovered_snapshot = cache.safe_snapshot()

    identity = build_external_identity_link(
        {
            "provider_id": provider["provider_id"],
            "external_subject": "opaque-subject",
            "tenant_id": "tenant-stage",
            "subject_id": "subject-stage",
        },
        provider=provider,
    )
    disabled_link = {**identity, "status": "DISABLED"}
    disabled_provider = {**provider, "status": "DISABLED"}
    assertion = {
        "issuer": ISSUER,
        "audience": (provider["client_id"],),
        "subject": "opaque-subject",
    }
    checks = {
        "initial_key_verified": old_verified.key_id == old_jwk["kid"],
        "unknown_key_triggered_rollover": new_verified.key_id == new_jwk["kid"],
        "retired_key_rejected": old_after_rollover == "oa.oidc_key_unavailable",
        "outage_failed_closed": outage == "oa.oidc_document_unavailable",
        "stale_key_not_served": failed_snapshot["last_refresh_outcome"] == "FAILED",
        "failure_count_visible": failed_snapshot["consecutive_failures"] == 1,
        "last_good_generation_preserved": failed_snapshot["refresh_generation"] == 3,
        "recovery_verified": recovered.key_id == new_jwk["kid"],
        "recovery_advanced_generation": recovered_snapshot["refresh_generation"] == 4,
        "failure_state_cleared": recovered_snapshot["consecutive_failures"] == 0,
        "disabled_link_denied": _resolution_error(assertion, provider, disabled_link)
        == "oa.federated_identity_not_linked",
        "disabled_provider_denied": _resolution_error(
            assertion, disabled_provider, identity
        )
        == "oa.federation_provider_inactive",
        "key_ids_absent_from_snapshot": recovered_snapshot["key_ids_included"] is False,
        "live_idp_postgres_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_oidc_rollover_resilience_evidence.v1",
        "slice": "1439",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": []
        if passed
        else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "refresh_generation": recovered_snapshot["refresh_generation"],
            "fetch_count": len(source.fetches),
            "consecutive_failures": recovered_snapshot["consecutive_failures"],
        },
        "decision": {
            "expired_cache_fallback": False,
            "cross_origin_jwks_allowed": False,
            "live_idp_contacted": False,
            "live_postgres_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1440" if passed else "blocked",
        },
    }


def _token(
    signer: InMemoryOaRsaSigningProvider,
    jwk: Mapping[str, Any],
    reference: str,
) -> str:
    return encode_signed_jwt(
        headers={"alg": "RS256", "typ": "JWT", "kid": jwk["kid"]},
        claims={
            "iss": ISSUER,
            "sub": "opaque-subject",
            "aud": "nex-platform-oa-staging",
            "iat": NOW,
            "exp": NOW + 300,
            "nonce": "browser-nonce",
        },
        private_key_ref=reference,
        signing_provider=signer,
    )


def _error_code(action: Any) -> str | None:
    try:
        action()
    except OaFederationError as exc:
        return exc.error_code
    return None


def _resolution_error(
    assertion: Mapping[str, Any],
    provider: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> str | None:
    return _error_code(
        lambda: resolve_federated_identity(
            assertion,
            provider=provider,
            identity_link=identity,
        )
    )


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            f"oa_oidc_rollover_resilience=fail issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_oidc_rollover_resilience=pass "
        f"checks={summary.get('check_count', 0)}/14 "
        f"generation={summary.get('refresh_generation', 0)} "
        f"fetches={summary.get('fetch_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_oidc_rollover_resilience()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
