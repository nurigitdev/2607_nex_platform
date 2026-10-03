from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit


SIGNING_ALGORITHM = "RS256"
ALLOWED_SIGNING_ALGORITHMS = frozenset({SIGNING_ALGORITHM})
MINIMUM_RSA_MODULUS_BITS = 3072
MINIMUM_PUBLICATION_LEAD_SECONDS = 330
MINIMUM_VERIFICATION_OVERLAP_SECONDS = 330
KEY_STATES = (
    "PREPUBLISHED",
    "ACTIVE",
    "VERIFY_ONLY",
    "RETIRED",
    "REVOKED",
)
PRIVATE_JWK_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})
PRODUCTION_CUSTODY_SCHEMES = frozenset({"kms", "vault", "pkcs11"})
TEST_CUSTODY_SCHEMES = PRODUCTION_CUSTODY_SCHEMES | {"file"}


@dataclass(frozen=True)
class SigningKeyPolicy:
    algorithm: str
    minimum_rsa_modulus_bits: int
    key_states: tuple[str, ...]
    minimum_publication_lead_seconds: int
    minimum_verification_overlap_seconds: int
    production_custody_schemes: tuple[str, ...]
    test_custody_schemes: tuple[str, ...]
    private_key_plaintext_database_allowed: bool
    one_active_signing_key_per_issuer: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


PRODUCTION_SIGNING_KEY_POLICY = SigningKeyPolicy(
    algorithm=SIGNING_ALGORITHM,
    minimum_rsa_modulus_bits=MINIMUM_RSA_MODULUS_BITS,
    key_states=KEY_STATES,
    minimum_publication_lead_seconds=MINIMUM_PUBLICATION_LEAD_SECONDS,
    minimum_verification_overlap_seconds=MINIMUM_VERIFICATION_OVERLAP_SECONDS,
    production_custody_schemes=tuple(sorted(PRODUCTION_CUSTODY_SCHEMES)),
    test_custody_schemes=tuple(sorted(TEST_CUSTODY_SCHEMES)),
    private_key_plaintext_database_allowed=False,
    one_active_signing_key_per_issuer=True,
)

_ALLOWED_TRANSITIONS = {
    "PREPUBLISHED": frozenset({"ACTIVE", "REVOKED"}),
    "ACTIVE": frozenset({"VERIFY_ONLY", "REVOKED"}),
    "VERIFY_ONLY": frozenset({"RETIRED", "REVOKED"}),
    "RETIRED": frozenset(),
    "REVOKED": frozenset(),
}
_REQUIRED_METADATA = (
    "key_id",
    "issuer",
    "algorithm",
    "state",
    "public_jwk",
    "private_key_ref",
    "published_at",
    "activate_at",
    "sign_until",
    "verify_until",
    "revision",
)


def allowed_key_transition(current_state: str, target_state: str) -> bool:
    return target_state in _ALLOWED_TRANSITIONS.get(current_state, frozenset())


def validate_signing_key_metadata(
    metadata: Mapping[str, Any],
    *,
    deployment_profile: str,
) -> tuple[str, ...]:
    errors: list[str] = []
    for name in _REQUIRED_METADATA:
        if name not in metadata:
            errors.append(f"metadata_missing:{name}")

    for name in ("key_id", "issuer", "algorithm", "state", "private_key_ref"):
        if name in metadata and not _nonempty_string(metadata[name]):
            errors.append(f"metadata_invalid:{name}")
    if "algorithm" in metadata and metadata.get("algorithm") not in ALLOWED_SIGNING_ALGORITHMS:
        errors.append("metadata_algorithm_forbidden")
    if "state" in metadata and metadata.get("state") not in KEY_STATES:
        errors.append("metadata_state_invalid")
    if "revision" in metadata and not _positive_integer(metadata["revision"]):
        errors.append("metadata_revision_invalid")

    _validate_custody_reference(
        metadata.get("private_key_ref"),
        deployment_profile,
        errors,
    )
    _validate_public_jwk(metadata.get("public_jwk"), metadata.get("key_id"), errors)
    _validate_rotation_times(metadata, errors)
    return tuple(errors)


def _validate_custody_reference(
    value: Any,
    deployment_profile: str,
    errors: list[str],
) -> None:
    if deployment_profile == "production":
        allowed_schemes = PRODUCTION_CUSTODY_SCHEMES
    elif deployment_profile in {"test", "development"}:
        allowed_schemes = TEST_CUSTODY_SCHEMES
    else:
        errors.append("deployment_profile_invalid")
        return
    if not _nonempty_string(value):
        return
    parsed = urlsplit(value)
    if parsed.scheme not in allowed_schemes:
        errors.append("private_key_custody_scheme_forbidden")
    if not (parsed.netloc or parsed.path):
        errors.append("private_key_custody_locator_missing")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        errors.append("private_key_custody_locator_unsafe")


def _validate_public_jwk(
    value: Any,
    key_id: Any,
    errors: list[str],
) -> None:
    if not isinstance(value, Mapping):
        errors.append("public_jwk_invalid")
        return
    if PRIVATE_JWK_MEMBERS.intersection(value):
        errors.append("public_jwk_contains_private_material")
    expected = {
        "kty": "RSA",
        "use": "sig",
        "alg": SIGNING_ALGORITHM,
        "kid": key_id,
    }
    if any(value.get(name) != expected_value for name, expected_value in expected.items()):
        errors.append("public_jwk_metadata_invalid")
    for name in ("n", "e"):
        if not _nonempty_string(value.get(name)):
            errors.append(f"public_jwk_member_invalid:{name}")
    modulus = value.get("n")
    if _nonempty_string(modulus):
        bits = _base64url_bit_length(modulus)
        if bits is None:
            errors.append("public_jwk_modulus_encoding_invalid")
        elif bits < MINIMUM_RSA_MODULUS_BITS:
            errors.append("public_jwk_modulus_too_small")


def _validate_rotation_times(
    metadata: Mapping[str, Any], errors: list[str]
) -> None:
    names = ("published_at", "activate_at", "sign_until", "verify_until")
    for name in names:
        if name in metadata and not _integer(metadata[name]):
            errors.append(f"metadata_invalid:{name}")
    if not all(_integer(metadata.get(name)) for name in names):
        return
    published_at = metadata["published_at"]
    activate_at = metadata["activate_at"]
    sign_until = metadata["sign_until"]
    verify_until = metadata["verify_until"]
    if activate_at - published_at < MINIMUM_PUBLICATION_LEAD_SECONDS:
        errors.append("key_publication_lead_too_short")
    if sign_until <= activate_at:
        errors.append("key_signing_window_invalid")
    if verify_until - sign_until < MINIMUM_VERIFICATION_OVERLAP_SECONDS:
        errors.append("key_verification_overlap_too_short")


def _base64url_bit_length(value: str) -> int | None:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return None
    if not raw:
        return 0
    return (len(raw) - 1) * 8 + raw[0].bit_length()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_integer(value: Any) -> bool:
    return _integer(value) and value > 0
