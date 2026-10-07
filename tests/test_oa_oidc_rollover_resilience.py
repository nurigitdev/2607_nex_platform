from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import run_oa_oidc_rollover_resilience as runner
from nex_oa.federated_identities import OaFederationError, build_federation_provider
from nex_oa.oidc_verifier import (
    OidcDiscoveryJwksCache,
    StaticOidcDocumentSource,
    _validated_discovery,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider

NOW = 1_800_000_000
ISSUER = "https://id.example.test"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
JWKS = f"{ISSUER}/keys"


def _provider() -> dict[str, Any]:
    return build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": ISSUER,
            "client_id": "nex-platform",
            "discovery_url": DISCOVERY,
            "display_name": "Company OIDC",
        }
    )


def _documents(jwk: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        DISCOVERY: {
            "issuer": ISSUER,
            "jwks_uri": JWKS,
            "id_token_signing_alg_values_supported": ["RS256"],
        },
        JWKS: {"keys": [jwk]},
    }


def test_initial_unknown_key_performs_only_one_refresh() -> None:
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key("memory://oidc")
    source = StaticOidcDocumentSource(_documents(jwk))
    cache = OidcDiscoveryJwksCache(_provider(), source, clock=lambda: NOW)

    with pytest.raises(OaFederationError) as exc:
        cache.key_for("unknown", now_epoch=NOW)

    assert exc.value.error_code == "oa.oidc_key_unavailable"
    assert source.fetches == [DISCOVERY, JWKS]
    assert cache.safe_snapshot()["refresh_generation"] == 1


def test_expired_cache_outage_fails_closed_and_recovers() -> None:
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key("memory://oidc")
    source = StaticOidcDocumentSource(_documents(jwk))
    cache = OidcDiscoveryJwksCache(
        _provider(), source, ttl_seconds=10, clock=lambda: NOW
    )
    assert cache.key_for(jwk["kid"], now_epoch=NOW)
    source._documents.pop(DISCOVERY)

    with pytest.raises(OaFederationError) as outage:
        cache.key_for(jwk["kid"], now_epoch=NOW + 10)

    assert outage.value.error_code == "oa.oidc_document_unavailable"
    failed = cache.safe_snapshot()
    assert failed["last_refresh_outcome"] == "FAILED"
    assert failed["last_failure_at_epoch"] == NOW + 10
    assert failed["consecutive_failures"] == 1
    assert failed["refresh_generation"] == 1

    source.replace(DISCOVERY, _documents(jwk)[DISCOVERY])
    assert cache.key_for(jwk["kid"], now_epoch=NOW + 11)
    recovered = cache.safe_snapshot()
    assert recovered["last_refresh_outcome"] == "SUCCEEDED"
    assert recovered["last_failure_at_epoch"] is None
    assert recovered["consecutive_failures"] == 0
    assert recovered["refresh_generation"] == 2


def test_unexpected_source_failure_is_redacted_and_counted() -> None:
    class BrokenSource:
        def fetch_json(self, _url: str) -> Mapping[str, Any]:
            raise RuntimeError("private transport detail")

    cache = OidcDiscoveryJwksCache(_provider(), BrokenSource(), clock=lambda: NOW)
    with pytest.raises(OaFederationError) as exc:
        cache.refresh(now_epoch=NOW)

    assert exc.value.error_code == "oa.oidc_document_unavailable"
    assert "private transport detail" not in str(exc.value)
    assert cache.safe_snapshot()["consecutive_failures"] == 1


@pytest.mark.parametrize(
    "jwks_uri",
    (
        "https://other.example.test/keys",
        "https://user@id.example.test/keys",
        "https://id.example.test/keys?version=1",
        "https://id.example.test/keys#fragment",
        "https://id.example.test/",
        "https://id.example.test:bad/keys",
    ),
)
def test_discovery_rejects_unsafe_or_cross_origin_jwks(jwks_uri: str) -> None:
    with pytest.raises(OaFederationError) as exc:
        _validated_discovery(
            {
                "issuer": ISSUER,
                "jwks_uri": jwks_uri,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            provider=_provider(),
        )
    assert exc.value.error_code in {
        "oa.oidc_jwks_uri_invalid",
        "oa.oidc_jwks_origin_invalid",
    }


def test_explicit_default_https_port_is_same_origin() -> None:
    result = _validated_discovery(
        {
            "issuer": ISSUER,
            "jwks_uri": "https://id.example.test:443/keys",
            "id_token_signing_alg_values_supported": ["RS256"],
        },
        provider=_provider(),
    )
    assert result == "https://id.example.test:443/keys"


def test_resilience_runner_and_cli(monkeypatch, capsys) -> None:
    result = runner.run_oa_oidc_rollover_resilience()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["decision"]["expired_cache_fallback"] is False
    assert result["decision"]["live_idp_contacted"] is False
    assert runner._error_code(lambda: None) is None
    assert runner.summary_line(result).startswith(
        "oa_oidc_rollover_resilience=pass checks=14/14 generation=4"
    )

    monkeypatch.setattr(runner, "run_oa_oidc_rollover_resilience", lambda: result)
    assert runner.main(["--summary"]) == 0
    assert "next=1440" in capsys.readouterr().out

    failure = {**result, "status": "FAIL", "issues": ["x"]}
    assert runner.summary_line(failure) == ("oa_oidc_rollover_resilience=fail issues=1")
    monkeypatch.setattr(
        runner,
        "run_oa_oidc_rollover_resilience",
        lambda: failure,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
