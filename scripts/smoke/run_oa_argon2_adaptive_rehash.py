#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_oa.credentials import (  # noqa: E402
    ARGON2ID_PASSWORD_HASH_ALGORITHM,
    InMemoryOaCredentialRegistry,
    PASSWORD_HASH_ALGORITHM,
    hash_password,
    password_hash_algorithm,
    password_hash_needs_rehash,
    verify_password,
)


def run_oa_argon2_adaptive_rehash() -> dict[str, Any]:
    password = "Nuri1004!"
    modern = hash_password(password)
    legacy = hash_password(password, salt=b"1234567890123456", iterations=10)
    registry = InMemoryOaCredentialRegistry()
    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password_hash": legacy,
        }
    )
    changed_at = registry.credentials[("tenant-a", "emp-001")]["password_changed_at"]
    registry.verify_credential(
        {"tenant_id": "tenant-a", "employee_id": "EMP-001", "password": password}
    )
    upgraded = registry.credentials[("tenant-a", "emp-001")]
    checks = {
        "new_hash_uses_argon2id": password_hash_algorithm(modern)
        == ARGON2ID_PASSWORD_HASH_ALGORITHM,
        "argon2id_verifies": verify_password(password, password_hash=modern),
        "argon2id_is_current": not password_hash_needs_rehash(modern),
        "legacy_hash_recognized": password_hash_algorithm(legacy)
        == PASSWORD_HASH_ALGORITHM,
        "legacy_hash_requires_rehash": password_hash_needs_rehash(legacy),
        "login_upgrades_legacy_hash": upgraded["password_hash_algorithm"]
        == ARGON2ID_PASSWORD_HASH_ALGORITHM,
        "rehash_preserves_password_changed_at": upgraded["password_changed_at"]
        == changed_at,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_argon2_adaptive_rehash.v1",
        "slice": "1223",
        "requirement": "S123",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_argon2_adaptive_rehash_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "default_algorithm": ARGON2ID_PASSWORD_HASH_ALGORITHM,
            "legacy_algorithm": PASSWORD_HASH_ALGORITHM,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_argon2_adaptive_rehash={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"default={summary.get('default_algorithm')} legacy={summary.get('legacy_algorithm')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_argon2_adaptive_rehash()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
