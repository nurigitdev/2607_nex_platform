from __future__ import annotations

import base64

import nex_oa.signing_key_policy as signing_policy
from nex_oa.signing_key_policy import (
    MINIMUM_PUBLICATION_LEAD_SECONDS,
    MINIMUM_RSA_MODULUS_BITS,
    MINIMUM_VERIFICATION_OVERLAP_SECONDS,
    PRODUCTION_SIGNING_KEY_POLICY,
    allowed_key_transition,
    validate_signing_key_metadata,
)


def _modulus(bits: int = 3072) -> str:
    raw = bytes([0x80]) + bytes(bits // 8 - 1)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _metadata(**changes: object) -> dict[str, object]:
    key_id = changes.get("key_id", "oa-key-1")
    return {
        "key_id": key_id,
        "issuer": "urn:nex-platform:oa",
        "algorithm": "RS256",
        "state": "PREPUBLISHED",
        "public_jwk": {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": key_id,
            "n": _modulus(),
            "e": "AQAB",
        },
        "private_key_ref": "kms://nex-oa/signing/oa-key-1",
        "published_at": 1_000,
        "activate_at": 1_000 + MINIMUM_PUBLICATION_LEAD_SECONDS,
        "sign_until": 5_000,
        "verify_until": 5_000 + MINIMUM_VERIFICATION_OVERLAP_SECONDS,
        "revision": 1,
    } | changes


def test_signing_key_policy_freezes_algorithm_custody_and_rotation() -> None:
    policy = PRODUCTION_SIGNING_KEY_POLICY

    assert policy.algorithm == "RS256"
    assert policy.minimum_rsa_modulus_bits == MINIMUM_RSA_MODULUS_BITS == 3072
    assert policy.private_key_plaintext_database_allowed is False
    assert policy.one_active_signing_key_per_issuer is True
    assert policy.production_custody_schemes == ("kms", "pkcs11", "vault")
    assert policy.to_wire()["minimum_publication_lead_seconds"] == 330


def test_valid_production_and_test_metadata_pass() -> None:
    assert validate_signing_key_metadata(
        _metadata(), deployment_profile="production"
    ) == ()
    assert validate_signing_key_metadata(
        _metadata(private_key_ref="file:///tmp/oa-test-key.pem"),
        deployment_profile="test",
    ) == ()
    assert validate_signing_key_metadata(
        _metadata(private_key_ref="file:///tmp/oa-dev-key.pem"),
        deployment_profile="development",
    ) == ()


def test_key_state_transitions_are_one_way_and_emergency_revocable() -> None:
    assert allowed_key_transition("PREPUBLISHED", "ACTIVE") is True
    assert allowed_key_transition("PREPUBLISHED", "REVOKED") is True
    assert allowed_key_transition("ACTIVE", "VERIFY_ONLY") is True
    assert allowed_key_transition("ACTIVE", "REVOKED") is True
    assert allowed_key_transition("VERIFY_ONLY", "RETIRED") is True
    assert allowed_key_transition("VERIFY_ONLY", "REVOKED") is True
    assert allowed_key_transition("ACTIVE", "RETIRED") is False
    assert allowed_key_transition("RETIRED", "ACTIVE") is False
    assert allowed_key_transition("REVOKED", "ACTIVE") is False
    assert allowed_key_transition("UNKNOWN", "ACTIVE") is False


def test_missing_and_invalid_scalar_metadata_fails_closed() -> None:
    errors = validate_signing_key_metadata({}, deployment_profile="production")
    assert "metadata_missing:key_id" in errors
    assert "metadata_missing:verify_until" in errors

    errors = validate_signing_key_metadata(
        _metadata(
            key_id=" key ",
            issuer=1,
            algorithm="HS256",
            state="UNKNOWN",
            revision=True,
        ),
        deployment_profile="production",
    )
    assert "metadata_invalid:key_id" in errors
    assert "metadata_invalid:issuer" in errors
    assert "metadata_algorithm_forbidden" in errors
    assert "metadata_state_invalid" in errors
    assert "metadata_revision_invalid" in errors


def test_custody_reference_profiles_and_unsafe_locators_are_rejected() -> None:
    assert "private_key_custody_scheme_forbidden" in validate_signing_key_metadata(
        _metadata(private_key_ref="file:///tmp/key.pem"),
        deployment_profile="production",
    )
    assert "deployment_profile_invalid" in validate_signing_key_metadata(
        _metadata(), deployment_profile="staging"
    )
    assert "private_key_custody_locator_missing" in validate_signing_key_metadata(
        _metadata(private_key_ref="kms:"), deployment_profile="production"
    )
    assert "private_key_custody_locator_unsafe" in validate_signing_key_metadata(
        _metadata(private_key_ref="vault://user:secret@host/key?raw=yes#fragment"),
        deployment_profile="production",
    )


def test_public_jwk_rejects_private_material_metadata_and_weak_modulus() -> None:
    assert "public_jwk_invalid" in validate_signing_key_metadata(
        _metadata(public_jwk="not-a-jwk"), deployment_profile="production"
    )
    assert "public_jwk_invalid" in validate_signing_key_metadata(
        _metadata(public_jwk=None), deployment_profile="production"
    )

    bad_jwk = dict(_metadata()["public_jwk"]) | {
        "kty": "EC",
        "n": "not!base64",
        "e": "",
        "d": "private",
    }
    errors = validate_signing_key_metadata(
        _metadata(public_jwk=bad_jwk), deployment_profile="production"
    )
    assert "public_jwk_contains_private_material" in errors
    assert "public_jwk_metadata_invalid" in errors
    assert "public_jwk_member_invalid:e" in errors
    assert "public_jwk_modulus_encoding_invalid" in errors

    weak_jwk = dict(_metadata()["public_jwk"]) | {"n": _modulus(2048)}
    assert "public_jwk_modulus_too_small" in validate_signing_key_metadata(
        _metadata(public_jwk=weak_jwk), deployment_profile="production"
    )


def test_rotation_time_types_and_windows_are_rejected() -> None:
    errors = validate_signing_key_metadata(
        _metadata(published_at=True), deployment_profile="production"
    )
    assert "metadata_invalid:published_at" in errors

    errors = validate_signing_key_metadata(
        _metadata(activate_at=1_329, sign_until=1_329, verify_until=1_400),
        deployment_profile="production",
    )
    assert "key_publication_lead_too_short" in errors
    assert "key_signing_window_invalid" in errors
    assert "key_verification_overlap_too_short" in errors


def test_base64url_empty_modulus_is_too_small() -> None:
    empty_jwk = dict(_metadata()["public_jwk"]) | {"n": ""}
    errors = validate_signing_key_metadata(
        _metadata(public_jwk=empty_jwk), deployment_profile="production"
    )
    assert "public_jwk_member_invalid:n" in errors
    assert signing_policy._base64url_bit_length("") == 0

    invalid_jwk = dict(_metadata()["public_jwk"]) | {"n": "===="}
    errors = validate_signing_key_metadata(
        _metadata(public_jwk=invalid_jwk), deployment_profile="production"
    )
    assert "public_jwk_modulus_encoding_invalid" in errors
