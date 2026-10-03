from __future__ import annotations

import pytest

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signed_tokens import (
    OaSignedTokenError,
    build_jwks_document,
    build_signing_key_record,
    build_token_revocation_record,
    digest_token_jti,
    normalize_revocation_id,
    normalize_signing_key_id,
    plan_signing_key_transition,
    build_test_public_jwk,
    token_is_revoked,
)
import run_oa_signed_token_domain as domain_runner


def _key(key_id: str = "oa-key-1") -> dict:
    return build_signing_key_record(
        {
            "key_id": key_id,
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": build_test_public_jwk(key_id),
            "private_key_ref": "file:///tmp/key.pem",
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 800,
            "verify_until": 1_130,
        },
        deployment_profile="test",
    )


def test_build_signing_key_and_forward_transitions() -> None:
    registered = _key()
    active = plan_signing_key_transition(
        registered, target_state="active", expected_revision=1, now_epoch=430
    )
    verify_only = plan_signing_key_transition(
        active, target_state="VERIFY_ONLY", expected_revision=2, now_epoch=800
    )
    retired = plan_signing_key_transition(
        verify_only, target_state="RETIRED", expected_revision=3, now_epoch=1_130
    )

    assert registered["state"] == "PREPUBLISHED"
    assert active["revision"] == 2
    assert verify_only["revision"] == 3
    assert retired["revision"] == 4


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda p: p.update(extra=True), "unsupported fields"),
        (lambda p: p.update(key_id="INVALID"), "key_id is invalid"),
        (lambda p: p.update(issuer="wrong"), "canonical OA issuer"),
        (lambda p: p.update(private_key_ref="file:///tmp/key.pem"), "metadata rejected"),
    ],
)
def test_signing_key_registration_rejects_invalid_metadata(mutator, message: str) -> None:
    payload = {
        "key_id": "oa-key-prod",
        "issuer": PRODUCTION_TOKEN_ISSUER,
        "public_jwk": build_test_public_jwk("oa-key-prod"),
        "private_key_ref": "kms://oa/signing/key",
        "published_at": 100,
        "activate_at": 430,
        "sign_until": 800,
        "verify_until": 1_130,
    }
    mutator(payload)
    with pytest.raises(OaSignedTokenError, match=message):
        build_signing_key_record(payload, deployment_profile="production")


def test_transition_rejects_revision_direction_and_time_errors() -> None:
    registered = _key()
    with pytest.raises(OaSignedTokenError, match="revision conflict"):
        plan_signing_key_transition(
            registered, target_state="ACTIVE", expected_revision=2, now_epoch=430
        )
    with pytest.raises(OaSignedTokenError, match="not allowed"):
        plan_signing_key_transition(
            registered, target_state="RETIRED", expected_revision=1, now_epoch=1_130
        )
    with pytest.raises(OaSignedTokenError, match="has not arrived"):
        plan_signing_key_transition(
            registered, target_state="ACTIVE", expected_revision=1, now_epoch=429
        )
    active = plan_signing_key_transition(
        registered, target_state="ACTIVE", expected_revision=1, now_epoch=430
    )
    verify_only = plan_signing_key_transition(
        active, target_state="VERIFY_ONLY", expected_revision=2, now_epoch=500
    )
    with pytest.raises(OaSignedTokenError, match="window is open"):
        plan_signing_key_transition(
            verify_only, target_state="RETIRED", expected_revision=3, now_epoch=1_129
        )


def test_jwks_filters_terminal_and_expired_keys_and_sorts() -> None:
    first = _key("oa-key-b")
    second = _key("oa-key-a")
    retired = {**_key("oa-key-retired"), "state": "RETIRED"}
    revoked = {**_key("oa-key-revoked"), "state": "REVOKED"}
    expired = {**_key("oa-key-expired"), "verify_until": 400}

    document = build_jwks_document(
        [first, second, retired, revoked, expired], at_epoch=430
    )

    assert [item["kid"] for item in document["keys"]] == ["oa-key-a", "oa-key-b"]
    assert document["key_count"] == 2


def test_jwks_rejects_private_material_duplicate_and_bad_records() -> None:
    key = _key()
    private = {**key, "public_jwk": {**key["public_jwk"], "d": "secret"}}
    with pytest.raises(OaSignedTokenError, match="private key material"):
        build_jwks_document([private], at_epoch=430)
    with pytest.raises(OaSignedTokenError, match="duplicate key id"):
        build_jwks_document([key, key], at_epoch=430)
    with pytest.raises(OaSignedTokenError, match="state is invalid"):
        build_jwks_document([{**key, "state": "BAD"}], at_epoch=430)
    with pytest.raises(OaSignedTokenError, match="public JWK is invalid"):
        build_jwks_document([{**key, "public_jwk": None}], at_epoch=430)


def test_revocation_record_hashes_jti_and_expires() -> None:
    claims = {
        "iss": PRODUCTION_TOKEN_ISSUER,
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "jti": "private-jti",
        "token_use": "service_access",
        "exp": 900,
    }
    record = build_token_revocation_record(
        claims, reason_code="operator", now_epoch=600, revocation_id="rev-one"
    )

    assert record["jti_digest"] == digest_token_jti("private-jti")
    assert "private-jti" not in str(record)
    assert token_is_revoked(record, at_epoch=899) is True
    assert token_is_revoked(record, at_epoch=900) is False
    assert token_is_revoked(None, at_epoch=900) is False


@pytest.mark.parametrize(
    ("claims", "reason", "message"),
    [
        ({}, "OPERATOR", "incomplete"),
        ({"iss": "bad", "sub": "s", "aud": "a", "jti": "j", "token_use": "t", "exp": 9}, "OPERATOR", "issuer"),
        ({"iss": PRODUCTION_TOKEN_ISSUER, "sub": "s", "aud": "a", "jti": "j", "token_use": "t", "exp": 5}, "OPERATOR", "expired token"),
        ({"iss": PRODUCTION_TOKEN_ISSUER, "sub": "s", "aud": "a", "jti": "j", "token_use": "t", "exp": 9}, "UNKNOWN", "not supported"),
    ],
)
def test_revocation_rejects_invalid_claims_and_reasons(claims, reason, message) -> None:
    with pytest.raises(OaSignedTokenError, match=message):
        build_token_revocation_record(claims, reason_code=reason, now_epoch=5)


def test_normalizers_and_low_level_validation_fail_closed() -> None:
    assert normalize_signing_key_id("oa-key") == "oa-key"
    assert normalize_revocation_id("rev-key") == "rev-key"
    for value in (None, "", " spaced ", "UPPER"):
        with pytest.raises(OaSignedTokenError):
            normalize_signing_key_id(value)
    for value in (None, "", " x "):
        with pytest.raises(OaSignedTokenError):
            digest_token_jti(value)
    with pytest.raises(OaSignedTokenError, match="digest is invalid"):
        token_is_revoked({"jti_digest": "bad", "expires_at": 10}, at_epoch=1)
    with pytest.raises(OaSignedTokenError, match="must be positive"):
        token_is_revoked({"jti_digest": "0" * 64, "expires_at": 0}, at_epoch=0)
    with pytest.raises(OaSignedTokenError, match="non-negative integer"):
        build_jwks_document([], at_epoch=-1)


def test_domain_smoke_and_cli_paths(monkeypatch, capsys) -> None:
    evidence = domain_runner.run_oa_signed_token_domain()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert domain_runner.main(["--summary"]) == 0
    assert "domain=pass" in capsys.readouterr().out
    assert domain_runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        domain_runner,
        "run_oa_signed_token_domain",
        lambda: {"status": "FAIL", "next_slice": "blocked"},
    )
    assert domain_runner.main([]) == 1
