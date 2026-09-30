from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.catalog_lifecycle import (
    ALIAS_BINDING_STATES,
    CATALOG_CAPABILITIES,
    CATALOG_STATES,
    AliasBinding,
    ModelCatalogEntry,
)


class CatalogLifecycleRepositoryError(RuntimeError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


class SqlAlchemyCatalogLifecycleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert_catalog_entry(self, entry: ModelCatalogEntry) -> ModelCatalogEntry:
        with self._write_session() as session:
            session.execute(text(_INSERT_CATALOG_SQL), _catalog_params(entry))
        persisted = self.get_catalog_entry(entry.catalog_id)
        if persisted is None:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_write_failed",
                "catalog insert did not return a durable record",
            )
        return persisted

    def get_catalog_entry(self, catalog_id: str) -> ModelCatalogEntry | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_SELECT_CATALOG_SQL + " WHERE catalog_id = :catalog_id"),
                        {"catalog_id": catalog_id},
                    )
                    .mappings()
                    .first()
                )
            return None if row is None else _catalog_from_mapping(row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def list_catalog_entries(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
    ) -> list[ModelCatalogEntry]:
        if capability is not None and capability not in CATALOG_CAPABILITIES:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_filter_invalid",
                "unsupported catalog capability filter",
            )
        if state is not None and state not in CATALOG_STATES:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_filter_invalid",
                "unsupported catalog state filter",
            )
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if capability is not None:
            clauses.append("capability = :capability")
            params["capability"] = capability
        if state is not None:
            clauses.append("catalog_state = :catalog_state")
            params["catalog_state"] = state
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _SELECT_CATALOG_SQL
                            + where
                            + " ORDER BY capability ASC, model_name ASC, revision ASC"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_catalog_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def insert_alias_binding(self, binding: AliasBinding) -> AliasBinding:
        with self._write_session() as session:
            session.execute(text(_INSERT_BINDING_SQL), _binding_params(binding))
        persisted = self.get_alias_binding(binding.binding_id)
        if persisted is None:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_write_failed",
                "alias insert did not return a durable record",
            )
        return persisted

    def update_catalog_state(
        self,
        catalog_id: str,
        *,
        expected_revision: int,
        target_state: str,
        updated_at: str,
    ) -> ModelCatalogEntry:
        if target_state not in CATALOG_STATES:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_state_invalid",
                "unsupported target catalog state",
            )
        with self._write_session() as session:
            result = session.execute(
                text(
                    "UPDATE mo_model_catalog "
                    "SET catalog_state = :target_state, "
                    "revision = revision + 1, updated_at = :updated_at "
                    "WHERE catalog_id = :catalog_id AND revision = :expected_revision"
                ),
                {
                    "catalog_id": catalog_id,
                    "expected_revision": expected_revision,
                    "target_state": target_state,
                    "updated_at": updated_at,
                },
            )
            updated = int(result.rowcount or 0)
        if updated == 0:
            existing = self.get_catalog_entry(catalog_id)
            if existing is None:
                raise CatalogLifecycleRepositoryError(
                    "mo.catalog_not_found",
                    "catalog entry was not found",
                )
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_revision_conflict",
                "catalog revision does not match expected revision",
            )
        persisted = self.get_catalog_entry(catalog_id)
        if persisted is None:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_write_failed",
                "catalog transition did not return a durable record",
            )
        return persisted

    def get_alias_binding(self, binding_id: str) -> AliasBinding | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_SELECT_BINDING_SQL + " WHERE binding_id = :binding_id"),
                        {"binding_id": binding_id},
                    )
                    .mappings()
                    .first()
                )
            return None if row is None else _binding_from_mapping(row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def list_alias_bindings(
        self,
        *,
        alias: str | None = None,
        capability: str | None = None,
        state: str | None = None,
    ) -> list[AliasBinding]:
        if capability is not None and capability not in CATALOG_CAPABILITIES:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_filter_invalid",
                "unsupported alias capability filter",
            )
        if state is not None and state not in ALIAS_BINDING_STATES:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_filter_invalid",
                "unsupported alias binding state filter",
            )
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if alias is not None:
            clauses.append("alias = :alias")
            params["alias"] = alias
        if capability is not None:
            clauses.append("capability = :capability")
            params["capability"] = capability
        if state is not None:
            clauses.append("binding_state = :binding_state")
            params["binding_state"] = state
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _SELECT_BINDING_SQL
                            + where
                            + " ORDER BY alias ASC, capability ASC, "
                            + "binding_revision ASC"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_binding_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def bootstrap_if_empty(
        self,
        entries: Sequence[ModelCatalogEntry],
        bindings: Sequence[AliasBinding],
    ) -> bool:
        session = self._session_factory()
        try:
            try:
                count = session.execute(
                    text("SELECT COUNT(*) FROM mo_model_catalog")
                ).scalar_one()
                if int(count) > 0:
                    session.rollback()
                    return False
                for entry in entries:
                    session.execute(text(_INSERT_CATALOG_SQL), _catalog_params(entry))
                for binding in bindings:
                    session.execute(text(_INSERT_BINDING_SQL), _binding_params(binding))
                session.commit()
                return True
            except Exception:
                session.rollback()
                raise
        except IntegrityError as exc:
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_conflict",
                "catalog bootstrap conflicts with durable state",
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def clear(self) -> tuple[int, int]:
        session = self._session_factory()
        try:
            try:
                bindings = session.execute(text("DELETE FROM mo_alias_bindings"))
                entries = session.execute(text("DELETE FROM mo_model_catalog"))
                deleted = (int(entries.rowcount or 0), int(bindings.rowcount or 0))
                session.commit()
                return deleted
            except Exception:
                session.rollback()
                raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def _write_session(self) -> _RepositoryWriteSession:
        return _RepositoryWriteSession(self._session_factory)


class _RepositoryWriteSession:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session = session_factory()

    def __enter__(self) -> Session:
        return self._session

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        except IntegrityError as error:
            self._session.rollback()
            raise CatalogLifecycleRepositoryError(
                "mo.catalog_conflict",
                "catalog lifecycle write conflicts with durable state",
            ) from error
        except SQLAlchemyError as error:
            self._session.rollback()
            raise _unavailable() from error
        finally:
            self._session.close()
        if exc_type is not None:
            if isinstance(exc, IntegrityError):
                raise CatalogLifecycleRepositoryError(
                    "mo.catalog_conflict",
                    "catalog lifecycle write conflicts with durable state",
                ) from exc
            if isinstance(exc, (SQLAlchemyError, ValueError, TypeError, KeyError)):
                raise _unavailable() from exc
        return False


def _catalog_params(entry: ModelCatalogEntry) -> dict[str, Any]:
    return {
        "catalog_id": entry.catalog_id,
        "capability": entry.provider_capability,
        "model_name": entry.model_name,
        "model_revision": entry.model_revision,
        "deployment_id": entry.deployment_id,
        "runtime_profile": entry.runtime_profile,
        "precision": entry.precision,
        "provider_type": entry.provider_type,
        "response_formats_json": json.dumps(list(entry.supports_response_formats)),
        "max_input_tokens": entry.max_input_tokens,
        "max_output_tokens": entry.max_output_tokens,
        "embedding_dimensions": entry.embedding_dimensions,
        "catalog_state": entry.catalog_state,
        "revision": entry.revision,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _binding_params(binding: AliasBinding) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "alias": binding.alias,
        "capability": binding.provider_capability,
        "catalog_id": binding.catalog_id,
        "binding_revision": binding.binding_revision,
        "binding_state": binding.binding_state,
        "change_reason": binding.change_reason,
        "changed_by": binding.changed_by,
        "previous_binding_id": binding.previous_binding_id,
        "created_at": binding.created_at,
    }


def _catalog_from_mapping(row: Any) -> ModelCatalogEntry:
    formats = json.loads(str(row["response_formats_json"]))
    if not isinstance(formats, list):
        raise ValueError("persisted response formats must be a list")
    return ModelCatalogEntry(
        catalog_id=str(row["catalog_id"]),
        provider_capability=str(row["capability"]),
        model_name=str(row["model_name"]),
        model_revision=str(row["model_revision"]),
        deployment_id=str(row["deployment_id"]),
        runtime_profile=str(row["runtime_profile"]),
        precision=str(row["precision"]),
        provider_type=str(row["provider_type"]),
        supports_response_formats=tuple(str(value) for value in formats),
        max_input_tokens=int(row["max_input_tokens"]),
        max_output_tokens=int(row["max_output_tokens"]),
        embedding_dimensions=(
            None
            if row["embedding_dimensions"] is None
            else int(row["embedding_dimensions"])
        ),
        catalog_state=str(row["catalog_state"]),
        revision=int(row["revision"]),
        created_at=_canonical_timestamp(row["created_at"]),
        updated_at=_canonical_timestamp(row["updated_at"]),
    )


def _binding_from_mapping(row: Any) -> AliasBinding:
    return AliasBinding(
        binding_id=str(row["binding_id"]),
        alias=str(row["alias"]),
        provider_capability=str(row["capability"]),
        catalog_id=str(row["catalog_id"]),
        binding_revision=int(row["binding_revision"]),
        binding_state=str(row["binding_state"]),
        change_reason=str(row["change_reason"]),
        changed_by=str(row["changed_by"]),
        previous_binding_id=(
            None
            if row["previous_binding_id"] is None
            else str(row["previous_binding_id"])
        ),
        created_at=_canonical_timestamp(row["created_at"]),
    )


def _canonical_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unavailable() -> CatalogLifecycleRepositoryError:
    return CatalogLifecycleRepositoryError(
        "mo.catalog_persistence_unavailable",
        "catalog lifecycle persistence is unavailable",
    )


_SELECT_CATALOG_SQL = """
SELECT catalog_id, capability, model_name, model_revision, deployment_id,
       runtime_profile, precision, provider_type, response_formats_json,
       max_input_tokens, max_output_tokens, embedding_dimensions,
       catalog_state, revision, created_at, updated_at
FROM mo_model_catalog
"""

_INSERT_CATALOG_SQL = """
INSERT INTO mo_model_catalog (
    catalog_id, capability, model_name, model_revision, deployment_id,
    runtime_profile, precision, provider_type, response_formats_json,
    max_input_tokens, max_output_tokens, embedding_dimensions,
    catalog_state, revision, created_at, updated_at
) VALUES (
    :catalog_id, :capability, :model_name, :model_revision, :deployment_id,
    :runtime_profile, :precision, :provider_type, :response_formats_json,
    :max_input_tokens, :max_output_tokens, :embedding_dimensions,
    :catalog_state, :revision, :created_at, :updated_at
)
"""

_SELECT_BINDING_SQL = """
SELECT binding_id, alias, capability, catalog_id, binding_revision,
       binding_state, change_reason, changed_by, previous_binding_id, created_at
FROM mo_alias_bindings
"""

_INSERT_BINDING_SQL = """
INSERT INTO mo_alias_bindings (
    binding_id, alias, capability, catalog_id, binding_revision,
    binding_state, change_reason, changed_by, previous_binding_id, created_at
) VALUES (
    :binding_id, :alias, :capability, :catalog_id, :binding_revision,
    :binding_state, :change_reason, :changed_by, :previous_binding_id, :created_at
)
"""
