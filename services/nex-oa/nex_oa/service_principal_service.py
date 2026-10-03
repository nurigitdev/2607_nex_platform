from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from nex_oa.service_principal_repository import OaServicePrincipalRepository
from nex_oa.service_principals import (
    OaServicePrincipalError,
    plan_credential_issue,
    plan_credential_status_transition,
    normalize_service_principal_id,
    plan_service_principal_upsert,
)


OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION = "oa_service_principal_response.v1"
OA_SERVICE_CREDENTIAL_RESPONSE_SCHEMA_VERSION = "oa_service_credential_response.v1"
_CREDENTIAL_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_PUBLIC_PRINCIPAL_FIELDS = (
    "principal_schema_version",
    "principal_id",
    "service_id",
    "display_name",
    "status",
    "allowed_audiences",
    "allowed_scopes",
    "revision",
    "created_at",
    "updated_at",
)


@dataclass
class OaServicePrincipalService:
    repository: OaServicePrincipalRepository

    def upsert_principal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        principal_id = normalize_service_principal_id(payload.get("principal_id"))
        current = self.repository.get_principal(principal_id)
        planned = plan_service_principal_upsert(payload, current=current)
        stored = self.repository.save_principal(planned)
        return _principal_response(stored)

    def set_principal_status(
        self,
        principal_id: str,
        *,
        target_status: object,
        expected_revision: object,
    ) -> dict[str, Any]:
        normalized = normalize_service_principal_id(principal_id)
        current = self.repository.get_principal(normalized)
        if current is None:
            raise _not_found()
        planned = plan_service_principal_upsert(
            {
                **current,
                "status": target_status,
                "expected_revision": expected_revision,
            },
            current=current,
        )
        stored = self.repository.save_principal(planned)
        return _principal_response(stored)

    def get_principal(self, principal_id: str) -> dict[str, Any]:
        record = self.repository.get_principal(
            normalize_service_principal_id(principal_id)
        )
        if record is None:
            raise _not_found()
        return _principal_response(record)

    def list_principals(
        self, *, service_id: str | None = None
    ) -> dict[str, Any]:
        records = self.repository.list_principals(service_id=service_id)
        return {
            "response_schema_version": OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION,
            "items": [_principal_wire(item) for item in records],
            "count": len(records),
        }

    def issue_credential(
        self,
        principal_id: str,
        *,
        lifetime_days: object,
        now_epoch: int | None = None,
        credential_id: str | None = None,
        client_secret: str | None = None,
    ) -> dict[str, Any]:
        now = _now_epoch() if now_epoch is None else now_epoch
        principal = self.repository.get_principal(
            normalize_service_principal_id(principal_id)
        )
        if principal is None:
            raise _not_found()
        generated_id = credential_id or f"cred-{uuid4().hex}"
        secret = client_secret or token_urlsafe(32)
        count = self.repository.active_credential_count(
            principal_id=principal["principal_id"], at_epoch=now
        )
        planned = plan_credential_issue(
            {"credential_id": generated_id, "lifetime_days": lifetime_days},
            principal=principal,
            active_credential_count=count,
            now_epoch=now,
        )
        stored = self.repository.create_credential(
            {
                **planned,
                "secret_hash": _CREDENTIAL_HASHER.hash(secret),
                "secret_hint": secret[-6:],
            }
        )
        return _credential_response(stored, client_secret=secret)

    def rotate_credential(
        self,
        credential_id: str,
        *,
        expected_revision: object,
        lifetime_days: object,
        grace_seconds: object,
        now_epoch: int | None = None,
        new_credential_id: str | None = None,
        client_secret: str | None = None,
    ) -> dict[str, Any]:
        now = _now_epoch() if now_epoch is None else now_epoch
        current = self.repository.get_credential(credential_id)
        if current is None:
            raise _credential_not_found()
        principal = self.repository.get_principal(current["principal_id"])
        if principal is None:
            raise _not_found()
        transition = plan_credential_status_transition(
            current,
            target_status="ROTATING",
            expected_revision=expected_revision,
            now_epoch=now,
            grace_seconds=grace_seconds,
        )
        new_id = new_credential_id or f"cred-{uuid4().hex}"
        secret = client_secret or token_urlsafe(32)
        count = self.repository.active_credential_count(
            principal_id=current["principal_id"], at_epoch=now
        )
        issued = plan_credential_issue(
            {"credential_id": new_id, "lifetime_days": lifetime_days},
            principal=principal,
            active_credential_count=count,
            now_epoch=now,
        )
        previous, created = self.repository.rotate_credential(
            transition,
            {
                **issued,
                "secret_hash": _CREDENTIAL_HASHER.hash(secret),
                "secret_hint": secret[-6:],
            },
        )
        return {
            "response_schema_version": OA_SERVICE_CREDENTIAL_RESPONSE_SCHEMA_VERSION,
            "rotated_credential": _credential_wire(previous),
            "credential": _credential_wire(created),
            "client_secret": secret,
            "secret_display": "once",
        }

    def set_credential_status(
        self,
        credential_id: str,
        *,
        target_status: object,
        expected_revision: object,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        current = self.repository.get_credential(credential_id)
        if current is None:
            raise _credential_not_found()
        planned = plan_credential_status_transition(
            current,
            target_status=target_status,
            expected_revision=expected_revision,
            now_epoch=_now_epoch() if now_epoch is None else now_epoch,
        )
        return _credential_response(self.repository.save_credential(planned))

    def get_credential(self, credential_id: str) -> dict[str, Any]:
        record = self.repository.get_credential(credential_id)
        if record is None:
            raise _credential_not_found()
        return _credential_response(record)

    def list_credentials(self, principal_id: str) -> dict[str, Any]:
        records = self.repository.list_credentials(principal_id=principal_id)
        return {
            "response_schema_version": OA_SERVICE_CREDENTIAL_RESPONSE_SCHEMA_VERSION,
            "items": [_credential_wire(item) for item in records],
            "count": len(records),
        }

    def verify_client_secret(
        self,
        credential_id: str,
        client_secret: object,
        *,
        now_epoch: int | None = None,
    ) -> dict[str, str]:
        if not isinstance(client_secret, str) or not client_secret:
            raise _credential_rejected()
        record = self.repository.get_credential(credential_id)
        now = _now_epoch() if now_epoch is None else now_epoch
        if record is None or record["status"] not in {"ACTIVE", "ROTATING"}:
            raise _credential_rejected()
        if int(record["expires_at"]) <= now:
            raise _credential_rejected()
        if record["status"] == "ROTATING" and (
            record.get("grace_until") is None or int(record["grace_until"]) < now
        ):
            raise _credential_rejected()
        try:
            verified = _CREDENTIAL_HASHER.verify(record["secret_hash"], client_secret)
        except (InvalidHashError, VerificationError, VerifyMismatchError) as exc:
            raise _credential_rejected() from exc
        if not verified:
            raise _credential_rejected()
        principal = self.repository.get_principal(str(record["principal_id"]))
        if principal is None or principal["status"] != "ACTIVE":
            raise _credential_rejected()
        return {
            "principal_id": str(record["principal_id"]),
            "credential_id": str(record["credential_id"]),
        }

    def authenticate_client_credential(
        self,
        credential_id: str,
        client_secret: object,
        *,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        identity = self.verify_client_secret(
            credential_id,
            client_secret,
            now_epoch=now_epoch,
        )
        credential = self.repository.get_credential(identity["credential_id"])
        principal = self.repository.get_principal(identity["principal_id"])
        if credential is None or principal is None:
            raise _credential_rejected()
        return {
            **identity,
            "service_id": str(principal["service_id"]),
            "allowed_audiences": tuple(principal["allowed_audiences"]),
            "allowed_scopes": tuple(principal["allowed_scopes"]),
            "credential_revision": int(credential["revision"]),
        }


def _principal_response(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_schema_version": OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION,
        "principal": _principal_wire(record),
    }


def _credential_response(
    record: Mapping[str, Any], *, client_secret: str | None = None
) -> dict[str, Any]:
    response = {
        "response_schema_version": OA_SERVICE_CREDENTIAL_RESPONSE_SCHEMA_VERSION,
        "credential": _credential_wire(record),
    }
    if client_secret is not None:
        response.update(client_secret=client_secret, secret_display="once")
    return response


def _credential_wire(record: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "credential_schema_version",
        "credential_id",
        "principal_id",
        "secret_hint",
        "status",
        "issued_at",
        "expires_at",
        "grace_until",
        "last_used_at",
        "revision",
        "created_at",
        "updated_at",
    )
    return {field: record[field] for field in fields if field in record}


def _principal_wire(record: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        field: record[field]
        for field in _PUBLIC_PRINCIPAL_FIELDS
        if field in record
    }
    for field in ("allowed_audiences", "allowed_scopes"):
        if field in result:
            result[field] = list(result[field])
    return result


def _not_found() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        status_code=404,
        error_code="oa.service_principal_not_found",
        detail="service principal was not found.",
    )


def _credential_not_found() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        404,
        "oa.service_credential_not_found",
        "service credential was not found.",
    )


def _credential_rejected() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        401,
        "oa.service_credential_rejected",
        "service credential was rejected.",
    )


def _now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())
