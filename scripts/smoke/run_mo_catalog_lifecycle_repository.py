#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.catalog_lifecycle import build_bootstrap_catalog  # noqa: E402
from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    SqlAlchemyCatalogLifecycleRepository,
)


SQLITE_SCHEMA = """
CREATE TABLE mo_model_catalog (
    catalog_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    runtime_profile TEXT NOT NULL,
    precision TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    response_formats_json TEXT NOT NULL,
    max_input_tokens INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    embedding_dimensions INTEGER,
    catalog_state TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (capability, deployment_id, model_revision)
);
CREATE TABLE mo_alias_bindings (
    binding_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    capability TEXT NOT NULL,
    catalog_id TEXT NOT NULL REFERENCES mo_model_catalog(catalog_id),
    binding_revision INTEGER NOT NULL,
    binding_state TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    previous_binding_id TEXT REFERENCES mo_alias_bindings(binding_id),
    created_at TEXT NOT NULL,
    UNIQUE (alias, capability, binding_revision)
);
CREATE UNIQUE INDEX uq_mo_alias_binding_active
    ON mo_alias_bindings (alias, capability)
    WHERE binding_state = 'ACTIVE';
"""


def run_mo_catalog_lifecycle_repository(root: Path = ROOT) -> dict[str, Any]:
    migration = root / "database/nex-mo/migrations/1174_mo_catalog_lifecycle.sql"
    with TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "catalog.db"
        engine = create_engine(f"sqlite+pysqlite:///{database_path}")
        with engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        repository = SqlAlchemyCatalogLifecycleRepository(factory)
        entries, bindings = build_bootstrap_catalog()
        seeded = repository.bootstrap_if_empty(entries, bindings)
        seeded_again = repository.bootstrap_if_empty(entries, bindings)
        engine.dispose()

        restarted_engine = create_engine(f"sqlite+pysqlite:///{database_path}")
        restarted_factory = sessionmaker(
            bind=restarted_engine,
            autoflush=False,
            expire_on_commit=False,
        )
        restarted = SqlAlchemyCatalogLifecycleRepository(restarted_factory)
        durable_entries = restarted.list_catalog_entries()
        durable_bindings = restarted.list_alias_bindings(state="ACTIVE")
        cleanup = restarted.clear()
        restarted_engine.dispose()

    migration_source = migration.read_text(encoding="utf-8") if migration.is_file() else ""
    checks = {
        "migration_registered": "1174_mo_catalog_lifecycle" in migration_source
        and "INSERT INTO schema_migrations" in migration_source,
        "short_tables_present": all(
            name in migration_source
            for name in ("mo_model_catalog", "mo_alias_bindings")
        ),
        "partial_active_alias_constraint_present": (
            "WHERE binding_state = 'ACTIVE'" in migration_source
        ),
        "empty_store_seeded_once": seeded is True and seeded_again is False,
        "restart_recovered_three_entries": len(durable_entries) == 3,
        "restart_recovered_three_active_bindings": len(durable_bindings) == 3,
        "targeted_cleanup_complete": cleanup == (3, 3),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_repository.v1",
        "slice": "1174",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_repository_failed",
        "checks": checks,
        "summary": {
            "migration_present": migration.is_file(),
            "catalog_entry_count": len(durable_entries),
            "active_binding_count": len(durable_bindings),
            "deleted_entry_count": cleanup[0],
            "deleted_binding_count": cleanup[1],
        },
        "next_slice": "1175" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_lifecycle_repository="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"entries={summary.get('catalog_entry_count', 0)} "
        f"bindings={summary.get('active_binding_count', 0)} "
        f"deleted={summary.get('deleted_entry_count', 0)}/"
        f"{summary.get('deleted_binding_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_repository()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
