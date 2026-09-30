from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.catalog_lifecycle import build_bootstrap_catalog
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from run_mo_catalog_lifecycle_repository import SQLITE_SCHEMA
import run_mo_catalog_lifecycle_service as runner


NOW = "2026-10-01T01:00:00Z"


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyCatalogLifecycleRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'service.db'}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return SqlAlchemyCatalogLifecycleRepository(factory)


def service(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> CatalogLifecycleService:
    return CatalogLifecycleService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: "candidate-1",
    )


def command(**overrides: object) -> RegisterCatalogEntry:
    values: dict[str, object] = {
        "provider_capability": "generation",
        "model_name": "Candidate",
        "model_revision": "candidate-v1",
        "deployment_id": "candidate-deployment",
        "runtime_profile": "generation-candidate",
        "precision": "BF16",
        "provider_type": "openai-compatible",
        "supports_response_formats": ("text",),
        "max_input_tokens": 8192,
        "max_output_tokens": 1024,
        "embedding_dimensions": None,
    }
    values.update(overrides)
    return RegisterCatalogEntry(**values)  # type: ignore[arg-type]


def test_service_bootstrap_registers_lists_and_gets(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    lifecycle = service(repository)
    assert lifecycle.ensure_bootstrap() is True
    assert lifecycle.ensure_bootstrap() is False

    candidate = lifecycle.register_catalog_entry(command())

    assert candidate.catalog_id == "catalog:candidate-1"
    assert candidate.catalog_state == "DRAFT"
    assert lifecycle.get_catalog_entry(candidate.catalog_id) == candidate
    assert lifecycle.list_catalog_entries(
        capability="generation", state="DRAFT"
    ) == [candidate]
    assert len(lifecycle.list_alias_bindings(state="ACTIVE")) == 3


def test_service_transitions_with_revision_and_active_alias_guards(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    lifecycle = service(repository)
    lifecycle.ensure_bootstrap()
    candidate = lifecycle.register_catalog_entry(command())

    activated = lifecycle.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    assert activated.revision == 2

    with pytest.raises(CatalogLifecycleServiceError) as stale:
        lifecycle.transition_catalog_entry(
            candidate.catalog_id,
            expected_revision=1,
            target_state="RETIRED",
        )
    assert stale.value.status_code == 409
    assert stale.value.error_code == "MO_CATALOG_REVISION_CONFLICT"

    retired = lifecycle.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=2,
        target_state="RETIRED",
    )
    assert retired.catalog_state == "RETIRED"
    assert retired.revision == 3

    with pytest.raises(CatalogLifecycleServiceError) as terminal:
        lifecycle.transition_catalog_entry(
            candidate.catalog_id,
            expected_revision=3,
            target_state="ACTIVE",
        )
    assert terminal.value.error_code == "MO_CATALOG_TRANSITION_INVALID"

    active_default = lifecycle.list_alias_bindings(state="ACTIVE")[0]
    default_entry = lifecycle.get_catalog_entry(active_default.catalog_id)
    with pytest.raises(CatalogLifecycleServiceError) as referenced:
        lifecycle.transition_catalog_entry(
            default_entry.catalog_id,
            expected_revision=default_entry.revision,
            target_state="RETIRED",
        )
    assert referenced.value.error_code == "MO_CATALOG_ACTIVE_ALIAS_CONFLICT"


def test_service_maps_not_found_filter_conflict_and_unavailable_errors(
    repository: SqlAlchemyCatalogLifecycleRepository,
    monkeypatch,
) -> None:
    lifecycle = service(repository)
    with pytest.raises(CatalogLifecycleServiceError) as missing:
        lifecycle.get_catalog_entry("catalog:missing")
    assert missing.value.status_code == 404

    with pytest.raises(CatalogLifecycleServiceError) as invalid_filter:
        lifecycle.list_catalog_entries(capability="other")
    assert invalid_filter.value.status_code == 422
    with pytest.raises(CatalogLifecycleServiceError) as invalid_alias_filter:
        lifecycle.list_alias_bindings(state="OTHER")
    assert invalid_alias_filter.value.error_code == "MO_ALIAS_FILTER_INVALID"

    def unavailable(*args, **kwargs):
        raise CatalogLifecycleRepositoryError(
            "mo.catalog_persistence_unavailable",
            "offline",
        )

    monkeypatch.setattr(repository, "list_catalog_entries", unavailable)
    with pytest.raises(CatalogLifecycleServiceError) as unavailable_error:
        lifecycle.list_catalog_entries()
    assert unavailable_error.value.status_code == 503


def test_service_maps_repository_failures_on_each_mutation_path(
    repository: SqlAlchemyCatalogLifecycleRepository,
    monkeypatch,
) -> None:
    lifecycle = service(repository)

    def fail(code: str):
        def operation(*args, **kwargs):
            raise CatalogLifecycleRepositoryError(code, "repository failure")

        return operation

    with monkeypatch.context() as patch:
        patch.setattr(repository, "bootstrap_if_empty", fail("mo.catalog_conflict"))
        with pytest.raises(CatalogLifecycleServiceError) as bootstrap:
            lifecycle.ensure_bootstrap()
        assert bootstrap.value.error_code == "MO_CATALOG_CONFLICT"

    with monkeypatch.context() as patch:
        patch.setattr(repository, "insert_catalog_entry", fail("mo.catalog_conflict"))
        with pytest.raises(CatalogLifecycleServiceError) as register:
            lifecycle.register_catalog_entry(command())
        assert register.value.error_code == "MO_CATALOG_CONFLICT"

    lifecycle.ensure_bootstrap()
    candidate = lifecycle.register_catalog_entry(command())
    with monkeypatch.context() as patch:
        patch.setattr(
            repository,
            "update_catalog_state",
            fail("mo.catalog_revision_conflict"),
        )
        with pytest.raises(CatalogLifecycleServiceError) as transition:
            lifecycle.transition_catalog_entry(
                candidate.catalog_id,
                expected_revision=1,
                target_state="ACTIVE",
            )
        assert transition.value.error_code == "MO_CATALOG_REVISION_CONFLICT"

    with monkeypatch.context() as patch:
        patch.setattr(repository, "get_catalog_entry", fail("mo.catalog_not_found"))
        with pytest.raises(CatalogLifecycleServiceError) as read:
            lifecycle.get_catalog_entry(candidate.catalog_id)
        assert read.value.error_code == "MO_CATALOG_NOT_FOUND"


def test_service_default_clock_and_identifier_are_valid(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    candidate = CatalogLifecycleService(repository).register_catalog_entry(command())

    assert candidate.catalog_id.startswith("catalog:")
    assert candidate.created_at.endswith("Z")


def test_repository_atomic_catalog_state_update_contract(
    repository: SqlAlchemyCatalogLifecycleRepository,
    monkeypatch,
) -> None:
    entry = build_bootstrap_catalog()[0][0]
    repository.insert_catalog_entry(entry)
    updated = repository.update_catalog_state(
        entry.catalog_id,
        expected_revision=1,
        target_state="RETIRED",
        updated_at="2026-10-01T02:00:00Z",
    )
    assert updated.catalog_state == "RETIRED"
    assert updated.revision == 2

    with pytest.raises(CatalogLifecycleRepositoryError) as stale:
        repository.update_catalog_state(
            entry.catalog_id,
            expected_revision=1,
            target_state="ACTIVE",
            updated_at=NOW,
        )
    assert stale.value.error_code == "mo.catalog_revision_conflict"
    with pytest.raises(CatalogLifecycleRepositoryError) as missing:
        repository.update_catalog_state(
            "catalog:missing",
            expected_revision=1,
            target_state="ACTIVE",
            updated_at=NOW,
        )
    assert missing.value.error_code == "mo.catalog_not_found"
    with pytest.raises(CatalogLifecycleRepositoryError) as invalid:
        repository.update_catalog_state(
            entry.catalog_id,
            expected_revision=2,
            target_state="OTHER",
            updated_at=NOW,
        )
    assert invalid.value.error_code == "mo.catalog_state_invalid"

    monkeypatch.setattr(repository, "get_catalog_entry", lambda catalog_id: None)
    with pytest.raises(CatalogLifecycleRepositoryError) as readback:
        repository.update_catalog_state(
            entry.catalog_id,
            expected_revision=2,
            target_state="ACTIVE",
            updated_at=NOW,
        )
    assert readback.value.error_code == "mo.catalog_write_failed"


def test_service_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_service()
    assert "lifecycle_service=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_lifecycle_service", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "revision=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_service",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
