from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
import json
from threading import RLock
from typing import Any, Protocol, Sequence

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


class CatalogLifecycleRepository(Protocol):
    def insert_catalog_entry(self, entry: ModelCatalogEntry) -> ModelCatalogEntry: ...
    def get_catalog_entry(self, catalog_id: str) -> ModelCatalogEntry | None: ...
    def list_catalog_entries(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
    ) -> Sequence[ModelCatalogEntry]: ...
    def update_catalog_state(
        self,
        catalog_id: str,
        *,
        expected_revision: int,
        target_state: str,
        updated_at: str,
    ) -> ModelCatalogEntry: ...
    def list_alias_bindings(
        self,
        *,
        alias: str | None = None,
        capability: str | None = None,
        state: str | None = None,
    ) -> Sequence[AliasBinding]: ...
    def replace_active_alias(
        self,
        binding: AliasBinding,
        *,
        expected_binding_revision: int,
        prior_state: str,
    ) -> AliasBinding: ...
    def bootstrap_if_empty(
        self,
        entries: Sequence[ModelCatalogEntry],
        bindings: Sequence[AliasBinding],
    ) -> bool: ...


class InMemoryCatalogLifecycleRepository:
    def __init__(self) -> None:
        self._entries: dict[str, ModelCatalogEntry] = {}
        self._bindings: dict[str, AliasBinding] = {}
        self._lock = RLock()

    def insert_catalog_entry(self, entry: ModelCatalogEntry) -> ModelCatalogEntry:
        with self._lock:
            if entry.catalog_id in self._entries or any(
                (
                    current.provider_capability,
                    current.deployment_id,
                    current.model_revision,
                )
                == (
                    entry.provider_capability,
                    entry.deployment_id,
                    entry.model_revision,
                )
                for current in self._entries.values()
            ):
                raise CatalogLifecycleRepositoryError(
                    "mo.catalog_conflict",
                    "catalog entry conflicts with durable state",
                )
            self._entries[entry.catalog_id] = entry
            return entry

    def get_catalog_entry(self, catalog_id: str) -> ModelCatalogEntry | None:
        with self._lock:
            return self._entries.get(catalog_id)

    def list_catalog_entries(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
    ) -> list[ModelCatalogEntry]:
        _validate_catalog_filters(capability, state)
        with self._lock:
            values = [
                entry
                for entry in self._entries.values()
                if (capability is None or entry.provider_capability == capability)
                and (state is None or entry.catalog_state == state)
            ]
        return sorted(
            values,
            key=lambda entry: (
                entry.provider_capability,
                entry.model_name,
                entry.revision,
            ),
        )

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
        with self._lock:
            current = self._entries.get(catalog_id)
            if current is None:
                raise CatalogLifecycleRepositoryError(
                    "mo.catalog_not_found",
                    "catalog entry was not found",
                )
            if current.revision != expected_revision:
                raise CatalogLifecycleRepositoryError(
                    "mo.catalog_revision_conflict",
                    "catalog revision does not match expected revision",
                )
            updated = replace(
                current,
                catalog_state=target_state,
                revision=current.revision + 1,
                updated_at=updated_at,
            )
            self._entries[catalog_id] = updated
            return updated

    def list_alias_bindings(
        self,
        *,
        alias: str | None = None,
        capability: str | None = None,
        state: str | None = None,
    ) -> list[AliasBinding]:
        _validate_alias_filters(capability, state)
        with self._lock:
            values = [
                binding
                for binding in self._bindings.values()
                if (alias is None or binding.alias == alias)
                and (
                    capability is None
                    or binding.provider_capability == capability
                )
                and (state is None or binding.binding_state == state)
            ]
        return sorted(
            values,
            key=lambda binding: (
                binding.alias,
                binding.provider_capability,
                binding.binding_revision,
            ),
        )

    def replace_active_alias(
        self,
        binding: AliasBinding,
        *,
        expected_binding_revision: int,
        prior_state: str,
    ) -> AliasBinding:
        if binding.binding_state != "ACTIVE" or prior_state not in {
            "SUPERSEDED",
            "ROLLED_BACK",
        }:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_state_invalid",
                "alias replacement states are invalid",
            )
        with self._lock:
            target = self._entries.get(binding.catalog_id)
            if target is None:
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_catalog_not_found",
                    "alias target catalog entry was not found",
                )
            if target.catalog_state != "ACTIVE":
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_catalog_inactive",
                    "alias target catalog entry is not active",
                )
            if target.provider_capability != binding.provider_capability:
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_capability_mismatch",
                    "alias and target catalog capabilities do not match",
                )
            active = [
                current
                for current in self._bindings.values()
                if current.alias == binding.alias
                and current.provider_capability == binding.provider_capability
                and current.binding_state == "ACTIVE"
            ]
            if len(active) > 1:
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_integrity_invalid",
                    "multiple active alias bindings were found",
                )
            current = active[0] if active else None
            revision = 0 if current is None else current.binding_revision
            previous_id = None if current is None else current.binding_id
            if revision != expected_binding_revision:
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_revision_conflict",
                    "alias revision does not match expected revision",
                )
            if (
                binding.binding_revision != expected_binding_revision + 1
                or binding.previous_binding_id != previous_id
            ):
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_lineage_invalid",
                    "alias replacement revision or lineage is invalid",
                )
            if binding.binding_id in self._bindings:
                raise CatalogLifecycleRepositoryError(
                    "mo.alias_revision_conflict",
                    "alias binding identity already exists",
                )
            if current is not None:
                self._bindings[current.binding_id] = replace(
                    current,
                    binding_state=prior_state,
                )
            self._bindings[binding.binding_id] = binding
            return binding

    def bootstrap_if_empty(
        self,
        entries: Sequence[ModelCatalogEntry],
        bindings: Sequence[AliasBinding],
    ) -> bool:
        with self._lock:
            if self._entries:
                return False
            self._entries = {entry.catalog_id: entry for entry in entries}
            self._bindings = {binding.binding_id: binding for binding in bindings}
            return True


def _validate_catalog_filters(
    capability: str | None,
    state: str | None,
) -> None:
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


def _validate_alias_filters(
    capability: str | None,
    state: str | None,
) -> None:
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

    def replace_active_alias(
        self,
        binding: AliasBinding,
        *,
        expected_binding_revision: int,
        prior_state: str,
    ) -> AliasBinding:
        if binding.binding_state != "ACTIVE":
            raise CatalogLifecycleRepositoryError(
                "mo.alias_state_invalid",
                "replacement alias binding must be active",
            )
        if prior_state not in {"SUPERSEDED", "ROLLED_BACK"}:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_state_invalid",
                "prior alias state is invalid",
            )
        session = self._session_factory()
        try:
            try:
                catalog_row = (
                    session.execute(
                        text(
                            _SELECT_CATALOG_SQL
                            + " WHERE catalog_id = :catalog_id"
                        ),
                        {"catalog_id": binding.catalog_id},
                    )
                    .mappings()
                    .first()
                )
                if catalog_row is None:
                    raise CatalogLifecycleRepositoryError(
                        "mo.alias_catalog_not_found",
                        "alias target catalog entry was not found",
                    )
                target = _catalog_from_mapping(catalog_row)
                if target.catalog_state != "ACTIVE":
                    raise CatalogLifecycleRepositoryError(
                        "mo.alias_catalog_inactive",
                        "alias target catalog entry is not active",
                    )
                if target.provider_capability != binding.provider_capability:
                    raise CatalogLifecycleRepositoryError(
                        "mo.alias_capability_mismatch",
                        "alias and target catalog capabilities do not match",
                    )

                current_row = (
                    session.execute(
                        text(
                            _SELECT_BINDING_SQL
                            + " WHERE alias = :alias AND capability = :capability"
                            + " AND binding_state = 'ACTIVE'"
                        ),
                        {
                            "alias": binding.alias,
                            "capability": binding.provider_capability,
                        },
                    )
                    .mappings()
                    .first()
                )
                current = (
                    None
                    if current_row is None
                    else _binding_from_mapping(current_row)
                )
                current_revision = 0 if current is None else current.binding_revision
                if current_revision != expected_binding_revision:
                    raise CatalogLifecycleRepositoryError(
                        "mo.alias_revision_conflict",
                        "alias revision does not match expected revision",
                    )
                expected_previous = None if current is None else current.binding_id
                if (
                    binding.binding_revision != expected_binding_revision + 1
                    or binding.previous_binding_id != expected_previous
                ):
                    raise CatalogLifecycleRepositoryError(
                        "mo.alias_lineage_invalid",
                        "alias replacement revision or lineage is invalid",
                    )
                if current is not None:
                    result = session.execute(
                        text(
                            "UPDATE mo_alias_bindings "
                            "SET binding_state = :prior_state "
                            "WHERE binding_id = :binding_id "
                            "AND binding_revision = :expected_revision "
                            "AND binding_state = 'ACTIVE'"
                        ),
                        {
                            "prior_state": prior_state,
                            "binding_id": current.binding_id,
                            "expected_revision": expected_binding_revision,
                        },
                    )
                    if int(result.rowcount or 0) != 1:
                        raise CatalogLifecycleRepositoryError(
                            "mo.alias_revision_conflict",
                            "active alias changed during replacement",
                        )
                session.execute(text(_INSERT_BINDING_SQL), _binding_params(binding))
                session.commit()
                return binding
            except Exception:
                session.rollback()
                raise
        except CatalogLifecycleRepositoryError:
            raise
        except IntegrityError as exc:
            raise CatalogLifecycleRepositoryError(
                "mo.alias_revision_conflict",
                "alias replacement conflicts with durable state",
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

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
