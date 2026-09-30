from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.catalog_lifecycle import AliasBinding, build_bootstrap_catalog
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    SqlAlchemyCatalogLifecycleRepository,
    _binding_params,
    _catalog_params,
)
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from run_mo_catalog_lifecycle_repository import SQLITE_SCHEMA
import run_mo_alias_lifecycle as runner


NOW = "2026-10-01T02:00:00Z"


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyCatalogLifecycleRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alias.db'}")
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


def lifecycle(
    repository: SqlAlchemyCatalogLifecycleRepository,
    *identifiers: str,
) -> CatalogLifecycleService:
    values = iter(identifiers or ("candidate", "switch", "rollback"))
    return CatalogLifecycleService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(values),
    )


def candidate_command(capability: str = "generation") -> RegisterCatalogEntry:
    is_embedding = capability == "embedding"
    return RegisterCatalogEntry(
        provider_capability=capability,
        model_name="Candidate",
        model_revision=f"candidate-{capability}-v1",
        deployment_id=f"candidate-{capability}",
        runtime_profile=f"{capability}-candidate",
        precision="BF16",
        provider_type="openai-compatible",
        supports_response_formats=("vector",) if is_embedding else ("text",),
        max_input_tokens=8192,
        max_output_tokens=0 if is_embedding else 1024,
        embedding_dimensions=1024 if is_embedding else None,
    )


def activate_candidate(
    service: CatalogLifecycleService,
) -> tuple[object, AliasBinding, AliasBinding]:
    service.ensure_bootstrap()
    original = next(
        binding
        for binding in service.list_alias_bindings(state="ACTIVE")
        if binding.provider_capability == "generation"
    )
    candidate = service.register_catalog_entry(candidate_command())
    candidate = service.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    activated = service.activate_alias(
        alias=original.alias,
        capability="generation",
        catalog_id=candidate.catalog_id,
        expected_binding_revision=1,
        change_reason="Promote candidate",
        changed_by="operator:test",
    )
    return candidate, original, activated


def test_alias_activation_and_rollback_preserve_revisioned_history(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    service = lifecycle(repository)
    candidate, original, activated = activate_candidate(service)

    assert activated.catalog_id == candidate.catalog_id
    assert activated.binding_revision == 2
    assert activated.previous_binding_id == original.binding_id
    history = service.list_alias_bindings(
        alias=original.alias,
        capability="generation",
    )
    assert [item.binding_state for item in history] == ["SUPERSEDED", "ACTIVE"]

    rolled_back = service.rollback_alias(
        alias=original.alias,
        capability="generation",
        expected_binding_revision=2,
        change_reason="Candidate regression",
        changed_by="operator:test",
    )

    assert rolled_back.catalog_id == original.catalog_id
    assert rolled_back.binding_revision == 3
    assert rolled_back.previous_binding_id == activated.binding_id
    history = service.list_alias_bindings(
        alias=original.alias,
        capability="generation",
    )
    assert [item.binding_state for item in history] == [
        "SUPERSEDED",
        "ROLLED_BACK",
        "ACTIVE",
    ]


def test_new_alias_can_be_activated_at_revision_one(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    service = lifecycle(repository, "candidate", "new-alias")
    service.ensure_bootstrap()
    candidate = service.register_catalog_entry(candidate_command())
    candidate = service.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )

    binding = service.activate_alias(
        alias="generation-canary",
        capability="generation",
        catalog_id=candidate.catalog_id,
        expected_binding_revision=0,
        change_reason="Create canary alias",
        changed_by="operator:test",
    )

    assert binding.binding_revision == 1
    assert binding.previous_binding_id is None


def test_alias_activation_rejects_stale_same_inactive_and_mismatched_targets(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    service = lifecycle(repository, "candidate", "switch", "embedding-draft")
    candidate, original, activated = activate_candidate(service)

    with pytest.raises(CatalogLifecycleServiceError) as stale:
        service.activate_alias(
            alias=original.alias,
            capability="generation",
            catalog_id=original.catalog_id,
            expected_binding_revision=1,
            change_reason="stale",
            changed_by="operator:test",
        )
    assert stale.value.error_code == "MO_ALIAS_REVISION_CONFLICT"

    with pytest.raises(CatalogLifecycleServiceError) as same:
        service.activate_alias(
            alias=original.alias,
            capability="generation",
            catalog_id=candidate.catalog_id,
            expected_binding_revision=2,
            change_reason="duplicate",
            changed_by="operator:test",
        )
    assert same.value.error_code == "MO_ALIAS_ALREADY_ACTIVE"

    embedding = next(
        entry
        for entry in service.list_catalog_entries(capability="embedding")
        if entry.catalog_state == "ACTIVE"
    )
    with pytest.raises(CatalogLifecycleServiceError) as mismatch:
        service.activate_alias(
            alias="generation-other",
            capability="generation",
            catalog_id=embedding.catalog_id,
            expected_binding_revision=0,
            change_reason="mismatch",
            changed_by="operator:test",
        )
    assert mismatch.value.error_code == "MO_ALIAS_CAPABILITY_MISMATCH"

    draft = service.register_catalog_entry(candidate_command("embedding"))
    with pytest.raises(CatalogLifecycleServiceError) as inactive:
        service.activate_alias(
            alias="embedding-canary",
            capability="embedding",
            catalog_id=draft.catalog_id,
            expected_binding_revision=0,
            change_reason="inactive",
            changed_by="operator:test",
        )
    assert inactive.value.error_code == "MO_ALIAS_CATALOG_INACTIVE"
    assert activated.binding_state == "ACTIVE"


def test_rollback_rejects_missing_stale_no_history_and_retired_target(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    service = lifecycle(repository, "candidate", "switch", "race")
    service.ensure_bootstrap()
    default = service.list_alias_bindings(state="ACTIVE")[0]
    with pytest.raises(CatalogLifecycleServiceError) as no_history:
        service.rollback_alias(
            alias=default.alias,
            capability=default.provider_capability,
            expected_binding_revision=1,
            change_reason="none",
            changed_by="operator:test",
        )
    assert no_history.value.error_code == "MO_ALIAS_ROLLBACK_UNAVAILABLE"
    with pytest.raises(CatalogLifecycleServiceError) as missing:
        service.rollback_alias(
            alias="missing",
            capability="generation",
            expected_binding_revision=0,
            change_reason="missing",
            changed_by="operator:test",
        )
    assert missing.value.error_code == "MO_ALIAS_NOT_FOUND"

    candidate, original, activated = activate_candidate(service)
    with pytest.raises(CatalogLifecycleServiceError) as stale:
        service.rollback_alias(
            alias=original.alias,
            capability="generation",
            expected_binding_revision=1,
            change_reason="stale",
            changed_by="operator:test",
        )
    assert stale.value.error_code == "MO_ALIAS_REVISION_CONFLICT"

    prior_entry = service.get_catalog_entry(original.catalog_id)
    service.transition_catalog_entry(
        prior_entry.catalog_id,
        expected_revision=prior_entry.revision,
        target_state="RETIRED",
    )
    with pytest.raises(CatalogLifecycleServiceError) as retired:
        service.rollback_alias(
            alias=original.alias,
            capability="generation",
            expected_binding_revision=activated.binding_revision,
            change_reason="retired",
            changed_by="operator:test",
        )
    assert retired.value.error_code == "MO_ALIAS_ROLLBACK_TARGET_INACTIVE"
    assert candidate.catalog_state == "ACTIVE"


def test_repository_replace_validates_target_state_capability_revision_and_lineage(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    entries, bindings = build_bootstrap_catalog()
    repository.bootstrap_if_empty(entries, bindings)
    generation_entry = next(
        entry for entry in entries if entry.provider_capability == "generation"
    )
    generation_binding = next(
        binding
        for binding in bindings
        if binding.provider_capability == "generation"
    )
    base = AliasBinding(
        binding_id="binding:replacement",
        alias=generation_binding.alias,
        provider_capability="generation",
        catalog_id=generation_entry.catalog_id,
        binding_revision=2,
        binding_state="ACTIVE",
        change_reason="replace",
        changed_by="operator:test",
        previous_binding_id=generation_binding.binding_id,
        created_at=NOW,
    )

    with pytest.raises(CatalogLifecycleRepositoryError) as state:
        repository.replace_active_alias(
            replace(base, binding_state="SUPERSEDED"),
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        )
    assert state.value.error_code == "mo.alias_state_invalid"
    with pytest.raises(CatalogLifecycleRepositoryError) as prior_state:
        repository.replace_active_alias(
            base,
            expected_binding_revision=1,
            prior_state="BAD",
        )
    assert prior_state.value.error_code == "mo.alias_state_invalid"
    with pytest.raises(CatalogLifecycleRepositoryError) as revision:
        repository.replace_active_alias(
            base,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        )
    assert revision.value.error_code == "mo.alias_revision_conflict"
    with pytest.raises(CatalogLifecycleRepositoryError) as lineage:
        repository.replace_active_alias(
            replace(base, binding_revision=3),
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        )
    assert lineage.value.error_code == "mo.alias_lineage_invalid"
    with pytest.raises(CatalogLifecycleRepositoryError) as missing:
        repository.replace_active_alias(
            replace(base, catalog_id="catalog:missing"),
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        )
    assert missing.value.error_code == "mo.alias_catalog_not_found"

    retired = repository.update_catalog_state(
        generation_entry.catalog_id,
        expected_revision=1,
        target_state="RETIRED",
        updated_at=NOW,
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as inactive:
        repository.replace_active_alias(
            base,
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        )
    assert retired.catalog_state == "RETIRED"
    assert inactive.value.error_code == "mo.alias_catalog_inactive"


def test_repository_replace_rejects_capability_mismatch(
    repository: SqlAlchemyCatalogLifecycleRepository,
) -> None:
    entries, bindings = build_bootstrap_catalog()
    repository.bootstrap_if_empty(entries, bindings)
    generation = next(
        entry for entry in entries if entry.provider_capability == "generation"
    )
    mismatch = AliasBinding(
        binding_id="binding:mismatch",
        alias="embedding-other",
        provider_capability="embedding",
        catalog_id=generation.catalog_id,
        binding_revision=1,
        binding_state="ACTIVE",
        change_reason="mismatch",
        changed_by="operator:test",
        previous_binding_id=None,
        created_at=NOW,
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        repository.replace_active_alias(
            mismatch,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        )
    assert captured.value.error_code == "mo.alias_capability_mismatch"


def _result(row=None, *, rowcount: int = 0):
    result = Mock()
    result.mappings.return_value.first.return_value = row
    result.rowcount = rowcount
    return result


def test_repository_replace_maps_race_integrity_and_database_failures() -> None:
    entries, bindings = build_bootstrap_catalog()
    target = next(
        entry for entry in entries if entry.provider_capability == "generation"
    )
    current = next(
        binding
        for binding in bindings
        if binding.provider_capability == "generation"
    )
    replacement = AliasBinding(
        binding_id="binding:replacement",
        alias=current.alias,
        provider_capability="generation",
        catalog_id=target.catalog_id,
        binding_revision=2,
        binding_state="ACTIVE",
        change_reason="replace",
        changed_by="operator:test",
        previous_binding_id=current.binding_id,
        created_at=NOW,
    )

    race_session = Mock()
    race_session.execute.side_effect = [
        _result(_catalog_params(target)),
        _result(_binding_params(current)),
        _result(rowcount=0),
    ]
    race_repository = SqlAlchemyCatalogLifecycleRepository(
        lambda: race_session  # type: ignore[arg-type]
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as race:
        race_repository.replace_active_alias(
            replacement,
            expected_binding_revision=1,
            prior_state="SUPERSEDED",
        )
    assert race.value.error_code == "mo.alias_revision_conflict"
    race_session.rollback.assert_called_once()

    initial = replace(
        replacement,
        alias="generation-new",
        binding_revision=1,
        previous_binding_id=None,
    )
    conflict_session = Mock()
    conflict_session.execute.side_effect = [
        _result(_catalog_params(target)),
        _result(None),
        IntegrityError("insert", {}, RuntimeError("conflict")),
    ]
    conflict_repository = SqlAlchemyCatalogLifecycleRepository(
        lambda: conflict_session  # type: ignore[arg-type]
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as conflict:
        conflict_repository.replace_active_alias(
            initial,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        )
    assert conflict.value.error_code == "mo.alias_revision_conflict"

    offline_session = Mock()
    offline_session.execute.side_effect = SQLAlchemyError("offline")
    offline_repository = SqlAlchemyCatalogLifecycleRepository(
        lambda: offline_session  # type: ignore[arg-type]
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as offline:
        offline_repository.replace_active_alias(
            initial,
            expected_binding_revision=0,
            prior_state="SUPERSEDED",
        )
    assert offline.value.error_code == "mo.catalog_persistence_unavailable"


def test_service_rejects_broken_alias_integrity_and_maps_repository_failure(
    repository: SqlAlchemyCatalogLifecycleRepository,
    monkeypatch,
) -> None:
    service = lifecycle(repository, "candidate", "switch", "race")
    candidate, original, current = activate_candidate(service)

    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "list_alias_bindings",
            lambda **kwargs: [current, current],
        )
        with pytest.raises(CatalogLifecycleServiceError) as duplicate:
            service.activate_alias(
                alias=original.alias,
                capability="generation",
                catalog_id=original.catalog_id,
                expected_binding_revision=2,
                change_reason="duplicate",
                changed_by="operator:test",
            )
        assert duplicate.value.error_code == "MO_ALIAS_INTEGRITY_INVALID"

    broken = replace(current, previous_binding_id="binding:missing")
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "list_alias_bindings",
            lambda **kwargs: [broken],
        )
        with pytest.raises(CatalogLifecycleServiceError) as lineage:
            service.rollback_alias(
                alias=original.alias,
                capability="generation",
                expected_binding_revision=2,
                change_reason="broken",
                changed_by="operator:test",
            )
        assert lineage.value.error_code == "MO_ALIAS_LINEAGE_INVALID"

    with monkeypatch.context() as patch:
        patch.setattr(
            repository,
            "replace_active_alias",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                CatalogLifecycleRepositoryError(
                    "mo.alias_revision_conflict",
                    "race",
                )
            ),
        )
        with pytest.raises(CatalogLifecycleServiceError) as mapped:
            service.activate_alias(
                alias=original.alias,
                capability="generation",
                catalog_id=original.catalog_id,
                expected_binding_revision=2,
                change_reason="race",
                changed_by="operator:test",
            )
        assert mapped.value.error_code == "MO_ALIAS_REVISION_CONFLICT"
    assert candidate.catalog_state == "ACTIVE"


def test_alias_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_alias_lifecycle()
    assert "mo_alias_lifecycle=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_alias_lifecycle", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "revision=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_alias_lifecycle",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
