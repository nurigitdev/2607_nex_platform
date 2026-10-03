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
    validate_service_credential_record,
    validate_service_principal_spec,
)


def run_oa_service_principal_handoff(root: Path = ROOT) -> dict[str, Any]:
    principal = {
        "principal_id": "principal-1",
        "service_id": "nex-ae-api",
        "display_name": "NeX AE API",
        "status": "ACTIVE",
        "allowed_audiences": ["nex-oa", "nex-cx"],
        "allowed_scopes": ["service:call", "document:read"],
        "revision": 1,
    }
    credential = {
        "credential_id": "credential-1",
        "principal_id": "principal-1",
        "secret_hash": "$argon2id$v=19$m=65536,t=3,p=4$hash",
        "secret_hint": "a1b2",
        "status": "ACTIVE",
        "issued_at": 1_000,
        "expires_at": 1_000 + 90 * 86_400,
        "grace_until": 1_000 + 86_400,
        "revision": 1,
    }
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _historical_migrations(root)
    )
    handoff = S126_SERVICE_PRINCIPAL_HANDOFF
    checks = {
        "principal_contract_valid": validate_service_principal_spec(principal) == (),
        "credential_contract_valid": (
            validate_service_credential_record(credential) == ()
        ),
        "proposed_table_names_short": (
            max(map(len, handoff.proposed_tables)) < 30
        ),
        "no_s125_table_created": all(
            table not in migration_text for table in handoff.proposed_tables
        ),
        "plaintext_secret_forbidden": (
            not handoff.database_plaintext_secret_allowed
        ),
        "audience_and_scope_must_be_explicit": (
            not handoff.silent_default_audience_or_scope_allowed
        ),
        "handoff_targets_s126": handoff.implementation_requirement == "S126",
    }
    passed = all(checks.values())
    return {
        "handoff_schema_version": "oa_service_principal_handoff.v1",
        "slice": "1247",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_service_principal_handoff_failed",
        "handoff": handoff.to_wire(),
        "implementation_order": (
            "migration_and_repository",
            "one_time_credential_issue_and_rotation",
            "signed_service_token_exchange",
            "jwks_and_introspection",
            "cross_service_signed_only_rollout",
        ),
        "checks": checks,
        "next_slice": "1248",
    }


def _historical_migrations(root: Path) -> tuple[Path, ...]:
    paths = sorted((root / "database/nex-oa/migrations").glob("*.sql"))
    historical = []
    for path in paths:
        prefix = path.stem.split("_", maxsplit=1)[0]
        if not prefix.isdigit() or int(prefix) <= 1247:
            historical.append(path)
    return tuple(historical)


def summary_line(evidence: Mapping[str, Any]) -> str:
    handoff = evidence.get("handoff") or {}
    return (
        "oa_service_principal_handoff="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"tables={len(handoff.get('proposed_tables') or ())} "
        f"target={handoff.get('implementation_requirement')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_service_principal_handoff()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
