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


NOW = "2026-10-01T01:00:00Z"


def run_mo_catalog_lifecycle_service() -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(temp_dir) / 'catalog-service.db'}"
        )
        with engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        repository = SqlAlchemyCatalogLifecycleRepository(factory)
        service = CatalogLifecycleService(
            repository,
            clock=lambda: NOW,
            id_factory=lambda: "candidate-1",
        )
        seeded = service.ensure_bootstrap()
        candidate = service.register_catalog_entry(
            RegisterCatalogEntry(
                provider_capability="generation",
                model_name="Generation Candidate",
                model_revision="candidate-v1",
                deployment_id="candidate-deployment",
                runtime_profile="generation-candidate",
                precision="BF16",
                provider_type="openai-compatible",
                supports_response_formats=("text", "json_object"),
                max_input_tokens=8192,
                max_output_tokens=1024,
            )
        )
        activated = service.transition_catalog_entry(
            candidate.catalog_id,
            expected_revision=1,
            target_state="ACTIVE",
        )
        stale_rejected = False
        try:
            service.transition_catalog_entry(
                candidate.catalog_id,
                expected_revision=1,
                target_state="RETIRED",
            )
        except CatalogLifecycleServiceError as exc:
            stale_rejected = exc.error_code == "MO_CATALOG_REVISION_CONFLICT"
        retired = service.transition_catalog_entry(
            candidate.catalog_id,
            expected_revision=2,
            target_state="RETIRED",
        )
        active_defaults = service.list_alias_bindings(state="ACTIVE")
        engine.dispose()

    checks = {
        "empty_store_bootstrapped": seeded is True,
        "candidate_registered_as_draft": candidate.catalog_state == "DRAFT"
        and candidate.revision == 1,
        "candidate_activated": activated.catalog_state == "ACTIVE"
        and activated.revision == 2,
        "stale_revision_rejected": stale_rejected,
        "unbound_candidate_retired": retired.catalog_state == "RETIRED"
        and retired.revision == 3,
        "default_aliases_unchanged": len(active_defaults) == 3,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_service.v1",
        "slice": "1175",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_service_failed",
        "checks": checks,
        "summary": {
            "candidate_revision": retired.revision,
            "active_default_binding_count": len(active_defaults),
            "stale_rejection_count": int(stale_rejected),
        },
        "next_slice": "1176" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_lifecycle_service="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"revision={summary.get('candidate_revision', 0)} "
        f"active_aliases={summary.get('active_default_binding_count', 0)} "
        f"stale_rejections={summary.get('stale_rejection_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_service()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
