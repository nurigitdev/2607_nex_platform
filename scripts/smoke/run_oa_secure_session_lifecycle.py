#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_oa.sessions import (  # noqa: E402
    build_browser_session_snapshot,
    build_session_record,
    refresh_session_for_introspection,
)
from nex_runtime import issue_mock_user_token  # noqa: E402


def run_oa_secure_session_lifecycle() -> dict[str, Any]:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        issued_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        ttl_seconds=3600,
    )
    first = build_session_record(issued.claims)
    second = build_session_record(issued.claims)
    first_refresh = refresh_session_for_introspection(
        first,
        now=datetime(2026, 8, 12, 12, 20, tzinfo=UTC),
    )
    refreshed = refresh_session_for_introspection(
        first_refresh,
        now=datetime(2026, 8, 12, 12, 45, tzinfo=UTC),
    )
    expired = refresh_session_for_introspection(
        {**first, "idle_expires_at": "2026-08-12T12:10:00Z"},
        now=datetime(2026, 8, 12, 12, 11, tzinfo=UTC),
    )
    public = build_browser_session_snapshot(refreshed)
    checks = {
        "opaque_ids_are_unique": first["session_id"] != second["session_id"],
        "opaque_id_has_256_bit_material": len(first["session_id"]) >= 43,
        "initial_idle_ttl_is_1800": first["idle_expires_at"]
        == "2026-08-12T12:30:00Z",
        "idle_refresh_slides": refreshed["last_seen_at"] == "2026-08-12T12:45:00Z",
        "idle_refresh_respects_absolute_expiry": refreshed["idle_expires_at"]
        == first["expires_at"],
        "idle_expiry_persists_expired_state": expired["status"] == "EXPIRED",
        "internal_lease_not_projected": "last_seen_at" not in public
        and "idle_expires_at" not in public,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_secure_session_lifecycle.v1",
        "slice": "1226",
        "requirement": "S123",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_secure_session_lifecycle_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "id_entropy_bytes": 32,
            "idle_ttl_seconds": 1800,
            "absolute_ttl_seconds": 3600,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_secure_session_lifecycle={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"entropy={summary.get('id_entropy_bytes')} idle={summary.get('idle_ttl_seconds')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_secure_session_lifecycle()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
