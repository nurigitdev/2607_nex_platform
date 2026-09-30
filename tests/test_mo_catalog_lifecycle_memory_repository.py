from __future__ import annotations

from dataclasses import replace

import pytest

from nex_mo.catalog_lifecycle import (
    AliasBinding,
    ModelCatalogEntry,
    build_bootstrap_catalog,
)
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    InMemoryCatalogLifecycleRepository,
)


NOW = "2026-10-01T04:00:00Z"


def _assert_error(error_code: str, operation) -> None:
    with pytest.raises(CatalogLifecycleRepositoryError) as exc_info:
        operation()
    assert exc_info.value.error_code == error_code


def _candidate(
    catalog_id: str,
    *,
    capability: str = "generation",
    state: str = "ACTIVE",
) -> ModelCatalogEntry:
    dimensions = 256 if capability == "embedding" else None
    return ModelCatalogEntry(
        catalog_id=catalog_id,
        provider_capability=capability,
        model_name=f"{capability}-candidate",
        model_revision=f"{catalog_id}-revision",
        deployment_id=f"{catalog_id}-deployment",
        runtime_profile=f"{capability}-candidate",
        precision="BF16",
        provider_type="openai-compatible",
        supports_response_formats=("float",) if dimensions else ("text",),
        max_input_tokens=8192,
        max_output_tokens=0 if dimensions else 1024,
        embedding_dimensions=dimensions,
        catalog_state=state,
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _binding(
    binding_id: str,
    alias: str,
    target: ModelCatalogEntry,
    *,
    revision: int = 1,
    state: str = "ACTIVE",
    previous_binding_id: str | None = None,
) -> AliasBinding:
    return AliasBinding(
        binding_id=binding_id,
        alias=alias,
        provider_capability=target.provider_capability,
        catalog_id=target.catalog_id,
        binding_revision=revision,
        binding_state=state,
        change_reason="Repository branch verification",
        changed_by="service:nex-ag",
        previous_binding_id=previous_binding_id,
        created_at=NOW,
    )


def test_memory_repository_bootstrap_insert_filter_and_transition_branches() -> None:
    entries, bindings = build_bootstrap_catalog(observed_at=NOW)
    repository = InMemoryCatalogLifecycleRepository()

    assert repository.bootstrap_if_empty(entries, bindings) is True
    assert repository.bootstrap_if_empty(entries, bindings) is False
    assert repository.get_catalog_entry("catalog:missing") is None
    assert repository.get_catalog_entry(entries[0].catalog_id) == entries[0]
    assert len(repository.list_catalog_entries()) == 3
    assert len(
        repository.list_catalog_entries(capability="generation", state="ACTIVE")
    ) == 1
    generation_binding = next(
        binding
        for binding in bindings
        if binding.provider_capability == "generation"
    )
    assert repository.list_alias_bindings(
        alias=generation_binding.alias,
        capability="generation",
        state="ACTIVE",
    ) == [generation_binding]

    _assert_error(
        "mo.catalog_conflict",
        lambda: repository.insert_catalog_entry(entries[0]),
    )
    _assert_error(
        "mo.catalog_conflict",
        lambda: repository.insert_catalog_entry(
            replace(entries[0], catalog_id="catalog:duplicate")
        ),
    )
    candidate = _candidate("catalog:candidate")
    assert repository.insert_catalog_entry(candidate) == candidate
    _assert_error(
        "mo.catalog_state_invalid",
        lambda: repository.update_catalog_state(
            candidate.catalog_id,
            expected_revision=1,
            target_state="OTHER",
            updated_at=NOW,
        ),
    )
    _assert_error(
        "mo.catalog_not_found",
        lambda: repository.update_catalog_state(
            "catalog:missing",
            expected_revision=1,
            target_state="RETIRED",
            updated_at=NOW,
        ),
    )
    _assert_error(
        "mo.catalog_revision_conflict",
        lambda: repository.update_catalog_state(
            candidate.catalog_id,
            expected_revision=2,
            target_state="RETIRED",
            updated_at=NOW,
        ),
    )
    retired = repository.update_catalog_state(
        candidate.catalog_id,
        expected_revision=1,
        target_state="RETIRED",
        updated_at=NOW,
    )
    assert retired.catalog_state == "RETIRED"
    assert retired.revision == 2


def test_memory_repository_rejects_invalid_alias_replacements() -> None:
    repository = InMemoryCatalogLifecycleRepository()
    target = _candidate("catalog:target")
    inactive = _candidate("catalog:inactive", state="RETIRED")
    repository.insert_catalog_entry(target)
    repository.insert_catalog_entry(inactive)

    _assert_error(
        "mo.alias_state_invalid",
        lambda: repository.replace_active_alias(
            _binding("binding:inactive", "candidate", target, state="SUPERSEDED"),
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        ),
    )
    _assert_error(
        "mo.alias_state_invalid",
        lambda: repository.replace_active_alias(
            _binding("binding:prior", "candidate", target),
            expected_binding_revision=0,
            prior_state="ACTIVE",
        ),
    )
    missing = replace(
        _binding("binding:missing", "missing", target),
        catalog_id="catalog:missing",
    )
    _assert_error(
        "mo.alias_catalog_not_found",
        lambda: repository.replace_active_alias(
            missing,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        ),
    )
    _assert_error(
        "mo.alias_catalog_inactive",
        lambda: repository.replace_active_alias(
            _binding("binding:retired", "retired", inactive),
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        ),
    )
    mismatched = replace(
        _binding("binding:mismatch", "mismatch", target),
        provider_capability="embedding",
    )
    _assert_error(
        "mo.alias_capability_mismatch",
        lambda: repository.replace_active_alias(
            mismatched,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        ),
    )

    first = _binding("binding:first", "candidate", target)
    assert repository.replace_active_alias(
        first,
        expected_binding_revision=0,
        prior_state="SUPERSEDED",
    ) == first
    _assert_error(
        "mo.alias_revision_conflict",
        lambda: repository.replace_active_alias(
            _binding(
                "binding:stale",
                "candidate",
                target,
                revision=2,
                previous_binding_id=first.binding_id,
            ),
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        ),
    )
    _assert_error(
        "mo.alias_lineage_invalid",
        lambda: repository.replace_active_alias(
            _binding(
                "binding:lineage",
                "candidate",
                target,
                revision=3,
                previous_binding_id=first.binding_id,
            ),
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        ),
    )


def test_memory_repository_detects_alias_integrity_identity_and_updates_prior() -> None:
    entries, bindings = build_bootstrap_catalog(observed_at=NOW)
    repository = InMemoryCatalogLifecycleRepository()
    repository.bootstrap_if_empty(entries, bindings)
    current = next(
        binding
        for binding in bindings
        if binding.provider_capability == "generation"
    )
    target = _candidate("catalog:next")
    repository.insert_catalog_entry(target)

    duplicate_identity = next(
        binding
        for binding in bindings
        if binding.provider_capability == "embedding"
    ).binding_id
    _assert_error(
        "mo.alias_revision_conflict",
        lambda: repository.replace_active_alias(
            _binding(
                duplicate_identity,
                current.alias,
                target,
                revision=2,
                previous_binding_id=current.binding_id,
            ),
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        ),
    )

    replacement = _binding(
        "binding:replacement",
        current.alias,
        target,
        revision=2,
        previous_binding_id=current.binding_id,
    )
    assert repository.replace_active_alias(
        replacement,
        expected_binding_revision=1,
        prior_state="ROLLED_BACK",
    ) == replacement
    history = repository.list_alias_bindings(alias=current.alias)
    assert [item.binding_state for item in history] == ["ROLLED_BACK", "ACTIVE"]

    repository._bindings["binding:extra-active"] = _binding(
        "binding:extra-active",
        current.alias,
        target,
        revision=3,
        previous_binding_id=replacement.binding_id,
    )
    _assert_error(
        "mo.alias_integrity_invalid",
        lambda: repository.replace_active_alias(
            _binding(
                "binding:blocked",
                current.alias,
                target,
                revision=3,
                previous_binding_id=replacement.binding_id,
            ),
            expected_binding_revision=2,
            prior_state="SUPERSEDED",
        ),
    )
