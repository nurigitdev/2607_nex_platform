from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService
from nex_oa.token_signing import InMemoryOaRsaSigningProvider


def _runtime() -> tuple[OaClientCredentialTokenExchangeService, dict[str, str]]:
    principals = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
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
    reference = "file:///tmp/oa-key-exchange"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(),
        deployment_profile="test",
    )
    public_jwk = signer.public_jwk(reference, key_id="oa-key-exchange")
    keys.register_key(
        {
            "key_id": "oa-key-exchange",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": public_jwk,
            "private_key_ref": reference,
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 900,
            "verify_until": 1_230,
        }
    )
    keys.set_key_state(
        "oa-key-exchange",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )
    return (
        OaClientCredentialTokenExchangeService(
            principal_service=principals,
            signing_key_service=keys,
            signing_provider=signer,
        ),
        public_jwk,
    )


def _request(**changes: object) -> dict[str, object]:
    return {
        "grant_type": "client_credentials",
        "credential_id": "cred-ae-runtime",
        "client_secret": "top-secret",
        "audience": "nex-cx",
        "scope": "generation:create document:read",
        **changes,
    }


def test_exchange_issues_verifiable_rs256_service_access_token() -> None:
    service, jwk = _runtime()
    response = service.exchange(_request(), now_epoch=500, token_id="sat-fixed")
    header, claims, signing_input, signature = _parts(response["access_token"])

    rsa.RSAPublicNumbers(
        e=_integer(jwk["e"]),
        n=_integer(jwk["n"]),
    ).public_key().verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())

    assert response == {
        "response_schema_version": "oa_token_response.v1",
        "access_token": response["access_token"],
        "token_type": "Bearer",
        "expires_in": 300,
        "scope": "document:read generation:create",
    }
    assert header == {"alg": "RS256", "kid": "oa-key-exchange", "typ": "at+jwt"}
    assert claims["iss"] == PRODUCTION_TOKEN_ISSUER
    assert claims["sub"] == "service:nex-ae-api"
    assert claims["credential_id"] == "cred-ae-runtime"
    assert claims["credential_revision"] == 1
    assert claims["exp"] - claims["iat"] == 300
    assert "client_secret" not in claims


def test_exchange_uses_runtime_clock_and_random_token_id(monkeypatch) -> None:
    service, _ = _runtime()
    monkeypatch.setattr("nex_oa.token_exchange_service.time", lambda: 500)

    first = _parts(service.exchange(_request())["access_token"])[1]
    second = _parts(service.exchange(_request())["access_token"])[1]

    assert first["iat"] == 500
    assert first["jti"].startswith("sat-")
    assert first["jti"] != second["jti"]


@pytest.mark.parametrize(
    ("changes", "status", "message"),
    [
        ({"grant_type": "password"}, 400, "grant_type"),
        ({"credential_id": ""}, 400, "credential_id"),
        ({"client_secret": " wrong "}, 400, "client_secret"),
        ({"audience": ""}, 400, "audience"),
        ({"scope": "document:read  generation:create"}, 400, "space-delimited"),
        ({"scope": "document:read document:read"}, 400, "duplicates"),
        ({"audience": "nex-mo"}, 403, "audience"),
        ({"scope": "admin:all"}, 403, "scope"),
        ({"extra": True}, 400, "unsupported"),
    ],
)
def test_exchange_rejects_invalid_or_unauthorized_requests(
    changes: dict[str, object], status: int, message: str
) -> None:
    service, _ = _runtime()
    with pytest.raises(OaSignedTokenError, match=message) as exc:
        service.exchange(_request(**changes), now_epoch=500)
    assert exc.value.status_code == status


@pytest.mark.parametrize("now_epoch", [-1, True])
def test_exchange_rejects_invalid_clock(now_epoch: object) -> None:
    service, _ = _runtime()
    with pytest.raises(OaSignedTokenError, match="now_epoch"):
        service.exchange(_request(), now_epoch=now_epoch)  # type: ignore[arg-type]


def test_exchange_fails_closed_without_active_key_or_custody() -> None:
    service, _ = _runtime()
    with pytest.raises(OaSignedTokenError) as no_key:
        service.exchange(_request(), now_epoch=901)
    assert no_key.value.status_code == 503

    service, _ = _runtime()
    service.signing_provider = InMemoryOaRsaSigningProvider()
    with pytest.raises(OaSignedTokenError) as no_custody:
        service.exchange(_request(), now_epoch=500)
    assert no_custody.value.code == "oa.signing_key_custody_unavailable"


def test_exchange_rejects_generated_claims_that_violate_profile() -> None:
    service, _ = _runtime()
    service.principal_service.authenticate_client_credential = lambda *a, **k: {  # type: ignore[method-assign]
        "service_id": "unknown",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 1,
        "allowed_audiences": ("nex-cx",),
        "allowed_scopes": ("document:read",),
    }
    with pytest.raises(OaSignedTokenError) as exc:
        service.exchange(
            _request(scope="document:read"), now_epoch=500, token_id="sat-invalid"
        )
    assert exc.value.code == "oa.token_claims_invalid"
    assert exc.value.status_code == 500


def _parts(token: str) -> tuple[dict, dict, bytes, bytes]:
    encoded_header, encoded_claims, encoded_signature = token.split(".")
    return (
        json.loads(_decode(encoded_header)),
        json.loads(_decode(encoded_claims)),
        f"{encoded_header}.{encoded_claims}".encode("ascii"),
        _decode(encoded_signature),
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _integer(value: str) -> int:
    return int.from_bytes(_decode(value), "big")
