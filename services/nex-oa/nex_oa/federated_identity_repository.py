from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.federated_identities import OaFederationError
from nex_runtime import PERSISTENCE_MODE_POSTGRES, ServicePersistenceRuntime


class OaFederatedIdentityRepository(Protocol):
    def save_provider(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_provider(self, provider_id: str) -> dict[str, Any] | None: ...
    def list_providers(self) -> list[dict[str, Any]]: ...
    def save_identity(self, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def find_identity(
        self, *, provider_id: str, external_subject_digest: str
    ) -> dict[str, Any] | None: ...
    def list_identities(
        self, *, provider_id: str | None = None, tenant_id: str | None = None
    ) -> list[dict[str, Any]]: ...


class InMemoryOaFederatedIdentityRepository:
    def __init__(self) -> None:
        self.providers: dict[str, dict[str, Any]] = {}
        self.identities: dict[tuple[str, str], dict[str, Any]] = {}

    def save_provider(self, record: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = _required_text(record, "provider_id")
        current = self.providers.get(provider_id)
        _require_revision(current, record, entity="federation provider")
        stored = _stored_record(record)
        if current is not None:
            stored["created_at"] = current["created_at"]
        self.providers[provider_id] = stored
        return deepcopy(stored)

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        record = self.providers.get(_required_value(provider_id, "provider_id"))
        return deepcopy(record) if record is not None else None

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in sorted(
                self.providers.values(), key=lambda item: item["provider_id"]
            )
        ]

    def save_identity(self, record: Mapping[str, Any]) -> dict[str, Any]:
        key = _identity_key(record)
        if key[0] not in self.providers:
            raise _not_found("federation provider")
        current = self.identities.get(key)
        _require_revision(current, record, entity="federated identity")
        _require_same_internal_subject(current, record)
        stored = _stored_record(record)
        if current is not None:
            stored["created_at"] = current["created_at"]
        self.identities[key] = stored
        return deepcopy(stored)

    def find_identity(
        self, *, provider_id: str, external_subject_digest: str
    ) -> dict[str, Any] | None:
        key = (
            _required_value(provider_id, "provider_id"),
            _digest(external_subject_digest),
        )
        record = self.identities.get(key)
        return deepcopy(record) if record is not None else None

    def list_identities(
        self, *, provider_id: str | None = None, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in sorted(
                self.identities.values(),
                key=lambda item: (item["provider_id"], item["external_subject_digest"]),
            )
            if (provider_id is None or record["provider_id"] == provider_id)
            and (tenant_id is None or record["tenant_id"] == tenant_id)
        ]


class SqlAlchemyOaFederatedIdentityRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_provider(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _provider_params(record)
        previous = int(record.get("previous_revision") or 0)
        session = self._session_factory()
        try:
            if previous == 0:
                session.execute(
                    text(
                        "INSERT INTO oa_fed_providers ("
                        "provider_id, provider_schema_version, issuer, client_id, "
                        "discovery_url, display_name, status, revision, created_at, updated_at"
                        ") VALUES ("
                        ":provider_id, :provider_schema_version, :issuer, :client_id, "
                        ":discovery_url, :display_name, :status, :revision, :created_at, :updated_at)"
                    ),
                    params,
                )
            else:
                result = session.execute(
                    text(
                        "UPDATE oa_fed_providers SET issuer = :issuer, client_id = :client_id, "
                        "discovery_url = :discovery_url, display_name = :display_name, "
                        "status = :status, revision = :revision, updated_at = :updated_at "
                        "WHERE provider_id = :provider_id AND revision = :previous_revision"
                    ),
                    {**params, "previous_revision": previous},
                )
                if result.rowcount != 1:
                    raise _revision_conflict("federation provider")
            session.commit()
            return _stored_record(record)
        except OaFederationError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _conflict("federation provider conflicts with persisted state") from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM oa_fed_providers WHERE provider_id = :provider_id",
            {"provider_id": _required_value(provider_id, "provider_id")},
        )

    def list_providers(self) -> list[dict[str, Any]]:
        return self._read_many(
            "SELECT * FROM oa_fed_providers ORDER BY provider_id", {}
        )

    def save_identity(self, record: Mapping[str, Any]) -> dict[str, Any]:
        params = _identity_params(record)
        previous = int(record.get("previous_revision") or 0)
        session = self._session_factory()
        try:
            if previous == 0:
                session.execute(
                    text(
                        "INSERT INTO oa_fed_identities ("
                        "provider_id, external_subject_digest, identity_schema_version, "
                        "tenant_id, subject_ref_type, subject_id, status, revision, "
                        "created_at, updated_at) VALUES ("
                        ":provider_id, :external_subject_digest, :identity_schema_version, "
                        ":tenant_id, 'oa.user', :subject_id, :status, :revision, "
                        ":created_at, :updated_at)"
                    ),
                    params,
                )
            else:
                result = session.execute(
                    text(
                        "UPDATE oa_fed_identities SET status = :status, revision = :revision, "
                        "updated_at = :updated_at WHERE provider_id = :provider_id "
                        "AND external_subject_digest = :external_subject_digest "
                        "AND tenant_id = :tenant_id AND subject_id = :subject_id "
                        "AND revision = :previous_revision"
                    ),
                    {**params, "previous_revision": previous},
                )
                if result.rowcount != 1:
                    raise _revision_conflict("federated identity")
            session.commit()
            return _stored_record(record)
        except OaFederationError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _conflict("federated identity conflicts with persisted state") from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()

    def find_identity(
        self, *, provider_id: str, external_subject_digest: str
    ) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM oa_fed_identities WHERE provider_id = :provider_id "
            "AND external_subject_digest = :external_subject_digest",
            {
                "provider_id": _required_value(provider_id, "provider_id"),
                "external_subject_digest": _digest(external_subject_digest),
            },
        )

    def list_identities(
        self, *, provider_id: str | None = None, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if provider_id is not None:
            clauses.append("provider_id = :provider_id")
            params["provider_id"] = _required_value(provider_id, "provider_id")
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = _required_value(tenant_id, "tenant_id")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._read_many(
            "SELECT * FROM oa_fed_identities"
            f"{where} ORDER BY provider_id, external_subject_digest",
            params,
        )

    def _read_one(self, sql: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
        rows = self._read_many(sql, params)
        return rows[0] if rows else None

    def _read_many(self, sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(text(sql), dict(params)).mappings().all()
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return [_decode_row(row) for row in rows]


def build_federated_identity_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaFederatedIdentityRepository:
    if runtime.mode == PERSISTENCE_MODE_POSTGRES:
        if runtime.api_session_factory is None:
            raise RuntimeError("PostgreSQL federation repository requires a session factory")
        return SqlAlchemyOaFederatedIdentityRepository(runtime.api_session_factory)
    return InMemoryOaFederatedIdentityRepository()


def _provider_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "provider_id",
            "provider_schema_version",
            "issuer",
            "client_id",
            "discovery_url",
            "display_name",
            "status",
            "revision",
            "created_at",
            "updated_at",
        )
    }


def _identity_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "provider_id",
            "external_subject_digest",
            "identity_schema_version",
            "tenant_id",
            "subject_id",
            "status",
            "revision",
            "created_at",
            "updated_at",
        )
    }


def _identity_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _required_text(record, "provider_id"),
        _digest(record.get("external_subject_digest")),
    )


def _stored_record(record: Mapping[str, Any]) -> dict[str, Any]:
    stored = deepcopy(dict(record))
    stored.pop("previous_revision", None)
    return stored


def _require_revision(
    current: Mapping[str, Any] | None,
    record: Mapping[str, Any],
    *,
    entity: str,
) -> None:
    expected = int(record.get("previous_revision") or 0)
    actual = int(current.get("revision") or 0) if current is not None else 0
    if actual != expected:
        raise _revision_conflict(entity)


def _require_same_internal_subject(
    current: Mapping[str, Any] | None, record: Mapping[str, Any]
) -> None:
    if current is None:
        return
    if (
        current.get("tenant_id") != record.get("tenant_id")
        or current.get("subject_id") != record.get("subject_id")
    ):
        raise _conflict("federated identity remapping is forbidden")


def _required_text(record: Mapping[str, Any], field: str) -> str:
    return _required_value(record.get(field), field)


def _required_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OaFederationError(400, f"oa.federation_{field}_invalid", f"{field} is invalid.")
    return value


def _digest(value: object) -> str:
    digest = _required_value(value, "external_subject_digest")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise OaFederationError(
            400,
            "oa.federation_external_subject_digest_invalid",
            "external_subject_digest is invalid.",
        )
    return digest


def _decode_row(row: Mapping[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key in ("created_at", "updated_at"):
        value = decoded.get(key)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            decoded[key] = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return decoded


def _revision_conflict(entity: str) -> OaFederationError:
    return OaFederationError(
        409,
        "oa.federation_revision_conflict",
        f"{entity} changed before this request was applied.",
    )


def _not_found(entity: str) -> OaFederationError:
    return OaFederationError(404, "oa.federation_not_found", f"{entity} was not found.")


def _conflict(detail: str) -> OaFederationError:
    return OaFederationError(409, "oa.federation_conflict", detail)


def _unavailable() -> OaFederationError:
    return OaFederationError(
        503,
        "oa.federation_repository_unavailable",
        "Federation repository is unavailable.",
    )
