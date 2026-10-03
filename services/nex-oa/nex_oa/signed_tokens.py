from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any
from uuid import uuid4

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signing_key_policy import (
    PRIVATE_JWK_MEMBERS,
    allowed_key_transition,
    validate_signing_key_metadata,
)


OA_SIGNING_KEY_SCHEMA_VERSION = "oa_signing_key.v1"
OA_TOKEN_REVOCATION_SCHEMA_VERSION = "oa_token_revocation.v1"
OA_JWKS_SCHEMA_VERSION = "oa_jwks.v1"
PUBLISHED_KEY_STATES = frozenset({"PREPUBLISHED", "ACTIVE", "VERIFY_ONLY"})
REVOCATION_REASON_CODES = frozenset(
    {"CREDENTIAL_REVOKED", "PRINCIPAL_DISABLED", "KEY_COMPROMISE", "OPERATOR"}
)
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class OaSignedTokenError(Exception):
    code: str
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def normalize_signing_key_id(value: object) -> str:
    return _normalize_identifier(value, field="key_id")


def build_signing_key_record(
    payload: Mapping[str, Any],
    *,
    deployment_profile: str,
) -> dict[str, Any]:
    allowed = {
        "key_id",
        "issuer",
        "public_jwk",
        "private_key_ref",
        "published_at",
        "activate_at",
        "sign_until",
        "verify_until",
    }
    _reject_unknown_fields(payload, allowed)
    key_id = normalize_signing_key_id(payload.get("key_id"))
    record = {
        "signing_key_schema_version": OA_SIGNING_KEY_SCHEMA_VERSION,
        "key_id": key_id,
        "issuer": payload.get("issuer"),
        "algorithm": "RS256",
        "state": "PREPUBLISHED",
        "public_jwk": deepcopy(payload.get("public_jwk")),
        "private_key_ref": payload.get("private_key_ref"),
        "published_at": payload.get("published_at"),
        "activate_at": payload.get("activate_at"),
        "sign_until": payload.get("sign_until"),
        "verify_until": payload.get("verify_until"),
        "revision": 1,
        "previous_revision": 0,
    }
    if record["issuer"] != PRODUCTION_TOKEN_ISSUER:
        raise _invalid("issuer must be the canonical OA issuer")
    errors = validate_signing_key_metadata(
        {
            **record,
            "public_jwk": record["public_jwk"],
        },
        deployment_profile=deployment_profile,
    )
    if errors:
        raise _invalid("signing key metadata rejected", detail=errors)
    return record


def plan_signing_key_transition(
    record: Mapping[str, Any],
    *,
    target_state: object,
    expected_revision: object,
    now_epoch: int,
) -> dict[str, Any]:
    current = _validated_key_record(record)
    target = _nonempty_string(target_state, field="target_state").upper()
    revision = _positive_integer(expected_revision, field="expected_revision")
    now = _nonnegative_integer(now_epoch, field="now_epoch")
    if revision != current["revision"]:
        raise OaSignedTokenError("oa.signing_key_revision_conflict", "signing key revision conflict", 409)
    if not allowed_key_transition(current["state"], target):
        raise OaSignedTokenError("oa.signing_key_transition_invalid", "signing key transition is not allowed", 409)
    if target == "ACTIVE" and now < current["activate_at"]:
        raise OaSignedTokenError("oa.signing_key_activation_early", "signing key activation time has not arrived", 409)
    if target == "RETIRED" and now < current["verify_until"]:
        raise OaSignedTokenError("oa.signing_key_retirement_early", "signing key verification window is open", 409)
    return {
        **current,
        "state": target,
        "revision": revision + 1,
        "previous_revision": revision,
    }


def build_jwks_document(
    records: Iterable[Mapping[str, Any]], *, at_epoch: int
) -> dict[str, Any]:
    now = _nonnegative_integer(at_epoch, field="at_epoch")
    keys: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        record = _validated_key_record(raw)
        if record["state"] not in PUBLISHED_KEY_STATES or record["verify_until"] <= now:
            continue
        public_jwk = deepcopy(record["public_jwk"])
        if PRIVATE_JWK_MEMBERS.intersection(public_jwk):
            raise _invalid("JWKS cannot contain private key material")
        kid = public_jwk["kid"]
        if kid in seen:
            raise OaSignedTokenError("oa.jwks_duplicate_kid", "JWKS contains a duplicate key id", 409)
        seen.add(kid)
        keys.append(public_jwk)
    keys.sort(key=lambda item: item["kid"])
    return {
        "jwks_schema_version": OA_JWKS_SCHEMA_VERSION,
        "issuer": PRODUCTION_TOKEN_ISSUER,
        "keys": keys,
        "key_count": len(keys),
    }


def build_token_revocation_record(
    claims: Mapping[str, Any],
    *,
    reason_code: object,
    now_epoch: int,
    revocation_id: str | None = None,
) -> dict[str, Any]:
    required = ("iss", "sub", "aud", "jti", "token_use", "exp")
    if any(name not in claims for name in required):
        raise _invalid("token claims are incomplete")
    issuer = _nonempty_string(claims["iss"], field="iss")
    if issuer != PRODUCTION_TOKEN_ISSUER:
        raise _invalid("token issuer is invalid")
    subject = _nonempty_string(claims["sub"], field="sub")
    audience = _nonempty_string(claims["aud"], field="aud")
    token_use = _nonempty_string(claims["token_use"], field="token_use")
    jti = _nonempty_string(claims["jti"], field="jti")
    expires_at = _positive_integer(claims["exp"], field="exp")
    revoked_at = _nonnegative_integer(now_epoch, field="now_epoch")
    if expires_at <= revoked_at:
        raise OaSignedTokenError("oa.token_already_expired", "expired token does not need revocation", 409)
    reason = _nonempty_string(reason_code, field="reason_code").upper()
    if reason not in REVOCATION_REASON_CODES:
        raise _invalid("revocation reason is not supported")
    return {
        "revocation_schema_version": OA_TOKEN_REVOCATION_SCHEMA_VERSION,
        "revocation_id": normalize_revocation_id(revocation_id or f"rev-{uuid4().hex}"),
        "jti_digest": digest_token_jti(jti),
        "issuer": issuer,
        "subject_ref": subject,
        "audience": audience,
        "token_use": token_use,
        "reason_code": reason,
        "revoked_at": revoked_at,
        "expires_at": expires_at,
    }


def normalize_revocation_id(value: object) -> str:
    return _normalize_identifier(value, field="revocation_id")


def digest_token_jti(jti: object) -> str:
    normalized = _nonempty_string(jti, field="jti")
    return sha256(normalized.encode("utf-8")).hexdigest()


def token_is_revoked(record: Mapping[str, Any] | None, *, at_epoch: int) -> bool:
    now = _nonnegative_integer(at_epoch, field="at_epoch")
    if record is None:
        return False
    digest = record.get("jti_digest")
    if not isinstance(digest, str) or _SHA256_HEX.fullmatch(digest) is None:
        raise _invalid("revocation digest is invalid")
    expires_at = _positive_integer(record.get("expires_at"), field="expires_at")
    return expires_at > now


def _validated_key_record(record: Mapping[str, Any]) -> dict[str, Any]:
    copied = deepcopy(dict(record))
    normalize_signing_key_id(copied.get("key_id"))
    for name in ("published_at", "activate_at", "sign_until", "verify_until"):
        copied[name] = _nonnegative_integer(copied.get(name), field=name)
    copied["revision"] = _positive_integer(copied.get("revision"), field="revision")
    state = _nonempty_string(copied.get("state"), field="state").upper()
    if state not in {"PREPUBLISHED", "ACTIVE", "VERIFY_ONLY", "RETIRED", "REVOKED"}:
        raise _invalid("signing key state is invalid")
    copied["state"] = state
    if not isinstance(copied.get("public_jwk"), Mapping):
        raise _invalid("public JWK is invalid")
    copied["public_jwk"] = deepcopy(dict(copied["public_jwk"]))
    return copied


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _invalid(f"unsupported fields: {', '.join(unknown)}")


def _normalize_identifier(value: object, *, field: str) -> str:
    normalized = _nonempty_string(value, field=field)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise _invalid(f"{field} is invalid")
    return normalized


def _nonempty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{field} must be a non-empty string")
    return value


def _nonnegative_integer(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _invalid(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, *, field: str) -> int:
    parsed = _nonnegative_integer(value, field=field)
    if parsed == 0:
        raise _invalid(f"{field} must be positive")
    return parsed


def _invalid(message: str, *, detail: tuple[str, ...] = ()) -> OaSignedTokenError:
    suffix = f": {', '.join(detail)}" if detail else ""
    return OaSignedTokenError("oa.signed_token_invalid", message + suffix, 400)


def build_test_public_jwk(key_id: str = "oa-key-test") -> dict[str, str]:
    modulus = b"\x80" + (b"\x00" * 383)
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": base64.urlsafe_b64encode(modulus).rstrip(b"=").decode("ascii"),
        "e": "AQAB",
    }
