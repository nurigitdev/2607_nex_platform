from __future__ import annotations

import base64
import json

import pytest

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_oa.token_validation_service import (
    OaSignedTokenValidationService,
    decode_and_verify_service_token,
)


def _raw_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _segment(value: object) -> str:
    return _raw_segment(json.dumps(value, separators=(",", ":")).encode())


def _runtime() -> dict[str, object]:
    principal_repository = InMemoryOaServicePrincipalRepository()
    principals = OaServicePrincipalService(principal_repository)
    principals.upsert_principal(
        {
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-cx", "nex-oa"],
            "allowed_scopes": ["document:read", "generation:create"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=100,
        credential_id="cred-ae-runtime",
        client_secret="top-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-validation"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    keys.register_key(
        {
            "key_id": "oa-key-validation",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(reference, key_id="oa-key-validation"),
            "private_key_ref": reference,
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 900,
            "verify_until": 1_230,
        }
    )
    keys.set_key_state(
        "oa-key-validation", target_state="ACTIVE", expected_revision=1, now_epoch=430
    )
    exchange = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    )
    token = exchange.exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": "cred-ae-runtime",
            "client_secret": "top-secret",
            "audience": "nex-cx",
            "scope": "generation:create document:read",
        },
        now_epoch=500,
        token_id="sat-validation",
    )["access_token"]
    return {
        "principal_repository": principal_repository,
        "principals": principals,
        "signer": signer,
        "reference": reference,
        "keys": keys,
        "token": token,
        "validator": OaSignedTokenValidationService(
            signing_key_service=keys,
            principal_service=principals,
        ),
    }


def test_validate_and_introspect_active_token() -> None:
    runtime = _runtime()
    validator = runtime["validator"]
    token = runtime["token"]

    claims = validator.validate(  # type: ignore[union-attr]
        token,
        expected_audience="nex-cx",
        required_scopes=("document:read",),
        now_epoch=600,
    )
    introspection = validator.introspect(  # type: ignore[union-attr]
        token,
        expected_audience="nex-cx",
        required_scopes=("generation:create",),
        now_epoch=600,
    )

    assert claims["jti"] == "sat-validation"
    assert introspection["active"] is True
    assert introspection["credential_id"] == "cred-ae-runtime"
    assert "jti" not in introspection
    assert "access_token" not in introspection


@pytest.mark.parametrize(
    ("kwargs", "code", "status"),
    [
        ({"expected_audience": "nex-oa"}, "oa.token_audience_forbidden", 403),
        ({"required_scopes": ("admin:all",)}, "oa.token_scope_forbidden", 403),
        ({"now_epoch": 469}, "oa.token_issued_in_future", 401),
        ({"now_epoch": 830}, "oa.token_expired", 401),
        ({"expected_audience": "external"}, "oa.token_audience_unknown", 403),
        ({"required_scopes": "document:read"}, "oa.token_scope_invalid", 403),
        ({"required_scopes": ("document:read", "document:read")}, "oa.token_scope_invalid", 403),
        ({"required_scopes": ("",)}, "oa.token_value_invalid", 401),
        ({"now_epoch": True}, "oa.token_clock_invalid", 401),
    ],
)
def test_validation_runtime_policy_failures(
    kwargs: dict[str, object], code: str, status: int
) -> None:
    runtime = _runtime()
    arguments = {
        "expected_audience": "nex-cx",
        "required_scopes": (),
        "now_epoch": 600,
        **kwargs,
    }
    with pytest.raises(OaSignedTokenError) as exc:
        runtime["validator"].validate(runtime["token"], **arguments)  # type: ignore[union-attr]
    assert exc.value.code == code
    assert exc.value.status_code == status


def test_revocation_credential_and_principal_lineage_fail_closed() -> None:
    runtime = _runtime()
    validator = runtime["validator"]
    token = runtime["token"]
    keys = runtime["keys"]
    claims = _claims(token)
    keys.revoke_token_claims(  # type: ignore[union-attr]
        claims, reason_code="OPERATOR", now_epoch=600, revocation_id="rev-validation"
    )
    with pytest.raises(OaSignedTokenError) as revoked:
        validator.validate(token, expected_audience="nex-cx", now_epoch=600)  # type: ignore[union-attr]
    assert revoked.value.code == "oa.token_revoked"

    stale = _runtime()
    stale_credential = stale["principal_repository"].credentials["cred-ae-runtime"]  # type: ignore[union-attr,index]
    stale_credential.update(status="ROTATING", grace_until=850, revision=2)
    with pytest.raises(OaSignedTokenError) as revision:
        stale["validator"].validate(  # type: ignore[union-attr]
            stale["token"], expected_audience="nex-cx", now_epoch=600
        )
    assert revision.value.code == "oa.token_credential_stale"

    disabled = _runtime()
    disabled["principals"].set_principal_status(  # type: ignore[union-attr]
        "ae-runtime", target_status="DISABLED", expected_revision=1
    )
    inactive = disabled["validator"].introspect(  # type: ignore[union-attr]
        disabled["token"], expected_audience="nex-cx", now_epoch=600
    )
    assert inactive == {
        "introspection_schema_version": "oa_token_introspection.v1",
        "active": False,
        "reason_code": "oa.token_credential_inactive",
    }


def test_current_principal_allowlists_and_identity_are_enforced() -> None:
    audience = _runtime()
    audience["principals"].upsert_principal(  # type: ignore[union-attr]
        {
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-oa"],
            "allowed_scopes": ["document:read", "generation:create"],
            "expected_revision": 1,
        }
    )
    with pytest.raises(OaSignedTokenError) as audience_error:
        audience["validator"].validate(  # type: ignore[union-attr]
            audience["token"], expected_audience="nex-cx", now_epoch=600
        )
    assert audience_error.value.code == "oa.token_audience_revoked"

    scope = _runtime()
    scope["principals"].upsert_principal(  # type: ignore[union-attr]
        {
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-cx"],
            "allowed_scopes": ["document:read"],
            "expected_revision": 1,
        }
    )
    with pytest.raises(OaSignedTokenError) as scope_error:
        scope["validator"].validate(  # type: ignore[union-attr]
            scope["token"], expected_audience="nex-cx", now_epoch=600
        )
    assert scope_error.value.code == "oa.token_scope_revoked"

    identity = _runtime()
    identity["principal_repository"].principals["ae-runtime"]["service_id"] = "nex-mo"  # type: ignore[union-attr,index]
    with pytest.raises(OaSignedTokenError) as identity_error:
        identity["validator"].validate(  # type: ignore[union-attr]
            identity["token"], expected_audience="nex-cx", now_epoch=600
        )
    assert identity_error.value.code == "oa.token_principal_mismatch"


def test_not_before_and_introspection_service_error_paths(monkeypatch) -> None:
    runtime = _runtime()
    claims = _claims(runtime["token"])
    claims["iat"] = 600
    claims["nbf"] = 600
    claims["exp"] = 800
    future = _resign(runtime, claims)
    with pytest.raises(OaSignedTokenError) as not_yet:
        runtime["validator"].validate(  # type: ignore[union-attr]
            future, expected_audience="nex-cx", now_epoch=569
        )
    assert not_yet.value.code == "oa.token_issued_in_future"

    monkeypatch.setattr(
        runtime["validator"],
        "validate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OaServicePrincipalError(401, "oa.synthetic_inactive", "inactive")
        ),
    )
    assert runtime["validator"].introspect(  # type: ignore[union-attr]
        runtime["token"], expected_audience="nex-cx"
    )["reason_code"] == "oa.synthetic_inactive"


@pytest.mark.parametrize(
    ("token", "code"),
    [
        ("not-a-jwt", "oa.token_malformed"),
        ("a..b", "oa.token_malformed"),
        ("***.e30.c2ln", "oa.token_encoding_invalid"),
        (_segment([]) + "." + _segment({}) + ".c2ln", "oa.token_json_invalid"),
        (
            _raw_segment(b'{"alg":"RS256","alg":"RS256","kid":"key"}')
            + "."
            + _segment({})
            + ".c2ln",
            "oa.token_json_invalid",
        ),
        (_segment({"alg": "none"}) + "." + _segment({}) + ".c2ln", "oa.token_algorithm_invalid"),
    ],
)
def test_malformed_tokens_fail_before_signature_validation(token: str, code: str) -> None:
    with pytest.raises(OaSignedTokenError) as exc:
        decode_and_verify_service_token(token, jwks={"keys": []})
    assert exc.value.code == code


def test_signature_key_and_shape_failures_are_explicit() -> None:
    runtime = _runtime()
    token = runtime["token"]
    keys = runtime["keys"]
    jwks = keys.jwks(at_epoch=600)  # type: ignore[union-attr]

    with pytest.raises(OaSignedTokenError) as signature:
        decode_and_verify_service_token(token[:-1] + ("A" if token[-1] != "A" else "B"), jwks=jwks)
    assert signature.value.code == "oa.token_signature_invalid"

    for document, code in (
        ({}, "oa.jwks_invalid"),
        ({"keys": []}, "oa.token_key_unavailable"),
        ({"keys": [jwks["keys"][0], jwks["keys"][0]]}, "oa.token_key_unavailable"),
        ({"keys": [{**jwks["keys"][0], "d": "secret"}]}, "oa.jwk_private_material"),
        ({"keys": [{**jwks["keys"][0], "use": "enc"}]}, "oa.jwk_metadata_invalid"),
        ({"keys": [{**jwks["keys"][0], "n": "AQ"}]}, "oa.jwk_modulus_invalid"),
        ({"keys": [{**jwks["keys"][0], "e": "BA"}]}, "oa.jwk_exponent_invalid"),
        ({"keys": [{**jwks["keys"][0], "e": ""}]}, "oa.token_value_invalid"),
    ):
        with pytest.raises(OaSignedTokenError) as exc:
            decode_and_verify_service_token(token, jwks=document)
        assert exc.value.code == code

    claims = _claims(token)
    claims.pop("credential_id")
    invalid_shape = _resign(runtime, claims)
    with pytest.raises(OaSignedTokenError) as shape:
        decode_and_verify_service_token(invalid_shape, jwks=jwks)
    assert shape.value.code == "oa.token_shape_invalid"


def test_invalid_jwk_encoding_and_rsa_numbers_fail_closed() -> None:
    runtime = _runtime()
    token = runtime["token"]
    jwk = runtime["keys"].jwks(at_epoch=600)["keys"][0]  # type: ignore[union-attr]
    for changes, code in (
        ({"n": "***"}, "oa.token_encoding_invalid"),
        ({"e": _encode_int(_integer(jwk["n"]) + 2)}, "oa.jwk_invalid"),
    ):
        with pytest.raises(OaSignedTokenError) as exc:
            decode_and_verify_service_token(token, jwks={"keys": [{**jwk, **changes}]})
        assert exc.value.code == code


def test_resolve_token_credential_default_clock_and_rotation_expiry(monkeypatch) -> None:
    runtime = _runtime()
    principals = runtime["principals"]
    monkeypatch.setattr("nex_oa.service_principal_service._now_epoch", lambda: 600)
    assert principals.resolve_token_credential("cred-ae-runtime")["credential_revision"] == 1  # type: ignore[union-attr]
    credential = runtime["principal_repository"].credentials["cred-ae-runtime"]  # type: ignore[union-attr,index]
    credential.update(status="ROTATING", grace_until=610, revision=2)
    with pytest.raises(OaServicePrincipalError):
        principals.resolve_token_credential("cred-ae-runtime", now_epoch=611)  # type: ignore[union-attr]
    with pytest.raises(OaServicePrincipalError):
        principals.resolve_token_credential("missing", now_epoch=600)  # type: ignore[union-attr]

    expired = _runtime()
    expired["principal_repository"].credentials["cred-ae-runtime"]["expires_at"] = 600  # type: ignore[union-attr,index]
    with pytest.raises(OaServicePrincipalError):
        expired["principals"].resolve_token_credential(  # type: ignore[union-attr]
            "cred-ae-runtime", now_epoch=600
        )


def _claims(token: str) -> dict[str, object]:
    return json.loads(_decode(token.split(".")[1]))


def _resign(runtime: dict[str, object], claims: dict[str, object]) -> str:
    return encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": "oa-key-validation"},
        claims=claims,
        private_key_ref=str(runtime["reference"]),
        signing_provider=runtime["signer"],  # type: ignore[arg-type]
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _integer(value: str) -> int:
    return int.from_bytes(_decode(value), "big")


def _encode_int(value: int) -> str:
    return _raw_segment(value.to_bytes((value.bit_length() + 7) // 8, "big"))
