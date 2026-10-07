from __future__ import annotations

from collections.abc import Mapping
from time import time
from typing import Any

from nex_oa.signed_token_repository import OaSignedTokenRepository
from nex_oa.signed_tokens import (
    OaSignedTokenError,
    build_jwks_document,
    build_signing_key_record,
    build_token_revocation_record,
    digest_token_jti,
    plan_signing_key_transition,
    token_is_revoked,
)

OA_SIGNING_KEY_RESPONSE_SCHEMA_VERSION = "oa_signing_key_response.v1"
OA_SIGNING_KEY_LIST_SCHEMA_VERSION = "oa_signing_key_list.v1"
OA_SIGNING_KEY_ROTATION_SCHEMA_VERSION = "oa_signing_key_rotation_response.v1"


class OaSigningKeyService:
    def __init__(
        self,
        *,
        repository: OaSignedTokenRepository,
        deployment_profile: str = "development",
    ) -> None:
        self.repository = repository
        self.deployment_profile = deployment_profile

    def register_key(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = build_signing_key_record(
            payload,
            deployment_profile=self.deployment_profile,
        )
        return _key_response(self.repository.save_signing_key(record))

    def set_key_state(
        self,
        key_id: str,
        *,
        target_state: object,
        expected_revision: object,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        current = self.repository.get_signing_key(key_id)
        if current is None:
            raise _key_not_found()
        planned = plan_signing_key_transition(
            current,
            target_state=target_state,
            expected_revision=expected_revision,
            now_epoch=_now_epoch() if now_epoch is None else now_epoch,
        )
        return _key_response(self.repository.save_signing_key(planned))

    def activate_rotation(
        self,
        previous_key_id: str,
        active_key_id: str,
        *,
        expected_previous_revision: object,
        expected_active_revision: object,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        if previous_key_id == active_key_id:
            raise OaSignedTokenError(
                "oa.signing_key_rotation_invalid",
                "rotation requires two distinct signing keys",
                400,
            )
        previous = self.repository.get_signing_key(previous_key_id)
        active = self.repository.get_signing_key(active_key_id)
        if previous is None or active is None:
            raise _key_not_found()
        if previous["issuer"] != active["issuer"]:
            raise OaSignedTokenError(
                "oa.signing_key_rotation_invalid",
                "rotation keys must have the same issuer",
                400,
            )
        now = _now_epoch() if now_epoch is None else now_epoch
        planned_previous = plan_signing_key_transition(
            previous,
            target_state="VERIFY_ONLY",
            expected_revision=expected_previous_revision,
            now_epoch=now,
        )
        planned_active = plan_signing_key_transition(
            active,
            target_state="ACTIVE",
            expected_revision=expected_active_revision,
            now_epoch=now,
        )
        stored_previous, stored_active = self.repository.rotate_signing_keys(
            planned_previous,
            planned_active,
        )
        return {
            "response_schema_version": OA_SIGNING_KEY_ROTATION_SCHEMA_VERSION,
            "previous_signing_key": _key_wire(stored_previous),
            "active_signing_key": _key_wire(stored_active),
        }

    def get_key(self, key_id: str) -> dict[str, Any]:
        record = self.repository.get_signing_key(key_id)
        if record is None:
            raise _key_not_found()
        return _key_response(record)

    def list_keys(self) -> dict[str, Any]:
        records = self.repository.list_signing_keys()
        return {
            "response_schema_version": OA_SIGNING_KEY_LIST_SCHEMA_VERSION,
            "items": [_key_wire(item) for item in records],
            "count": len(records),
        }

    def jwks(self, *, at_epoch: int | None = None) -> dict[str, Any]:
        return build_jwks_document(
            self.repository.list_signing_keys(),
            at_epoch=_now_epoch() if at_epoch is None else at_epoch,
        )

    def active_signing_key(self, *, at_epoch: int | None = None) -> dict[str, Any]:
        now = _now_epoch() if at_epoch is None else at_epoch
        active = [
            record
            for record in self.repository.list_signing_keys()
            if record["state"] == "ACTIVE"
            and int(record["activate_at"]) <= now < int(record["sign_until"])
        ]
        if len(active) != 1:
            raise OaSignedTokenError(
                "oa.active_signing_key_unavailable",
                "exactly one active signing key is required",
                503,
            )
        return active[0]

    def reconcile_key_states(self, *, now_epoch: int | None = None) -> dict[str, int]:
        now = _now_epoch() if now_epoch is None else now_epoch
        verify_only = 0
        retired = 0
        for record in self.repository.list_signing_keys():
            if record["state"] == "ACTIVE" and int(record["sign_until"]) <= now:
                record = plan_signing_key_transition(
                    record,
                    target_state="VERIFY_ONLY",
                    expected_revision=record["revision"],
                    now_epoch=now,
                )
                self.repository.save_signing_key(record)
                verify_only += 1
            if record["state"] == "VERIFY_ONLY" and int(record["verify_until"]) <= now:
                retired_record = plan_signing_key_transition(
                    record,
                    target_state="RETIRED",
                    expected_revision=record["revision"],
                    now_epoch=now,
                )
                self.repository.save_signing_key(retired_record)
                retired += 1
        return {"verify_only_count": verify_only, "retired_count": retired}

    def revoke_token_claims(
        self,
        claims: Mapping[str, Any],
        *,
        reason_code: object,
        now_epoch: int | None = None,
        revocation_id: str | None = None,
    ) -> dict[str, Any]:
        record = build_token_revocation_record(
            claims,
            reason_code=reason_code,
            now_epoch=_now_epoch() if now_epoch is None else now_epoch,
            revocation_id=revocation_id,
        )
        stored = self.repository.create_revocation(record)
        return {
            "revocation_schema_version": stored["revocation_schema_version"],
            "revocation_id": stored["revocation_id"],
            "subject_ref": stored["subject_ref"],
            "audience": stored["audience"],
            "token_use": stored["token_use"],
            "reason_code": stored["reason_code"],
            "revoked_at": stored["revoked_at"],
            "expires_at": stored["expires_at"],
        }

    def is_jti_revoked(self, jti: object, *, at_epoch: int | None = None) -> bool:
        record = self.repository.get_revocation_by_digest(digest_token_jti(jti))
        return token_is_revoked(
            record,
            at_epoch=_now_epoch() if at_epoch is None else at_epoch,
        )

    def purge_expired_revocations(self, *, at_epoch: int | None = None) -> int:
        return self.repository.purge_expired_revocations(
            at_epoch=_now_epoch() if at_epoch is None else at_epoch
        )


def _key_response(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_schema_version": OA_SIGNING_KEY_RESPONSE_SCHEMA_VERSION,
        "signing_key": _key_wire(record),
    }


def _key_wire(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: record[name]
        for name in (
            "signing_key_schema_version",
            "key_id",
            "issuer",
            "algorithm",
            "state",
            "public_jwk",
            "published_at",
            "activate_at",
            "sign_until",
            "verify_until",
            "revision",
        )
    }


def _key_not_found() -> OaSignedTokenError:
    return OaSignedTokenError("oa.signing_key_not_found", "signing key was not found", 404)


def _now_epoch() -> int:
    return int(time())
