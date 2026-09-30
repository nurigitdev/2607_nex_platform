from __future__ import annotations

from dataclasses import replace
import json

import pytest

from nex_mo.catalog_lifecycle import (
    AliasBinding,
    CatalogLifecycleError,
    ModelCatalogEntry,
    build_bootstrap_catalog,
    validate_active_bindings,
)
import run_mo_catalog_lifecycle_domain as runner


NOW = "2026-10-01T00:00:00Z"


def entry(**overrides: object) -> ModelCatalogEntry:
    values: dict[str, object] = {
        "catalog_id": "catalog:test",
        "provider_capability": "embedding",
        "model_name": "Test Embedding",
        "model_revision": "test-embedding-v1",
        "deployment_id": "test-embedding-deployment",
        "runtime_profile": "embedding-primary",
        "precision": "BF16",
        "provider_type": "openai-compatible",
        "supports_response_formats": ("vector",),
        "max_input_tokens": 4096,
        "max_output_tokens": 0,
        "embedding_dimensions": 1024,
        "catalog_state": "ACTIVE",
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ModelCatalogEntry(**values)  # type: ignore[arg-type]


def binding(**overrides: object) -> AliasBinding:
    values: dict[str, object] = {
        "binding_id": "binding:test:1",
        "alias": "embedding-default",
        "provider_capability": "embedding",
        "catalog_id": "catalog:test",
        "binding_revision": 1,
        "binding_state": "ACTIVE",
        "change_reason": "Initial activation",
        "changed_by": "operator:test",
        "created_at": NOW,
        "previous_binding_id": None,
    }
    values.update(overrides)
    return AliasBinding(**values)  # type: ignore[arg-type]


def test_bootstrap_catalog_is_complete_deterministic_and_privacy_safe() -> None:
    entries, bindings = build_bootstrap_catalog()
    repeated = build_bootstrap_catalog()
    projection = {
        "entries": [item.to_wire() for item in entries],
        "bindings": [item.to_wire() for item in bindings],
    }

    validate_active_bindings(entries, bindings)
    assert (entries, bindings) == repeated
    assert {item.provider_capability for item in entries} == {
        "embedding",
        "reranking",
        "generation",
    }
    assert all(item.catalog_state == "ACTIVE" for item in entries)
    assert all(item.binding_state == "ACTIVE" for item in bindings)
    serialized = json.dumps(projection)
    for private in (
        "provider_endpoint",
        "provider_api_key",
        "model_path",
        "database_url",
        "changed_by",
    ):
        assert private not in serialized


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"catalog_id": "BAD ID"}, "mo.catalog_id_invalid"),
        ({"provider_capability": "other"}, "mo.catalog_capability_invalid"),
        ({"model_name": ""}, "mo.model_name_invalid"),
        ({"catalog_state": "BAD"}, "mo.catalog_state_invalid"),
        ({"revision": 0}, "mo.catalog_revision_invalid"),
        ({"supports_response_formats": ()}, "mo.catalog_response_formats_invalid"),
        (
            {"supports_response_formats": ("vector", "vector")},
            "mo.catalog_response_formats_invalid",
        ),
        ({"max_input_tokens": 0}, "mo.catalog_token_limits_invalid"),
        ({"embedding_dimensions": 0}, "mo.catalog_embedding_dimensions_invalid"),
        ({"updated_at": "2026-09-30T23:59:59Z"}, "mo.catalog_timestamp_invalid"),
        ({"created_at": "bad"}, "mo.created_at_invalid"),
        ({"created_at": "2026-10-01T00:00:00"}, "mo.created_at_invalid"),
    ],
)
def test_catalog_entry_rejects_invalid_values(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(CatalogLifecycleError) as captured:
        entry(**overrides)
    assert captured.value.error_code == code


def test_non_embedding_entry_rejects_embedding_dimensions() -> None:
    with pytest.raises(CatalogLifecycleError) as captured:
        entry(
            provider_capability="generation",
            supports_response_formats=("text",),
            max_output_tokens=1024,
            embedding_dimensions=8,
        )
    assert captured.value.error_code == "mo.catalog_embedding_dimensions_invalid"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"binding_id": "BAD ID"}, "mo.binding_id_invalid"),
        ({"provider_capability": "other"}, "mo.alias_capability_invalid"),
        ({"binding_revision": 0}, "mo.alias_revision_invalid"),
        ({"binding_state": "BAD"}, "mo.alias_state_invalid"),
        ({"change_reason": ""}, "mo.change_reason_invalid"),
        ({"change_reason": "x" * 501}, "mo.alias_change_reason_invalid"),
        ({"created_at": "bad"}, "mo.created_at_invalid"),
        ({"previous_binding_id": "BAD ID"}, "mo.previous_binding_id_invalid"),
        (
            {"previous_binding_id": "binding:test:1"},
            "mo.alias_lineage_invalid",
        ),
    ],
)
def test_alias_binding_rejects_invalid_values(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(CatalogLifecycleError) as captured:
        binding(**overrides)
    assert captured.value.error_code == code


def test_active_binding_validation_rejects_integrity_conflicts() -> None:
    catalog = entry()
    with pytest.raises(CatalogLifecycleError, match="unique"):
        validate_active_bindings((catalog, catalog), ())
    with pytest.raises(CatalogLifecycleError, match="unknown"):
        validate_active_bindings((catalog,), (binding(catalog_id="catalog:missing"),))
    with pytest.raises(CatalogLifecycleError, match="capabilities"):
        validate_active_bindings(
            (catalog,),
            (binding(provider_capability="generation"),),
        )
    with pytest.raises(CatalogLifecycleError, match="active catalog"):
        validate_active_bindings(
            (replace(catalog, catalog_state="DRAFT"),),
            (binding(),),
        )
    with pytest.raises(CatalogLifecycleError, match="only one active"):
        validate_active_bindings(
            (catalog,),
            (
                binding(),
                binding(binding_id="binding:test:2", binding_revision=2),
            ),
        )


def test_non_active_binding_may_reference_non_active_catalog() -> None:
    prior = binding()
    successor = binding(
        binding_id="binding:test:2",
        binding_revision=2,
        previous_binding_id=prior.binding_id,
    )
    assert successor.previous_binding_id == prior.binding_id

    validate_active_bindings(
        (entry(catalog_state="RETIRED"),),
        (binding(binding_state="SUPERSEDED"),),
    )


def test_domain_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_domain()
    assert "mo_catalog_lifecycle_domain=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_lifecycle_domain", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "entries=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_domain",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
