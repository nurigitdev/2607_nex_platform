from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.catalog_lifecycle import build_bootstrap_catalog
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    SqlAlchemyCatalogLifecycleRepository,
    _RepositoryWriteSession,
    _canonical_timestamp,
)
from run_mo_catalog_lifecycle_repository import SQLITE_SCHEMA


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_repository_bootstraps_once_and_survives_restart(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entries, bindings = build_bootstrap_catalog()

    assert repository.bootstrap_if_empty(entries, bindings) is True
    assert repository.bootstrap_if_empty(entries, bindings) is False

    restarted = SqlAlchemyCatalogLifecycleRepository(session_factory)
    assert {item.catalog_id for item in restarted.list_catalog_entries()} == {
        item.catalog_id for item in entries
    }
    assert {item.binding_id for item in restarted.list_alias_bindings()} == {
        item.binding_id for item in bindings
    }
    assert restarted.get_catalog_entry(entries[0].catalog_id) == entries[0]
    assert restarted.get_alias_binding(bindings[0].binding_id) == bindings[0]
    assert restarted.get_catalog_entry("catalog:missing") is None
    assert restarted.get_alias_binding("binding:missing") is None


def test_repository_inserts_filters_orders_and_clears(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entries, bindings = build_bootstrap_catalog()
    for item in reversed(entries):
        assert repository.insert_catalog_entry(item) == item
    for item in reversed(bindings):
        assert repository.insert_alias_binding(item) == item

    assert len(repository.list_catalog_entries(capability="embedding")) == 1
    assert len(repository.list_catalog_entries(state="ACTIVE")) == 3
    assert len(repository.list_alias_bindings(alias=bindings[0].alias)) == 1
    assert len(repository.list_alias_bindings(capability="generation")) == 1
    assert len(repository.list_alias_bindings(state="ACTIVE")) == 3
    assert repository.clear() == (3, 3)
    assert repository.list_catalog_entries() == []
    assert repository.list_alias_bindings() == []


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("list_catalog_entries", {"capability": "other"}),
        ("list_catalog_entries", {"state": "OTHER"}),
        ("list_alias_bindings", {"capability": "other"}),
        ("list_alias_bindings", {"state": "OTHER"}),
    ],
)
def test_repository_rejects_invalid_filters(
    session_factory: sessionmaker[Session],
    method: str,
    kwargs: dict[str, str],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        getattr(repository, method)(**kwargs)
    assert captured.value.error_code.endswith("filter_invalid")


def test_repository_maps_integrity_conflicts(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entries, bindings = build_bootstrap_catalog()
    repository.insert_catalog_entry(entries[0])
    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        repository.insert_catalog_entry(entries[0])
    assert captured.value.error_code == "mo.catalog_conflict"

    repository.insert_alias_binding(bindings[0])
    conflict = replace(
        bindings[0],
        binding_id="binding:conflict",
    )
    with pytest.raises(CatalogLifecycleRepositoryError) as alias_conflict:
        repository.insert_alias_binding(conflict)
    assert alias_conflict.value.error_code == "mo.catalog_conflict"


def test_repository_fails_closed_for_broken_schema(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    with session_factory() as session:
        with session.begin():
            session.execute(text("DROP TABLE mo_alias_bindings"))
            session.execute(text("DROP TABLE mo_model_catalog"))

    operations = (
        lambda: repository.list_catalog_entries(),
        lambda: repository.list_alias_bindings(),
        lambda: repository.get_catalog_entry("catalog:test"),
        lambda: repository.get_alias_binding("binding:test"),
        lambda: repository.clear(),
        lambda: repository.bootstrap_if_empty(*build_bootstrap_catalog()),
    )
    for operation in operations:
        with pytest.raises(CatalogLifecycleRepositoryError) as captured:
            operation()
        assert captured.value.error_code == "mo.catalog_persistence_unavailable"


def test_repository_rejects_malformed_persisted_projection(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entry = build_bootstrap_catalog()[0][0]
    repository.insert_catalog_entry(entry)
    with session_factory() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE mo_model_catalog "
                    "SET response_formats_json = :value WHERE catalog_id = :catalog_id"
                ),
                {"value": "{}", "catalog_id": entry.catalog_id},
            )
    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        repository.get_catalog_entry(entry.catalog_id)
    assert captured.value.error_code == "mo.catalog_persistence_unavailable"


def test_write_requires_durable_readback(
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entry = build_bootstrap_catalog()[0][0]
    monkeypatch.setattr(repository, "get_catalog_entry", lambda catalog_id: None)
    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        repository.insert_catalog_entry(entry)
    assert captured.value.error_code == "mo.catalog_write_failed"
    assert repository.clear() == (1, 0)

    repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    entries, bindings = build_bootstrap_catalog()
    repository.insert_catalog_entry(entries[0])
    binding = bindings[0]
    monkeypatch.setattr(repository, "get_alias_binding", lambda binding_id: None)
    with pytest.raises(CatalogLifecycleRepositoryError) as alias_error:
        repository.insert_alias_binding(binding)
    assert alias_error.value.error_code == "mo.alias_write_failed"


def test_bootstrap_maps_integrity_conflict() -> None:
    session = Mock()
    count_result = Mock()
    count_result.scalar_one.return_value = 0
    session.execute.side_effect = [
        count_result,
        IntegrityError("insert", {}, RuntimeError("conflict")),
    ]
    repository = SqlAlchemyCatalogLifecycleRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        repository.bootstrap_if_empty(*build_bootstrap_catalog())

    assert captured.value.error_code == "mo.catalog_conflict"
    session.rollback.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    ("commit_error", "expected_code"),
    [
        (
            IntegrityError("commit", {}, RuntimeError("conflict")),
            "mo.catalog_conflict",
        ),
        (SQLAlchemyError("offline"), "mo.catalog_persistence_unavailable"),
    ],
)
def test_write_context_maps_commit_failures(
    commit_error: Exception,
    expected_code: str,
) -> None:
    session = Mock()
    session.commit.side_effect = commit_error

    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        with _RepositoryWriteSession(lambda: session):  # type: ignore[arg-type]
            pass

    assert captured.value.error_code == expected_code
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_write_context_maps_body_errors_and_rolls_back() -> None:
    session = Mock()

    with pytest.raises(CatalogLifecycleRepositoryError) as captured:
        with _RepositoryWriteSession(lambda: session):  # type: ignore[arg-type]
            raise ValueError("broken payload")

    assert captured.value.error_code == "mo.catalog_persistence_unavailable"
    session.rollback.assert_called_once()
    session.close.assert_called_once()

    other_session = Mock()
    with pytest.raises(RuntimeError, match="caller failure"):
        with _RepositoryWriteSession(lambda: other_session):  # type: ignore[arg-type]
            raise RuntimeError("caller failure")
    other_session.rollback.assert_called_once()
    other_session.close.assert_called_once()


def test_timestamp_canonicalization_accepts_database_and_naive_values() -> None:
    assert _canonical_timestamp(datetime(2026, 10, 1)) == "2026-10-01T00:00:00Z"
    assert _canonical_timestamp("2026-10-01T09:00:00+09:00") == (
        "2026-10-01T00:00:00Z"
    )
