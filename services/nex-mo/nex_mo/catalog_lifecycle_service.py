from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Sequence
from uuid import uuid4

from nex_mo.catalog_lifecycle import (
    AliasBinding,
    ModelCatalogEntry,
    build_bootstrap_catalog,
)
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    SqlAlchemyCatalogLifecycleRepository,
)


CATALOG_TRANSITIONS = {
    "DRAFT": frozenset({"ACTIVE", "RETIRED"}),
    "ACTIVE": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}


class CatalogLifecycleServiceError(RuntimeError):
    def __init__(self, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class RegisterCatalogEntry:
    provider_capability: str
    model_name: str
    model_revision: str
    deployment_id: str
    runtime_profile: str
    precision: str
    provider_type: str
    supports_response_formats: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    embedding_dimensions: int | None = None


class CatalogLifecycleService:
    def __init__(
        self,
        repository: SqlAlchemyCatalogLifecycleRepository,
        *,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or _utc_now
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def ensure_bootstrap(self) -> bool:
        entries, bindings = build_bootstrap_catalog(observed_at=self._clock())
        try:
            return self._repository.bootstrap_if_empty(entries, bindings)
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def register_catalog_entry(
        self,
        command: RegisterCatalogEntry,
    ) -> ModelCatalogEntry:
        now = self._clock()
        entry = ModelCatalogEntry(
            catalog_id=f"catalog:{self._id_factory()}",
            provider_capability=command.provider_capability,
            model_name=command.model_name,
            model_revision=command.model_revision,
            deployment_id=command.deployment_id,
            runtime_profile=command.runtime_profile,
            precision=command.precision,
            provider_type=command.provider_type,
            supports_response_formats=command.supports_response_formats,
            max_input_tokens=command.max_input_tokens,
            max_output_tokens=command.max_output_tokens,
            embedding_dimensions=command.embedding_dimensions,
            catalog_state="DRAFT",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._repository.insert_catalog_entry(entry)
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def transition_catalog_entry(
        self,
        catalog_id: str,
        *,
        expected_revision: int,
        target_state: str,
    ) -> ModelCatalogEntry:
        current = self.get_catalog_entry(catalog_id)
        if current.revision != expected_revision:
            raise CatalogLifecycleServiceError(
                409,
                "MO_CATALOG_REVISION_CONFLICT",
                "Catalog revision does not match expected revision.",
            )
        allowed = CATALOG_TRANSITIONS.get(current.catalog_state, frozenset())
        if target_state not in allowed:
            raise CatalogLifecycleServiceError(
                409,
                "MO_CATALOG_TRANSITION_INVALID",
                f"Cannot transition catalog from {current.catalog_state} to {target_state}.",
            )
        if target_state == "RETIRED" and self._has_active_binding(catalog_id):
            raise CatalogLifecycleServiceError(
                409,
                "MO_CATALOG_ACTIVE_ALIAS_CONFLICT",
                "Catalog entry is still referenced by an active alias.",
            )
        try:
            return self._repository.update_catalog_state(
                catalog_id,
                expected_revision=expected_revision,
                target_state=target_state,
                updated_at=self._clock(),
            )
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def get_catalog_entry(self, catalog_id: str) -> ModelCatalogEntry:
        try:
            entry = self._repository.get_catalog_entry(catalog_id)
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        if entry is None:
            raise CatalogLifecycleServiceError(
                404,
                "MO_CATALOG_NOT_FOUND",
                "Catalog entry was not found.",
            )
        return entry

    def list_catalog_entries(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
    ) -> Sequence[ModelCatalogEntry]:
        try:
            return self._repository.list_catalog_entries(
                capability=capability,
                state=state,
            )
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def list_alias_bindings(
        self,
        *,
        alias: str | None = None,
        capability: str | None = None,
        state: str | None = None,
    ) -> Sequence[AliasBinding]:
        try:
            return self._repository.list_alias_bindings(
                alias=alias,
                capability=capability,
                state=state,
            )
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def activate_alias(
        self,
        *,
        alias: str,
        capability: str,
        catalog_id: str,
        expected_binding_revision: int,
        change_reason: str,
        changed_by: str,
    ) -> AliasBinding:
        target = self.get_catalog_entry(catalog_id)
        if target.catalog_state != "ACTIVE":
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_CATALOG_INACTIVE",
                "Alias target catalog entry is not active.",
            )
        if target.provider_capability != capability:
            raise CatalogLifecycleServiceError(
                422,
                "MO_ALIAS_CAPABILITY_MISMATCH",
                "Alias and target catalog capabilities do not match.",
            )
        current = self._active_binding(alias, capability)
        current_revision = 0 if current is None else current.binding_revision
        if current_revision != expected_binding_revision:
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_REVISION_CONFLICT",
                "Alias revision does not match expected revision.",
            )
        if current is not None and current.catalog_id == catalog_id:
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_ALREADY_ACTIVE",
                "Alias already targets this catalog entry.",
            )
        binding = self._new_binding(
            alias=alias,
            capability=capability,
            catalog_id=catalog_id,
            expected_binding_revision=expected_binding_revision,
            change_reason=change_reason,
            changed_by=changed_by,
            current=current,
        )
        return self._replace_alias(
            binding,
            expected_binding_revision=expected_binding_revision,
            prior_state="SUPERSEDED",
        )

    def rollback_alias(
        self,
        *,
        alias: str,
        capability: str,
        expected_binding_revision: int,
        change_reason: str,
        changed_by: str,
    ) -> AliasBinding:
        current = self._active_binding(alias, capability)
        if current is None:
            raise CatalogLifecycleServiceError(
                404,
                "MO_ALIAS_NOT_FOUND",
                "Active alias binding was not found.",
            )
        if current.binding_revision != expected_binding_revision:
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_REVISION_CONFLICT",
                "Alias revision does not match expected revision.",
            )
        if current.previous_binding_id is None:
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_ROLLBACK_UNAVAILABLE",
                "Alias has no previous binding to restore.",
            )
        history = self.list_alias_bindings(alias=alias, capability=capability)
        prior = next(
            (
                binding
                for binding in history
                if binding.binding_id == current.previous_binding_id
            ),
            None,
        )
        if prior is None:
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_LINEAGE_INVALID",
                "Previous alias binding was not found.",
            )
        target = self.get_catalog_entry(prior.catalog_id)
        if target.catalog_state != "ACTIVE":
            raise CatalogLifecycleServiceError(
                409,
                "MO_ALIAS_ROLLBACK_TARGET_INACTIVE",
                "Previous alias target is not active.",
            )
        binding = self._new_binding(
            alias=alias,
            capability=capability,
            catalog_id=prior.catalog_id,
            expected_binding_revision=expected_binding_revision,
            change_reason=change_reason,
            changed_by=changed_by,
            current=current,
        )
        return self._replace_alias(
            binding,
            expected_binding_revision=expected_binding_revision,
            prior_state="ROLLED_BACK",
        )

    def _has_active_binding(self, catalog_id: str) -> bool:
        return any(
            binding.catalog_id == catalog_id
            for binding in self.list_alias_bindings(state="ACTIVE")
        )

    def _active_binding(
        self,
        alias: str,
        capability: str,
    ) -> AliasBinding | None:
        bindings = self.list_alias_bindings(
            alias=alias,
            capability=capability,
            state="ACTIVE",
        )
        if len(bindings) > 1:
            raise CatalogLifecycleServiceError(
                503,
                "MO_ALIAS_INTEGRITY_INVALID",
                "Multiple active alias bindings were found.",
            )
        return bindings[0] if bindings else None

    def _new_binding(
        self,
        *,
        alias: str,
        capability: str,
        catalog_id: str,
        expected_binding_revision: int,
        change_reason: str,
        changed_by: str,
        current: AliasBinding | None,
    ) -> AliasBinding:
        return AliasBinding(
            binding_id=f"binding:{self._id_factory()}",
            alias=alias,
            provider_capability=capability,
            catalog_id=catalog_id,
            binding_revision=expected_binding_revision + 1,
            binding_state="ACTIVE",
            change_reason=change_reason,
            changed_by=changed_by,
            previous_binding_id=None if current is None else current.binding_id,
            created_at=self._clock(),
        )

    def _replace_alias(
        self,
        binding: AliasBinding,
        *,
        expected_binding_revision: int,
        prior_state: str,
    ) -> AliasBinding:
        try:
            return self._repository.replace_active_alias(
                binding,
                expected_binding_revision=expected_binding_revision,
                prior_state=prior_state,
            )
        except CatalogLifecycleRepositoryError as exc:
            raise _map_repository_error(exc) from exc


def _map_repository_error(
    error: CatalogLifecycleRepositoryError,
) -> CatalogLifecycleServiceError:
    mappings = {
        "mo.catalog_not_found": (404, "MO_CATALOG_NOT_FOUND"),
        "mo.catalog_revision_conflict": (409, "MO_CATALOG_REVISION_CONFLICT"),
        "mo.catalog_conflict": (409, "MO_CATALOG_CONFLICT"),
        "mo.catalog_filter_invalid": (422, "MO_CATALOG_FILTER_INVALID"),
        "mo.alias_filter_invalid": (422, "MO_ALIAS_FILTER_INVALID"),
        "mo.alias_catalog_not_found": (404, "MO_ALIAS_CATALOG_NOT_FOUND"),
        "mo.alias_catalog_inactive": (409, "MO_ALIAS_CATALOG_INACTIVE"),
        "mo.alias_capability_mismatch": (422, "MO_ALIAS_CAPABILITY_MISMATCH"),
        "mo.alias_revision_conflict": (409, "MO_ALIAS_REVISION_CONFLICT"),
        "mo.alias_lineage_invalid": (409, "MO_ALIAS_LINEAGE_INVALID"),
    }
    status_code, error_code = mappings.get(
        error.error_code,
        (503, "MO_CATALOG_PERSISTENCE_UNAVAILABLE"),
    )
    return CatalogLifecycleServiceError(status_code, error_code, error.detail)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
