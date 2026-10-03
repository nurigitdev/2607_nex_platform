from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime.signed_token_verifier import (
    MAX_JWKS_KEYS,
    BoundedJwksCache,
    SignedServiceTokenVerifier,
    SignedTokenVerificationError,
    StaticJwksSource,
)


REFERENCE = "memory://oa-key-shared-verifier"
KEY_ID = "oa-key-shared-verifier"


@pytest.fixture(scope="module")
def signing_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    return {
        "signer": signer,
        "jwk": signer.public_jwk(REFERENCE, key_id=KEY_ID),
    }


def _claims(**changes: Any) -> dict[str, Any]:
    claims = {
        "iss": "urn:nex-platform:oa",
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "iat": 500,
        "nbf": 500,
        "exp": 800,
        "jti": "sat-shared-verifier",
        "token_use": "service_access",
        "scope": "document:read generation:create",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 2,
    }
    claims.update(changes)
    return claims


def _token(
    runtime: dict[str, Any],
    *,
    claims: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    return encode_signed_jwt(
        headers=headers
        or {"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims=claims or _claims(),
        private_key_ref=REFERENCE,
        signing_provider=runtime["signer"],
    )


def _source(runtime: dict[str, Any], *keys: dict[str, str]) -> StaticJwksSource:
    return StaticJwksSource(
        {
            "issuer": "urn:nex-platform:oa",
            "keys": list(keys or (runtime["jwk"],)),
        }
    )


def _verifier(
    runtime: dict[str, Any], source: StaticJwksSource | None = None
) -> tuple[SignedServiceTokenVerifier, StaticJwksSource]:
    resolved = source or _source(runtime)
    cache = BoundedJwksCache(resolved, clock=lambda: 600)
    return SignedServiceTokenVerifier(cache, clock=lambda: 600), resolved


def _raw_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _segment(value: object) -> str:
    return _raw_segment(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def test_verifies_oa_service_token_and_projects_privacy_safe_claims(
    signing_runtime: dict[str, Any],
) -> None:
    verifier, source = _verifier(signing_runtime)

    verified = verifier.verify_authorization_header(
        f"Bearer {_token(signing_runtime)}",
        expected_audience="nex-cx",
        required_scopes=("document:read",),
    )

    assert verified.service_id == "nex-ae-api"
    assert verified.scopes == ("document:read", "generation:create")
    assert len(verified.token_id_digest) == 64
    assert source.fetch_count == 1
    projection = verified.to_wire()
    assert "jti" not in projection
    assert "access_token" not in projection
    assert "sat-shared-verifier" not in json.dumps(projection)


def test_cache_reuses_keys_refreshes_on_ttl_and_unknown_kid(
    signing_runtime: dict[str, Any],
) -> None:
    source = _source(signing_runtime)
    cache = BoundedJwksCache(source, ttl_seconds=300, clock=lambda: 500)

    assert cache.key_for(KEY_ID, now_epoch=500).key_size == 3072
    assert cache.key_for(KEY_ID, now_epoch=799).key_size == 3072
    assert source.fetch_count == 1
    assert cache.key_for(KEY_ID, now_epoch=800).key_size == 3072
    assert source.fetch_count == 2
    rotated = {**signing_runtime["jwk"], "kid": "oa-key-rotated"}
    source.replace(
        {
            "issuer": "urn:nex-platform:oa",
            "keys": [signing_runtime["jwk"], rotated],
        }
    )
    assert cache.key_for("oa-key-rotated", now_epoch=801).key_size == 3072
    assert source.fetch_count == 3
    assert cache.key_count == 2
    assert cache.refreshed_at == 801


def test_unknown_kid_and_refresh_failure_do_not_accept_stale_keys(
    signing_runtime: dict[str, Any],
) -> None:
    source = _source(signing_runtime)
    cache = BoundedJwksCache(source, ttl_seconds=10)
    cache.refresh(now_epoch=10)
    with pytest.raises(SignedTokenVerificationError) as unknown:
        cache.key_for("missing-key", now_epoch=11)
    assert unknown.value.code == "nex.token_key_unavailable"
    assert source.fetch_count == 2

    def unavailable() -> dict[str, Any]:
        raise OSError("secret endpoint detail")

    cache = BoundedJwksCache(unavailable, ttl_seconds=10)
    with pytest.raises(SignedTokenVerificationError) as failed:
        cache.key_for(KEY_ID, now_epoch=20)
    assert failed.value.code == "nex.jwks_unavailable"
    assert failed.value.status_code == 503
    assert "secret" not in str(failed.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 0},
        {"ttl_seconds": 901},
        {"max_keys": 0},
        {"max_keys": MAX_JWKS_KEYS + 1},
    ],
)
def test_cache_configuration_is_bounded(
    signing_runtime: dict[str, Any], kwargs: dict[str, int]
) -> None:
    with pytest.raises(ValueError):
        BoundedJwksCache(_source(signing_runtime), **kwargs)


def test_cache_rejects_invalid_source_clock_and_explicit_clock(
    signing_runtime: dict[str, Any],
) -> None:
    with pytest.raises(TypeError):
        BoundedJwksCache(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BoundedJwksCache(_source(signing_runtime), clock=None)  # type: ignore[arg-type]
    cache = BoundedJwksCache(_source(signing_runtime), clock=lambda: -1)
    with pytest.raises(ValueError):
        cache.refresh()
    with pytest.raises(ValueError):
        cache.refresh(now_epoch=True)


@pytest.mark.parametrize(
    ("document", "code"),
    [
        (None, "nex.jwks_invalid"),
        ({"keys": []}, "nex.jwks_issuer_invalid"),
        ({"issuer": "wrong", "keys": []}, "nex.jwks_issuer_invalid"),
        ({"issuer": "urn:nex-platform:oa", "keys": {}}, "nex.jwks_invalid"),
        (
            {"issuer": "urn:nex-platform:oa", "keys": [{}] * (MAX_JWKS_KEYS + 1)},
            "nex.jwks_invalid",
        ),
        ({"issuer": "urn:nex-platform:oa", "keys": ["key"]}, "nex.jwks_invalid"),
    ],
)
def test_invalid_jwks_documents_fail_closed(document: object, code: str) -> None:
    cache = BoundedJwksCache(lambda: document)  # type: ignore[arg-type,return-value]
    with pytest.raises(SignedTokenVerificationError) as exc:
        cache.refresh(now_epoch=600)
    assert exc.value.code == code
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"kid": ""}, "nex.jwks_invalid"),
        ({"d": "private"}, "nex.jwk_private_material"),
        ({"use": "enc"}, "nex.jwk_metadata_invalid"),
        ({"n": "AQ"}, "nex.jwk_modulus_invalid"),
        ({"n": "***"}, "nex.jwk_encoding_invalid"),
        ({"e": "BA"}, "nex.jwk_exponent_invalid"),
        ({"e": ""}, "nex.jwk_encoding_invalid"),
    ],
)
def test_invalid_public_jwk_is_rejected(
    signing_runtime: dict[str, Any], change: dict[str, str], code: str
) -> None:
    jwk = {**signing_runtime["jwk"], **change}
    with pytest.raises(SignedTokenVerificationError) as exc:
        BoundedJwksCache(_source(signing_runtime, jwk)).refresh(now_epoch=600)
    assert exc.value.code == code


def test_duplicate_kid_and_invalid_rsa_numbers_are_rejected(
    signing_runtime: dict[str, Any],
) -> None:
    duplicate = _source(signing_runtime, signing_runtime["jwk"], signing_runtime["jwk"])
    with pytest.raises(SignedTokenVerificationError) as duplicate_error:
        BoundedJwksCache(duplicate).refresh(now_epoch=600)
    assert duplicate_error.value.code == "nex.jwks_duplicate_kid"

    modulus = int.from_bytes(
        base64.urlsafe_b64decode(signing_runtime["jwk"]["n"] + "=="), "big"
    )
    invalid_exponent = _raw_segment((modulus + 2).to_bytes(384, "big"))
    invalid = _source(
        signing_runtime, {**signing_runtime["jwk"], "e": invalid_exponent}
    )
    with pytest.raises(SignedTokenVerificationError) as invalid_error:
        BoundedJwksCache(invalid).refresh(now_epoch=600)
    assert invalid_error.value.code == "nex.jwk_invalid"


@pytest.mark.parametrize(
    ("authorization", "code"),
    [
        (None, "nex.authorization_missing"),
        ("", "nex.authorization_missing"),
        ("Basic abc", "nex.authorization_invalid"),
        ("Bearer", "nex.authorization_invalid"),
        ("Bearer  abc", "nex.authorization_invalid"),
    ],
)
def test_authorization_header_is_strict(
    signing_runtime: dict[str, Any], authorization: object, code: str
) -> None:
    verifier, _ = _verifier(signing_runtime)
    with pytest.raises(SignedTokenVerificationError) as exc:
        verifier.verify_authorization_header(
            authorization, expected_audience="nex-cx"
        )
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("token", "code"),
    [
        (None, "nex.token_value_invalid"),
        ("not-a-jwt", "nex.token_malformed"),
        ("a..b", "nex.token_malformed"),
        ("***.e30.c2ln", "nex.token_encoding_invalid"),
        (_segment([]) + "." + _segment({}) + ".c2ln", "nex.token_json_invalid"),
        (
            _raw_segment(b'{"alg":"RS256","alg":"RS256","kid":"key"}')
            + "."
            + _segment({})
            + ".c2ln",
            "nex.token_json_invalid",
        ),
    ],
)
def test_malformed_tokens_are_rejected_before_key_lookup(
    signing_runtime: dict[str, Any], token: object, code: str
) -> None:
    verifier, source = _verifier(signing_runtime)
    with pytest.raises(SignedTokenVerificationError) as exc:
        verifier.verify(token, expected_audience="nex-cx")
    assert exc.value.code == code
    assert source.fetch_count == 0


def test_oversized_token_and_invalid_verifier_configuration_are_rejected(
    signing_runtime: dict[str, Any],
) -> None:
    verifier, _ = _verifier(signing_runtime)
    with pytest.raises(SignedTokenVerificationError) as oversized:
        verifier.verify("a" * 16_385, expected_audience="nex-cx")
    assert oversized.value.code == "nex.token_oversized"
    with pytest.raises(TypeError):
        SignedServiceTokenVerifier(
            BoundedJwksCache(_source(signing_runtime)), clock=None  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"alg": "HS256", "typ": "at+jwt", "kid": KEY_ID}, "nex.token_algorithm_invalid"),
        ({"alg": "RS256", "typ": "JWT", "kid": KEY_ID}, "nex.token_type_invalid"),
        ({"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID, "jku": "https://bad"}, "nex.token_header_forbidden"),
        ({"alg": "RS256", "typ": "at+jwt", "kid": ""}, "nex.token_value_invalid"),
    ],
)
def test_token_headers_are_allowlisted(
    signing_runtime: dict[str, Any], headers: dict[str, Any], code: str
) -> None:
    verifier, _ = _verifier(signing_runtime)
    with pytest.raises(SignedTokenVerificationError) as exc:
        verifier.verify(
            _token(signing_runtime, headers=headers), expected_audience="nex-cx"
        )
    assert exc.value.code == code


def test_unknown_key_and_invalid_signature_are_rejected(
    signing_runtime: dict[str, Any],
) -> None:
    verifier, _ = _verifier(signing_runtime)
    unknown = _token(
        signing_runtime,
        headers={"alg": "RS256", "typ": "at+jwt", "kid": "unknown"},
    )
    with pytest.raises(SignedTokenVerificationError) as key_error:
        verifier.verify(unknown, expected_audience="nex-cx")
    assert key_error.value.code == "nex.token_key_unavailable"

    token = _token(signing_runtime)
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(SignedTokenVerificationError) as signature_error:
        verifier.verify(changed, expected_audience="nex-cx")
    assert signature_error.value.code == "nex.token_signature_invalid"


@pytest.mark.parametrize(
    ("changes", "code", "status"),
    [
        ({"credential_id": None}, "nex.token_value_invalid", 401),
        ({"credential_revision": 0}, "nex.token_credential_revision_invalid", 401),
        ({"iss": "wrong"}, "nex.token_issuer_invalid", 401),
        ({"aud": "nex-mo"}, "nex.token_audience_forbidden", 403),
        ({"token_use": "delegated_user_access"}, "nex.token_use_invalid", 401),
        ({"service_id": "unknown"}, "nex.token_subject_invalid", 401),
        ({"sub": "service:nex-mo"}, "nex.token_subject_invalid", 401),
        ({"nbf": 501}, "nex.token_time_invalid", 401),
        ({"nbf": 460}, "nex.token_time_invalid", 401),
        ({"exp": 500}, "nex.token_time_invalid", 401),
        ({"exp": 801}, "nex.token_ttl_invalid", 401),
        ({"iat": 631, "nbf": 601, "exp": 800}, "nex.token_issued_in_future", 401),
        ({"exp": 569}, "nex.token_expired", 401),
        ({"scope": "document:read  generation:create"}, "nex.token_scope_invalid", 401),
        ({"scope": "document:read document:read"}, "nex.token_scope_invalid", 401),
        ({"password": "secret"}, "nex.token_claim_forbidden", 401),
    ],
)
def test_claim_policy_failures_are_explicit_and_privacy_safe(
    signing_runtime: dict[str, Any],
    changes: dict[str, Any],
    code: str,
    status: int,
) -> None:
    verifier, _ = _verifier(signing_runtime)
    with pytest.raises(SignedTokenVerificationError) as exc:
        verifier.verify(
            _token(signing_runtime, claims=_claims(**changes)),
            expected_audience="nex-cx",
            now_epoch=600,
        )
    assert exc.value.code == code
    assert exc.value.status_code == status
    assert "secret" not in str(exc.value)


def test_missing_non_integer_and_not_yet_valid_claims_are_rejected(
    signing_runtime: dict[str, Any],
) -> None:
    verifier, _ = _verifier(signing_runtime)
    missing = _claims()
    missing.pop("jti")
    cases = (
        (missing, 600, "nex.token_claim_missing"),
        (_claims(iat=True), 600, "nex.token_claim_invalid"),
        (_claims(iat=600, nbf=570, exp=800), 569, "nex.token_issued_in_future"),
        (_claims(iat=530, nbf=530, exp=800), 499, "nex.token_not_yet_valid"),
    )
    for claims, now_epoch, code in cases:
        with pytest.raises(SignedTokenVerificationError) as exc:
            verifier.verify(
                _token(signing_runtime, claims=claims),
                expected_audience="nex-cx",
                now_epoch=now_epoch,
            )
        assert exc.value.code == code


def test_expected_audience_scope_and_clock_inputs_are_validated(
    signing_runtime: dict[str, Any],
) -> None:
    verifier, _ = _verifier(signing_runtime)
    token = _token(signing_runtime)
    cases = (
        ({"expected_audience": "external"}, "nex.token_audience_unknown", 403),
        ({"expected_audience": "nex-cx", "required_scopes": "document:read"}, "nex.token_scope_invalid", 403),
        ({"expected_audience": "nex-cx", "required_scopes": ("x", "x")}, "nex.token_scope_invalid", 403),
        ({"expected_audience": "nex-cx", "required_scopes": ("admin",)}, "nex.token_scope_forbidden", 403),
        ({"expected_audience": "nex-cx", "now_epoch": True}, "nex.token_clock_invalid", 401),
    )
    for kwargs, code, status in cases:
        with pytest.raises(SignedTokenVerificationError) as exc:
            verifier.verify(token, **kwargs)  # type: ignore[arg-type]
        assert exc.value.code == code
        assert exc.value.status_code == status
