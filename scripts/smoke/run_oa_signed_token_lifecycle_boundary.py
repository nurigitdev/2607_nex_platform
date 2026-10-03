#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.service_principal_lifecycle_boundary import (  # noqa: E402
    DEFERRED_SIGNED_RUNTIME_TABLES,
)
from nex_oa.signed_token_lifecycle_boundary import (  # noqa: E402
    SIGNED_RUNTIME_TABLES,
    S127_SIGNED_TOKEN_BOUNDARY,
    validate_signed_token_boundary,
)


def run_oa_signed_token_lifecycle_boundary(root: Path = ROOT) -> dict[str, Any]:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "database/nex-oa/migrations").glob("*.sql"))
    )
    boundary = S127_SIGNED_TOKEN_BOUNDARY
    checks = {
        "boundary_contract_valid": (
            validate_signed_token_boundary(boundary.to_wire()) == ()
        ),
        "s126_handoff_fully_adopted": (
            tuple(DEFERRED_SIGNED_RUNTIME_TABLES) == SIGNED_RUNTIME_TABLES
        ),
        "table_names_short": max(map(len, SIGNED_RUNTIME_TABLES)) < 30,
        "signed_runtime_not_preimplemented": all(
            table not in migration_text for table in SIGNED_RUNTIME_TABLES
        ),
        "private_key_database_storage_forbidden": (
            not boundary.private_key_database_storage_allowed
        ),
        "raw_token_storage_and_logging_forbidden": (
            not boundary.raw_token_persistence_allowed
            and not boundary.raw_token_logging_allowed
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
        "boundary_schema_version": "oa_signed_token_lifecycle_boundary.v1",
        "slice": "1262",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signed_token_boundary_failed",
        "boundary": boundary.to_wire(),
        "existing_signed_runtime_table_count": sum(
            table in migration_text for table in SIGNED_RUNTIME_TABLES
        ),
        "checks": checks,
        "next_slice": "1263",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    boundary = evidence.get("boundary") or {}
    return (
        "oa_signed_token_lifecycle_boundary="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"tables={len(boundary.get('owned_tables') or ())} "
        f"algorithm={boundary.get('algorithm', 'unknown')} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_lifecycle_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
