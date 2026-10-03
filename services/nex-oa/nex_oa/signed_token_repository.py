from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.signed_tokens import (
    OaSignedTokenError,
    normalize_revocation_id,
    normalize_signing_key_id,
)
from nex_runtime import PERSISTENCE_MODE_POSTGRES, ServicePersistenceRuntime


class OaSignedTokenRepository(Protocol):
    def save_signing_key(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_signing_key(self, key_id: str) -> dict[str, Any] | None: ...
    def list_signing_keys(self) -> list[dict[str, Any]]: ...
    def create_revocation(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_revocation_by_digest(self, jti_digest: str) -> dict[str, Any] | None: ...
    def purge_expired_revocations(self, *, at_epoch: int) -> int: ...


class InMemoryOaSignedTokenRepository:
    def __init__(self) -> None:
        self.signing_keys: dict[str, dict[str, Any]] = {}
        self.revocations: dict[str, dict[str, Any]] = {}

    def save_signing_key(self, record: Mapping[str, Any]) -> dict[str, Any]:
        key_id = normalize_signing_key_id(record.get("key_id"))
        current = self.signing_keys.get(key_id)
        previous = int(record.get("previous_revision") or 0)
        if (int(current["revision"]) if current else 0) != previous:
            raise _revision_conflict()
        if record.get("state") == "ACTIVE" and any(
            item["key_id"] != key_id
            and item["issuer"] == record.get("issuer")
            and item["state"] == "ACTIVE"
            for item in self.signing_keys.values()
        ):
            raise _active_key_conflict()
        stored = deepcopy(dict(record))
        self.signing_keys[key_id] = stored
        return deepcopy(stored)

    def get_signing_key(self, key_id: str) -> dict[str, Any] | None:
        record = self.signing_keys.get(normalize_signing_key_id(key_id))
        return deepcopy(record) if record is not None else None

    def list_signing_keys(self) -> list[dict[str, Any]]:
        return [
            deepcopy(item)
            for item in sorted(
                self.signing_keys.values(), key=lambda value: value["key_id"]
            )
        ]

    def create_revocation(self, record: Mapping[str, Any]) -> dict[str, Any]:
        revocation_id = normalize_revocation_id(record.get("revocation_id"))
        digest = _normalize_digest(record.get("jti_digest"))
        if revocation_id in self.revocations or any(
            item["jti_digest"] == digest for item in self.revocations.values()
        ):
            raise _revocation_conflict()
        stored = deepcopy(dict(record))
        self.revocations[revocation_id] = stored
        return deepcopy(stored)

    def get_revocation_by_digest(self, jti_digest: str) -> dict[str, Any] | None:
        normalized = _normalize_digest(jti_digest)
        for record in self.revocations.values():
            if record["jti_digest"] == normalized:
                return deepcopy(record)
        return None

    def purge_expired_revocations(self, *, at_epoch: int) -> int:
        expired = [
            revocation_id
            for revocation_id, record in self.revocations.items()
            if int(record["expires_at"]) <= int(at_epoch)
        ]
        for revocation_id in expired:
            del self.revocations[revocation_id]
        return len(expired)


class SqlAlchemyOaSignedTokenRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_signing_key(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _key_params(record)
        previous = int(record.get("previous_revision") or 0)
        session = self._session_factory()
        try:
            if previous == 0:
                session.execute(
                    text(
                        "INSERT INTO oa_signing_keys ("
                        "key_id, signing_key_schema_version, issuer, algorithm, state, "
                        "public_jwk, private_key_ref, published_at, activate_at, sign_until, "
                        "verify_until, revision) VALUES ("
                        ":key_id, :signing_key_schema_version, :issuer, :algorithm, :state, "
                        f"{_json_value(session, 'public_jwk')}, :private_key_ref, :published_at, "
                        ":activate_at, :sign_until, :verify_until, :revision)"
                    ),
                    params,
                )
            else:
                result = session.execute(
                    text(
                        "UPDATE oa_signing_keys SET state = :state, revision = :revision, "
                        "updated_at = :updated_at WHERE key_id = :key_id "
                        "AND revision = :previous_revision"
                    ),
                    {
                        "key_id": params["key_id"],
                        "state": params["state"],
                        "revision": params["revision"],
                        "previous_revision": previous,
                        "updated_at": _utc_now(),
                    },
                )
                if result.rowcount != 1:
                    raise _revision_conflict()
            session.commit()
            return deepcopy(dict(record))
        except OaSignedTokenError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _active_key_conflict() from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def get_signing_key(self, key_id: str) -> dict[str, Any] | None:
        rows = self._read(
            "SELECT * FROM oa_signing_keys WHERE key_id = :key_id",
            {"key_id": normalize_signing_key_id(key_id)},
            json_columns=("public_jwk",),
            timestamp_columns=("published_at", "activate_at", "sign_until", "verify_until"),
        )
        return rows[0] if rows else None

    def list_signing_keys(self) -> list[dict[str, Any]]:
        return self._read(
            "SELECT * FROM oa_signing_keys ORDER BY key_id",
            {},
            json_columns=("public_jwk",),
            timestamp_columns=("published_at", "activate_at", "sign_until", "verify_until"),
        )

    def create_revocation(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _revocation_params(record)
        session = self._session_factory()
        try:
            session.execute(
                text(
                    "INSERT INTO oa_token_revocations ("
                    "revocation_id, revocation_schema_version, jti_digest, issuer, "
                    "subject_ref, audience, token_use, reason_code, revoked_at, expires_at"
                    ") VALUES ("
                    ":revocation_id, :revocation_schema_version, :jti_digest, :issuer, "
                    ":subject_ref, :audience, :token_use, :reason_code, :revoked_at, :expires_at)"
                ),
                params,
            )
            session.commit()
            return deepcopy(dict(record))
        except IntegrityError as exc:
            session.rollback()
            raise _revocation_conflict() from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def get_revocation_by_digest(self, jti_digest: str) -> dict[str, Any] | None:
        rows = self._read(
            "SELECT * FROM oa_token_revocations WHERE jti_digest = :jti_digest",
            {"jti_digest": _normalize_digest(jti_digest)},
            timestamp_columns=("revoked_at", "expires_at"),
        )
        return rows[0] if rows else None

    def purge_expired_revocations(self, *, at_epoch: int) -> int:
        session = self._session_factory()
        try:
            result = session.execute(
                text("DELETE FROM oa_token_revocations WHERE expires_at <= :at_time"),
                {"at_time": _timestamp(at_epoch)},
            )
            session.commit()
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def _read(
        self,
        sql: str,
        params: Mapping[str, Any],
        *,
        json_columns: tuple[str, ...] = (),
        timestamp_columns: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                return [
                    _decode_row(row, json_columns, timestamp_columns)
                    for row in session.execute(text(sql), dict(params)).mappings()
                ]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def build_signed_token_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaSignedTokenRepository:
    if runtime.mode == PERSISTENCE_MODE_POSTGRES and runtime.api_session_factory is not None:
        return SqlAlchemyOaSignedTokenRepository(runtime.api_session_factory)
    return InMemoryOaSignedTokenRepository()


def _key_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key_id": normalize_signing_key_id(record.get("key_id")),
        "signing_key_schema_version": record["signing_key_schema_version"],
        "issuer": record["issuer"],
        "algorithm": record["algorithm"],
        "state": record["state"],
        "public_jwk": json.dumps(record["public_jwk"], sort_keys=True),
        "private_key_ref": record["private_key_ref"],
        "published_at": _timestamp(record["published_at"]),
        "activate_at": _timestamp(record["activate_at"]),
        "sign_until": _timestamp(record["sign_until"]),
        "verify_until": _timestamp(record["verify_until"]),
        "revision": int(record["revision"]),
    }


def _revocation_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "revocation_id": normalize_revocation_id(record.get("revocation_id")),
        "revocation_schema_version": record["revocation_schema_version"],
        "jti_digest": _normalize_digest(record.get("jti_digest")),
        "issuer": record["issuer"],
        "subject_ref": record["subject_ref"],
        "audience": record["audience"],
        "token_use": record["token_use"],
        "reason_code": record["reason_code"],
        "revoked_at": _timestamp(record["revoked_at"]),
        "expires_at": _timestamp(record["expires_at"]),
    }


def _decode_row(
    row: Mapping[str, Any],
    json_columns: tuple[str, ...],
    timestamp_columns: tuple[str, ...],
) -> dict[str, Any]:
    result = dict(row)
    for column in json_columns:
        if isinstance(result.get(column), str):
            result[column] = json.loads(result[column])
    for column in timestamp_columns:
        if result.get(column) is not None:
            result[column] = _epoch(result[column])
    return result


def _json_value(session: Session, parameter: str) -> str:
    return f"CAST(:{parameter} AS JSONB)" if session.bind.dialect.name == "postgresql" else f":{parameter}"


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(int(value), tz=UTC)


def _epoch(value: object) -> int:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(normalized.timestamp())
    return int(value)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise OaSignedTokenError("oa.revocation_digest_invalid", "revocation digest is invalid", 400)
    return value


def _revision_conflict() -> OaSignedTokenError:
    return OaSignedTokenError("oa.signing_key_revision_conflict", "signing key revision conflict", 409)


def _active_key_conflict() -> OaSignedTokenError:
    return OaSignedTokenError("oa.active_signing_key_conflict", "issuer already has an active signing key", 409)


def _revocation_conflict() -> OaSignedTokenError:
    return OaSignedTokenError("oa.token_revocation_conflict", "token revocation already exists", 409)


def _unavailable() -> OaSignedTokenError:
    return OaSignedTokenError("oa.signed_token_repository_unavailable", "signed-token persistence is unavailable", 503)
