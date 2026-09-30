#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import (  # noqa: E402
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from run_mo_catalog_lifecycle_repository import SQLITE_SCHEMA  # noqa: E402


NOW = "2026-10-01T02:00:00Z"


def run_mo_alias_lifecycle() -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        engine = create_engine(f"sqlite+pysqlite:///{Path(temp_dir) / 'alias.db'}")
        with engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        repository = SqlAlchemyCatalogLifecycleRepository(factory)
        identifiers = iter(("candidate", "switch", "rollback"))
        service = CatalogLifecycleService(
            repository,
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
        )
        service.ensure_bootstrap()
        original = next(
            binding
            for binding in service.list_alias_bindings(state="ACTIVE")
            if binding.provider_capability == "generation"
        )
        candidate = service.register_catalog_entry(
            RegisterCatalogEntry(
                provider_capability="generation",
                model_name="Generation Candidate",
                model_revision="candidate-v1",
                deployment_id="candidate-deployment",
                runtime_profile="generation-candidate",
                precision="BF16",
                provider_type="openai-compatible",
                supports_response_formats=("text",),
                max_input_tokens=8192,
                max_output_tokens=1024,
            )
        )
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
            changed_by="operator:smoke",
        )
        stale_rejected = False
        try:
            service.rollback_alias(
                alias=original.alias,
                capability="generation",
                expected_binding_revision=1,
                change_reason="Stale rollback",
                changed_by="operator:smoke",
            )
        except CatalogLifecycleServiceError as exc:
            stale_rejected = exc.error_code == "MO_ALIAS_REVISION_CONFLICT"
        rolled_back = service.rollback_alias(
            alias=original.alias,
            capability="generation",
            expected_binding_revision=2,
            change_reason="Candidate regression",
            changed_by="operator:smoke",
        )
        history = service.list_alias_bindings(
            alias=original.alias,
            capability="generation",
        )
        engine.dispose()

    checks = {
        "candidate_activated_atomically": activated.binding_revision == 2
        and activated.catalog_id == candidate.catalog_id,
        "stale_revision_rejected": stale_rejected,
        "prior_target_restored": rolled_back.catalog_id == original.catalog_id,
        "rollback_appended_revision": rolled_back.binding_revision == 3,
        "history_preserved": [item.binding_state for item in history]
        == ["SUPERSEDED", "ROLLED_BACK", "ACTIVE"],
        "single_active_binding": sum(
            item.binding_state == "ACTIVE" for item in history
        )
        == 1,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_alias_lifecycle.v1",
        "slice": "1176",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_alias_lifecycle_failed",
        "checks": checks,
        "summary": {
            "binding_revision": rolled_back.binding_revision,
            "history_count": len(history),
            "active_binding_count": sum(
                item.binding_state == "ACTIVE" for item in history
            ),
            "stale_rejection_count": int(stale_rejected),
        },
        "next_slice": "1177" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_alias_lifecycle="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"revision={summary.get('binding_revision', 0)} "
        f"history={summary.get('history_count', 0)} "
        f"active={summary.get('active_binding_count', 0)} "
        f"stale={summary.get('stale_rejection_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_alias_lifecycle()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
