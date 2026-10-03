#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.service_principal_boundary import (  # noqa: E402
    S126_SERVICE_PRINCIPAL_HANDOFF,
)
from nex_oa.service_principal_lifecycle_boundary import (  # noqa: E402
    DEFERRED_SIGNED_RUNTIME_TABLES,
    LIFECYCLE_TABLES,
    S126_LIFECYCLE_BOUNDARY,
    validate_lifecycle_boundary,
)


def run_oa_service_principal_lifecycle_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "database/nex-oa/migrations").glob("*.sql"))
    )
    boundary = S126_LIFECYCLE_BOUNDARY
    predecessor_tables = set(S126_SERVICE_PRINCIPAL_HANDOFF.proposed_tables)
    assigned_tables = set(boundary.lifecycle_tables) | set(boundary.deferred_tables)
    checks = {
        "boundary_contract_valid": (
            validate_lifecycle_boundary(boundary.to_wire()) == ()
        ),
        "predecessor_handoff_fully_refined": predecessor_tables == assigned_tables,
        "lifecycle_table_names_short": max(map(len, LIFECYCLE_TABLES)) < 30,
        "deferred_table_names_short": (
            max(map(len, DEFERRED_SIGNED_RUNTIME_TABLES)) < 30
        ),
        "deferred_runtime_not_implemented_in_s126": all(
            table not in migration_text for table in DEFERRED_SIGNED_RUNTIME_TABLES
        ),
        "plaintext_secret_forbidden": (
            not boundary.database_plaintext_secret_allowed
        ),
        "cross_service_database_reads_forbidden": (
            not boundary.cross_service_database_reads_allowed
        ),
        "remote_model_provider_not_required": (
            not boundary.remote_model_provider_required
        ),
    }
    passed = all(checks.values())
    return {
        "boundary_schema_version": "oa_service_principal_lifecycle_boundary.v1",
        "slice": "1252",
        "requirement": "S126",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_service_principal_boundary_failed",
        "boundary": boundary.to_wire(),
        "existing_lifecycle_table_count": sum(
            table in migration_text for table in LIFECYCLE_TABLES
        ),
        "checks": checks,
        "next_slice": "1253",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    boundary = evidence.get("boundary") or {}
    return (
        "oa_service_principal_lifecycle_boundary="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"owned_tables={len(boundary.get('lifecycle_tables') or ())} "
        f"deferred={boundary.get('deferred_requirement')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_service_principal_lifecycle_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
