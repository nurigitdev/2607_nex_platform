from __future__ import annotations

import pytest

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository
from nex_oa.signed_tokens import OaSignedTokenError, build_test_public_jwk
from nex_oa.signing_key_service import OaSigningKeyService


def _payload(key_id: str, *, offset: int = 0) -> dict:
    return {
        "key_id": key_id,
        "issuer": PRODUCTION_TOKEN_ISSUER,
        "public_jwk": build_test_public_jwk(key_id),
        "private_key_ref": f"file:///tmp/{key_id}.pem",
        "published_at": 100 + offset,
        "activate_at": 430 + offset,
        "sign_until": 800 + offset,
        "verify_until": 1_130 + offset,
    }


def _service() -> OaSigningKeyService:
    return OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(),
        deployment_profile="test",
    )


def test_service_registers_activates_lists_and_publishes_public_jwks() -> None:
    service = _service()
    created = service.register_key(_payload("oa-key-service"))
    activated = service.set_key_state(
        "oa-key-service",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )

    assert created["signing_key"]["state"] == "PREPUBLISHED"
    assert "private_key_ref" not in created["signing_key"]
    assert activated["signing_key"]["state"] == "ACTIVE"
    assert service.get_key("oa-key-service") == activated
    assert service.list_keys()["count"] == 1
    assert service.jwks(at_epoch=500)["key_count"] == 1
    assert service.active_signing_key(at_epoch=500)["key_id"] == "oa-key-service"


def test_service_rejects_missing_and_unavailable_active_keys() -> None:
    service = _service()
    with pytest.raises(OaSignedTokenError, match="not found"):
        service.get_key("oa-key-missing")
    with pytest.raises(OaSignedTokenError, match="not found"):
        service.set_key_state(
            "oa-key-missing",
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=430,
        )
    service.register_key(_payload("oa-key-future"))
    with pytest.raises(OaSignedTokenError, match="exactly one"):
        service.active_signing_key(at_epoch=500)


def test_service_reconciles_signing_and_verification_windows() -> None:
    service = _service()
    service.register_key(_payload("oa-key-reconcile"))
    service.set_key_state(
        "oa-key-reconcile",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )

    first = service.reconcile_key_states(now_epoch=800)
    second = service.reconcile_key_states(now_epoch=1_130)
    third = service.reconcile_key_states(now_epoch=1_200)

    assert first == {"verify_only_count": 1, "retired_count": 0}
    assert second == {"verify_only_count": 0, "retired_count": 1}
    assert third == {"verify_only_count": 0, "retired_count": 0}
    assert service.get_key("oa-key-reconcile")["signing_key"]["state"] == "RETIRED"
    assert service.jwks(at_epoch=1_200)["key_count"] == 0


def test_service_revokes_checks_and_purges_token_jti() -> None:
    service = _service()
    claims = {
        "iss": PRODUCTION_TOKEN_ISSUER,
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "jti": "service-jti",
        "token_use": "service_access",
        "exp": 900,
    }
    result = service.revoke_token_claims(
        claims,
        reason_code="OPERATOR",
        now_epoch=600,
        revocation_id="rev-service",
    )

    assert result["revocation_id"] == "rev-service"
    assert "jti" not in result
    assert service.is_jti_revoked("service-jti", at_epoch=899) is True
    assert service.is_jti_revoked("unknown-jti", at_epoch=899) is False
    assert service.purge_expired_revocations(at_epoch=899) == 0
    assert service.purge_expired_revocations(at_epoch=900) == 1


def test_service_default_clock_paths(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("nex_oa.signing_key_service.time", lambda: 430)
    service.register_key(_payload("oa-key-clock"))
    service.set_key_state(
        "oa-key-clock", target_state="ACTIVE", expected_revision=1
    )
    assert service.active_signing_key()["key_id"] == "oa-key-clock"
    assert service.jwks()["key_count"] == 1
    assert service.reconcile_key_states() == {
        "verify_only_count": 0,
        "retired_count": 0,
    }
    assert service.is_jti_revoked("missing") is False
    assert service.purge_expired_revocations() == 0
