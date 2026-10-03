from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.service_principal_boundary import MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS
from nex_oa.service_principals import (
    OaServicePrincipalError,
    normalize_credential_id,
    normalize_service_id,
    normalize_service_principal_id,
)
from nex_runtime import PERSISTENCE_MODE_POSTGRES, ServicePersistenceRuntime


class OaServicePrincipalRepository(Protocol):
    def save_principal(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_principal(self, principal_id: str) -> dict[str, Any] | None: ...
    def list_principals(
        self, *, service_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    def create_credential(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def save_credential(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_credential(self, credential_id: str) -> dict[str, Any] | None: ...
    def list_credentials(self, *, principal_id: str) -> list[dict[str, Any]]: ...
    def active_credential_count(self, *, principal_id: str, at_epoch: int) -> int: ...


class InMemoryOaServicePrincipalRepository:
    def __init__(self) -> None:
        self.principals: dict[str, dict[str, Any]] = {}
        self.credentials: dict[str, dict[str, Any]] = {}

    def save_principal(self, record: Mapping[str, Any]) -> dict[str, Any]:
        principal_id = normalize_service_principal_id(record.get("principal_id"))
        current = self.principals.get(principal_id)
        expected = int(record.get("previous_revision") or 0)
        if (int(current["revision"]) if current else 0) != expected:
            raise _revision_conflict("service principal")
        stored = deepcopy(dict(record))
        self.principals[principal_id] = stored
        return deepcopy(stored)

    def get_principal(self, principal_id: str) -> dict[str, Any] | None:
        record = self.principals.get(normalize_service_principal_id(principal_id))
        return deepcopy(record) if record is not None else None

    def list_principals(
        self, *, service_id: str | None = None
    ) -> list[dict[str, Any]]:
        normalized = normalize_service_id(service_id) if service_id is not None else None
        return [
            deepcopy(item)
            for item in sorted(
                self.principals.values(), key=lambda value: value["principal_id"]
            )
            if normalized is None or item["service_id"] == normalized
        ]

    def create_credential(self, record: Mapping[str, Any]) -> dict[str, Any]:
        credential_id = normalize_credential_id(record.get("credential_id"))
        principal_id = normalize_service_principal_id(record.get("principal_id"))
        if principal_id not in self.principals:
            raise _not_found("service principal")
        if credential_id in self.credentials:
            raise _conflict("credential already exists")
        if self.active_credential_count(
            principal_id=principal_id, at_epoch=int(record["issued_at"])
        ) >= MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS:
            raise _active_limit()
        stored = deepcopy(dict(record))
        self.credentials[credential_id] = stored
        return deepcopy(stored)

    def save_credential(self, record: Mapping[str, Any]) -> dict[str, Any]:
        credential_id = normalize_credential_id(record.get("credential_id"))
        current = self.credentials.get(credential_id)
        if current is None:
            raise _not_found("credential")
        if int(current["revision"]) != int(record.get("previous_revision") or 0):
            raise _revision_conflict("credential")
        current.update(deepcopy(dict(record)))
        return deepcopy(current)

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        record = self.credentials.get(normalize_credential_id(credential_id))
        return deepcopy(record) if record is not None else None

    def list_credentials(self, *, principal_id: str) -> list[dict[str, Any]]:
        normalized = normalize_service_principal_id(principal_id)
        return [
            deepcopy(item)
            for item in sorted(
                self.credentials.values(), key=lambda value: value["credential_id"]
            )
            if item["principal_id"] == normalized
        ]

    def active_credential_count(self, *, principal_id: str, at_epoch: int) -> int:
        normalized = normalize_service_principal_id(principal_id)
        return sum(
            item["principal_id"] == normalized
            and item["status"] in {"ACTIVE", "ROTATING"}
            and int(item["expires_at"]) > at_epoch
            for item in self.credentials.values()
        )


class SqlAlchemyOaServicePrincipalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_principal(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _principal_params(record)
        previous = int(record.get("previous_revision") or 0)
        session = self._session_factory()
        try:
            if previous == 0:
                session.execute(
                    text(
                        "INSERT INTO oa_service_principals ("
                        "principal_id, principal_schema_version, service_id, display_name, "
                        "status, allowed_audiences, allowed_scopes, revision"
                        ") VALUES ("
                        ":principal_id, :principal_schema_version, :service_id, :display_name, "
                        f":status, {_json_value(session, 'allowed_audiences')}, "
                        f"{_json_value(session, 'allowed_scopes')}, :revision)"
                    ),
                    params,
                )
            else:
                result = session.execute(
                    text(
                        "UPDATE oa_service_principals SET display_name = :display_name, "
                        "status = :status, "
                        f"allowed_audiences = {_json_value(session, 'allowed_audiences')}, "
                        f"allowed_scopes = {_json_value(session, 'allowed_scopes')}, "
                        "revision = :revision, updated_at = :updated_at "
                        "WHERE principal_id = :principal_id AND revision = :previous_revision"
                    ),
                    {**params, "previous_revision": previous, "updated_at": _utc_now()},
                )
                if result.rowcount != 1:
                    raise _revision_conflict("service principal")
            session.commit()
            return deepcopy(dict(record))
        except OaServicePrincipalError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _conflict("service principal conflicts with persisted state") from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def get_principal(self, principal_id: str) -> dict[str, Any] | None:
        normalized = normalize_service_principal_id(principal_id)
        return self._read_one(
            "SELECT * FROM oa_service_principals WHERE principal_id = :principal_id",
            {"principal_id": normalized},
            json_columns=("allowed_audiences", "allowed_scopes"),
        )

    def list_principals(
        self, *, service_id: str | None = None
    ) -> list[dict[str, Any]]:
        if service_id is None:
            sql = "SELECT * FROM oa_service_principals ORDER BY principal_id"
            params: dict[str, Any] = {}
        else:
            sql = (
                "SELECT * FROM oa_service_principals WHERE service_id = :service_id "
                "ORDER BY principal_id"
            )
            params = {"service_id": normalize_service_id(service_id)}
        return self._read_many(
            sql, params, json_columns=("allowed_audiences", "allowed_scopes")
        )

    def create_credential(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _credential_params(record)
        principal_id = params["principal_id"]
        session = self._session_factory()
        try:
            lock = _principal_lock_suffix(session)
            principal = session.execute(
                text(
                    "SELECT principal_id FROM oa_service_principals "
                    "WHERE principal_id = :principal_id" + lock
                ),
                {"principal_id": principal_id},
            ).first()
            if principal is None:
                raise _not_found("service principal")
            count = session.execute(
                text(
                    "SELECT COUNT(*) FROM oa_service_creds "
                    "WHERE principal_id = :principal_id "
                    "AND status IN ('ACTIVE', 'ROTATING') AND expires_at > :issued_at"
                ),
                {"principal_id": principal_id, "issued_at": params["issued_at"]},
            ).scalar_one()
            if int(count) >= MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS:
                raise _active_limit()
            session.execute(
                text(
                    "INSERT INTO oa_service_creds ("
                    "credential_id, credential_schema_version, principal_id, secret_hash, "
                    "secret_hint, status, issued_at, expires_at, grace_until, revision"
                    ") VALUES ("
                    ":credential_id, :credential_schema_version, :principal_id, :secret_hash, "
                    ":secret_hint, :status, :issued_at, :expires_at, :grace_until, :revision)"
                ),
                params,
            )
            session.commit()
            return deepcopy(dict(record))
        except OaServicePrincipalError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _conflict("credential conflicts with persisted state") from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def save_credential(self, record: Mapping[str, Any]) -> dict[str, Any]:
        credential_id = normalize_credential_id(record.get("credential_id"))
        previous = int(record.get("previous_revision") or 0)
        session = self._session_factory()
        try:
            result = session.execute(
                text(
                    "UPDATE oa_service_creds SET status = :status, "
                    "grace_until = :grace_until, revision = :revision, "
                    "updated_at = :updated_at WHERE credential_id = :credential_id "
                    "AND revision = :previous_revision"
                ),
                {
                    "credential_id": credential_id,
                    "status": record["status"],
                    "grace_until": _timestamp(record.get("grace_until")),
                    "revision": int(record["revision"]),
                    "previous_revision": previous,
                    "updated_at": _utc_now(),
                },
            )
            if result.rowcount != 1:
                raise _revision_conflict("credential")
            session.commit()
            return deepcopy(dict(record))
        except OaServicePrincipalError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        normalized = normalize_credential_id(credential_id)
        return self._read_one(
            "SELECT * FROM oa_service_creds WHERE credential_id = :credential_id",
            {"credential_id": normalized},
            timestamp_columns=("issued_at", "expires_at", "grace_until", "last_used_at"),
        )

    def list_credentials(self, *, principal_id: str) -> list[dict[str, Any]]:
        normalized = normalize_service_principal_id(principal_id)
        return self._read_many(
            "SELECT * FROM oa_service_creds WHERE principal_id = :principal_id "
            "ORDER BY credential_id",
            {"principal_id": normalized},
            timestamp_columns=("issued_at", "expires_at", "grace_until", "last_used_at"),
        )

    def active_credential_count(self, *, principal_id: str, at_epoch: int) -> int:
        normalized = normalize_service_principal_id(principal_id)
        try:
            with self._session_factory() as session:
                return int(
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM oa_service_creds "
                            "WHERE principal_id = :principal_id "
                            "AND status IN ('ACTIVE', 'ROTATING') "
                            "AND expires_at > :at_time"
                        ),
                        {"principal_id": normalized, "at_time": _timestamp(at_epoch)},
                    ).scalar_one()
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _read_one(
        self,
        sql: str,
        params: Mapping[str, Any],
        *,
        json_columns: tuple[str, ...] = (),
        timestamp_columns: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        rows = self._read_many(
            sql,
            params,
            json_columns=json_columns,
            timestamp_columns=timestamp_columns,
        )
        return rows[0] if rows else None

    def _read_many(
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


def build_service_principal_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaServicePrincipalRepository:
    if runtime.mode == PERSISTENCE_MODE_POSTGRES and runtime.api_session_factory is not None:
        return SqlAlchemyOaServicePrincipalRepository(runtime.api_session_factory)
    return InMemoryOaServicePrincipalRepository()


def _principal_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "principal_id": normalize_service_principal_id(record.get("principal_id")),
        "principal_schema_version": record["principal_schema_version"],
        "service_id": normalize_service_id(record.get("service_id")),
        "display_name": record["display_name"],
        "status": record["status"],
        "allowed_audiences": json.dumps(record["allowed_audiences"]),
        "allowed_scopes": json.dumps(record["allowed_scopes"]),
        "revision": int(record["revision"]),
    }


def _credential_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "credential_id": normalize_credential_id(record.get("credential_id")),
        "credential_schema_version": record["credential_schema_version"],
        "principal_id": normalize_service_principal_id(record.get("principal_id")),
        "secret_hash": record["secret_hash"],
        "secret_hint": record["secret_hint"],
        "status": record["status"],
        "issued_at": _timestamp(record["issued_at"]),
        "expires_at": _timestamp(record["expires_at"]),
        "grace_until": _timestamp(record.get("grace_until")),
        "revision": int(record["revision"]),
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
    return (
        f"CAST(:{parameter} AS JSONB)"
        if session.bind.dialect.name == "postgresql"
        else f":{parameter}"
    )


def _principal_lock_suffix(session: Session) -> str:
    return " FOR UPDATE" if session.bind.dialect.name == "postgresql" else ""


def _timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
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


def _not_found(name: str) -> OaServicePrincipalError:
    return OaServicePrincipalError(404, "oa.service_principal_not_found", f"{name} was not found.")


def _conflict(detail: str) -> OaServicePrincipalError:
    return OaServicePrincipalError(409, "oa.service_principal_conflict", detail)


def _revision_conflict(name: str) -> OaServicePrincipalError:
    return OaServicePrincipalError(
        409,
        "oa.service_principal_revision_conflict",
        f"{name} changed before this write could be applied.",
    )


def _active_limit() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        409,
        "oa.service_credential_active_limit",
        "the service principal already has the maximum active credentials.",
    )


def _unavailable() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        503,
        "oa.service_principal_repository_unavailable",
        "service-principal persistence is temporarily unavailable.",
    )
