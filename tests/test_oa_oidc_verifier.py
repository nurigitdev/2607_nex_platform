from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nex_oa.federated_identities import OaFederationError, build_federation_provider
from nex_oa.oidc_verifier import (
    OidcDiscoveryJwksCache,
    OidcIdTokenVerifier,
    StaticOidcDocumentSource,
    _public_key,
    _validated_discovery,
    _validated_jwks,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt, public_jwk_from_key
import run_oa_oidc_verifier as runner


NOW = 1_800_000_000
ISSUER = "https://id.example.test"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
JWKS = f"{ISSUER}/jwks"


def _fixture() -> tuple[dict, InMemoryOaRsaSigningProvider, dict, StaticOidcDocumentSource, OidcDiscoveryJwksCache, OidcIdTokenVerifier]:
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": ISSUER,
            "client_id": "nex-platform",
            "discovery_url": DISCOVERY,
            "display_name": "Company OIDC",
        }
    )
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key("memory://oidc-key")
    source = StaticOidcDocumentSource(
        {
            DISCOVERY: {"issuer": ISSUER, "jwks_uri": JWKS, "id_token_signing_alg_values_supported": ["RS256"]},
            JWKS: {"keys": [jwk]},
        }
    )
    cache = OidcDiscoveryJwksCache(provider, source, clock=lambda: NOW)
    return provider, signer, jwk, source, cache, OidcIdTokenVerifier(provider, cache, clock=lambda: NOW)


def _token(signer, jwk, **claims):
    payload = {"iss": ISSUER, "sub": "opaque-subject", "aud": "nex-platform", "iat": NOW, "exp": NOW + 300, "nonce": "nonce-1", **claims}
    return encode_signed_jwt(headers={"alg": "RS256", "typ": "JWT", "kid": jwk["kid"]}, claims=payload, private_key_ref="memory://oidc-key", signing_provider=signer)


def test_verifier_validates_and_redacts_identity() -> None:
    _provider, signer, jwk, source, cache, verifier = _fixture()
    verified = verifier.verify(_token(signer, jwk), expected_nonce="nonce-1", now_epoch=NOW)
    projection = verified.safe_projection()

    assert verified.external_subject == "opaque-subject"
    assert "opaque-subject" not in repr(verified)
    assert projection["raw_external_subject_included"] is False
    assert projection["raw_nonce_included"] is False
    assert projection["raw_id_token_included"] is False
    assert len(projection["key_id_digest"]) == 64
    assert source.fetches == [DISCOVERY, JWKS]
    assert cache.safe_snapshot()["status"] == "POPULATED"
    verifier.verify(_token(signer, jwk), expected_nonce="nonce-1", now_epoch=NOW + 1)
    assert source.fetches == [DISCOVERY, JWKS]


def test_cache_refreshes_on_ttl_and_unknown_key() -> None:
    provider, signer, jwk, source, cache, verifier = _fixture()
    cache.key_for(jwk["kid"], now_epoch=NOW)
    cache.key_for(jwk["kid"], now_epoch=NOW + 300)
    assert len(source.fetches) == 4
    with pytest.raises(OaFederationError) as missing:
        cache.key_for("missing", now_epoch=NOW + 301)
    assert missing.value.error_code == "oa.oidc_key_unavailable"
    assert len(source.fetches) == 6
    assert cache.safe_snapshot()["jwks_uri_configured"] is True


@pytest.mark.parametrize(
    ("claims", "nonce", "error_code"),
    (
        ({"iss": "https://wrong.example.test"}, "nonce-1", "oa.oidc_issuer_invalid"),
        ({"aud": "wrong-client"}, "nonce-1", "oa.oidc_audience_invalid"),
        ({"aud": ["nex-platform", "other"]}, "nonce-1", "oa.oidc_azp_missing"),
        ({"aud": ["nex-platform", "other"], "azp": "wrong"}, "nonce-1", "oa.oidc_azp_invalid"),
        ({"aud": ["nex-platform", "other"], "azp": "nex-platform"}, "nonce-1", None),
        ({}, "wrong", "oa.oidc_nonce_invalid"),
        ({"iat": NOW + 120, "exp": NOW + 300}, "nonce-1", "oa.oidc_not_yet_valid"),
        ({"exp": NOW - 61}, "nonce-1", "oa.oidc_time_invalid"),
        ({"iat": NOW - 4_000, "exp": NOW + 1}, "nonce-1", "oa.oidc_ttl_invalid"),
        ({"nbf": NOW + 1, "iat": NOW}, "nonce-1", "oa.oidc_time_invalid"),
        ({"exp": NOW - 61, "iat": NOW - 300}, "nonce-1", "oa.oidc_expired"),
        ({"aud": []}, "nonce-1", "oa.oidc_audience_invalid"),
        ({"iat": True}, "nonce-1", "oa.oidc_claim_invalid"),
    ),
)
def test_claim_validation(claims: dict, nonce: str, error_code: str | None) -> None:
    _provider, signer, jwk, _source, _cache, verifier = _fixture()
    token = _token(signer, jwk, **claims)
    if error_code is None:
        assert verifier.verify(token, expected_nonce=nonce, now_epoch=NOW).authorized_party == "nex-platform"
    else:
        with pytest.raises(OaFederationError) as exc_info:
            verifier.verify(token, expected_nonce=nonce, now_epoch=NOW)
        assert exc_info.value.error_code == error_code


def test_missing_claim_signature_header_and_token_guards() -> None:
    _provider, signer, jwk, _source, _cache, verifier = _fixture()
    missing = {"iss": ISSUER, "sub": "opaque", "aud": "nex-platform", "iat": NOW, "exp": NOW + 1}
    token = encode_signed_jwt(headers={"alg": "RS256", "kid": jwk["kid"]}, claims=missing, private_key_ref="memory://oidc-key", signing_provider=signer)
    with pytest.raises(OaFederationError) as exc_info:
        verifier.verify(token, expected_nonce="nonce-1", now_epoch=NOW)
    assert exc_info.value.error_code == "oa.oidc_claim_missing"

    bad_signature = _token(signer, jwk)[:-2] + "aa"
    for value, error_code in (("bad", "oa.oidc_token_malformed"), (bad_signature, "oa.oidc_signature_invalid"), ("x" * 20_000, "oa.oidc_token_oversized")):
        with pytest.raises(OaFederationError) as failure:
            verifier.verify(value, expected_nonce="nonce-1", now_epoch=NOW)
        assert failure.value.error_code == error_code

    for headers, error_code in (
        ({"alg": "HS256", "kid": jwk["kid"]}, "oa.oidc_algorithm_invalid"),
        ({"alg": "RS256", "typ": "at+jwt", "kid": jwk["kid"]}, "oa.oidc_type_invalid"),
        ({"alg": "RS256", "kid": jwk["kid"], "jku": "https://evil"}, "oa.oidc_header_forbidden"),
        ({"alg": "RS256"}, "oa.oidc_value_invalid"),
    ):
        value = encode_signed_jwt(headers=headers, claims={"value": True}, private_key_ref="memory://oidc-key", signing_provider=signer)
        with pytest.raises(OaFederationError) as failure:
            verifier.verify(value, expected_nonce="nonce-1", now_epoch=NOW)
        assert failure.value.error_code == error_code


def test_discovery_and_jwks_fail_closed() -> None:
    provider, _signer, jwk, _source, _cache, _verifier = _fixture()
    valid = {"issuer": ISSUER, "jwks_uri": JWKS, "id_token_signing_alg_values_supported": ["RS256"]}
    assert _validated_discovery(valid, provider=provider) == JWKS
    for document, code in (
        ([], "oa.oidc_discovery_invalid"),
        ({**valid, "issuer": "wrong"}, "oa.oidc_discovery_issuer_invalid"),
        ({**valid, "id_token_signing_alg_values_supported": ["ES256"]}, "oa.oidc_discovery_algorithm_invalid"),
        ({**valid, "jwks_uri": "http://id.example.test/jwks"}, "oa.oidc_jwks_uri_invalid"),
    ):
        with pytest.raises(OaFederationError) as exc_info:
            _validated_discovery(document, provider=provider)
        assert exc_info.value.error_code == code

    assert len(_validated_jwks({"keys": [jwk]}, max_keys=1)) == 1
    for document, code in (
        ([], "oa.oidc_jwks_invalid"),
        ({"keys": []}, "oa.oidc_jwks_invalid"),
        ({"keys": [jwk, jwk, jwk]}, "oa.oidc_jwks_invalid"),
        ({"keys": ["bad"]}, "oa.oidc_jwk_invalid"),
        ({"keys": [jwk, {**jwk}]}, "oa.oidc_jwk_duplicate"),
        ({"keys": [{**jwk, "d": "private"}]}, "oa.oidc_jwk_private"),
        ({"keys": [{**jwk, "use": "enc"}]}, "oa.oidc_jwk_metadata_invalid"),
    ):
        limit = 2 if isinstance(document, dict) and len(document.get("keys", [])) == 2 else 1
        with pytest.raises(OaFederationError) as exc_info:
            _validated_jwks(document, max_keys=limit)
        assert exc_info.value.error_code == code


def test_cache_constructor_source_errors_and_clock_guards() -> None:
    provider, _signer, _jwk, source, _cache, _verifier = _fixture()
    for kwargs in ({"ttl_seconds": 0}, {"ttl_seconds": True}, {"max_keys": 0}, {"max_keys": True}):
        with pytest.raises(ValueError):
            OidcDiscoveryJwksCache(provider, source, **kwargs)
    with pytest.raises(TypeError):
        OidcDiscoveryJwksCache(provider, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        OidcDiscoveryJwksCache(provider, source, clock=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OidcDiscoveryJwksCache(provider, source, clock=lambda: -1).refresh()
    source.replace(DISCOVERY, {"bad": True})
    with pytest.raises(OaFederationError):
        OidcDiscoveryJwksCache(provider, source).refresh(now_epoch=NOW)
    with pytest.raises(OaFederationError):
        StaticOidcDocumentSource({}).fetch_json("missing")


def test_verifier_constructor_clock_json_and_jwk_edges() -> None:
    provider, signer, jwk, _source, cache, _verifier = _fixture()
    with pytest.raises(ValueError):
        OidcIdTokenVerifier({**provider, "status": "DISABLED"}, cache)
    with pytest.raises(TypeError):
        OidcIdTokenVerifier(provider, cache, clock=None)  # type: ignore[arg-type]
    verifier = OidcIdTokenVerifier(provider, cache, clock=lambda: -1)
    with pytest.raises(OaFederationError):
        verifier.verify(_token(signer, jwk), expected_nonce="nonce-1")
    with pytest.raises(OaFederationError):
        verifier.verify("e30.e30.bad!", expected_nonce="nonce-1", now_epoch=NOW)
    array_segment = base64.urlsafe_b64encode(json.dumps([]).encode()).rstrip(b"=").decode()
    with pytest.raises(OaFederationError):
        verifier.verify(f"{array_segment}.{array_segment}.AA", expected_nonce="nonce-1", now_epoch=NOW)

    small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    with pytest.raises(OaFederationError):
        _public_key(public_jwk_from_key_for_test(small, "small"))
    with pytest.raises(OaFederationError):
        _public_key({**jwk, "e": "Ag"})


def public_jwk_from_key_for_test(key, kid):
    numbers = key.public_key().public_numbers()
    encode = lambda value: base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": encode(numbers.n), "e": encode(numbers.e)}


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_oidc_verifier()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.summary_line(evidence) == "oa_oidc_verifier=pass checks=9/9 fetches=2 next=1286"
    monkeypatch.setattr(runner, "run_oa_oidc_verifier", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1286" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_oidc_verifier", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1
