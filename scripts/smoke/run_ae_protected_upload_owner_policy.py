#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.upload_owner_policy import (
    UploadOwnerPolicyError,
    enforce_upload_owner_policy,
    upload_owner_policy_projection,
)


SCHEMA_VERSION = "ae_protected_upload_owner_policy_evidence.v1"


def run_ae_protected_upload_owner_policy(root: Path = ROOT) -> dict[str, Any]:
    uploads_source = _read_text(root / "services/nex-ae-api/nex_ae_api/uploads.py")
    protected_projection = upload_owner_policy_projection("test")
    local_projection = upload_owner_policy_projection("local_mock")
    denial_codes = []
    for payload in (
        {},
        {"tenant_id": "tenant-a"},
        {"tenant_id": "local-tenant", "owner_user_id": "local-user"},
    ):
        try:
            enforce_upload_owner_policy(payload, runtime_profile="test")
        except UploadOwnerPolicyError as exc:
            denial_codes.append(exc.error_code)

    accepted = enforce_upload_owner_policy(
        {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        runtime_profile="test",
    )
    checks = {
        "route_applies_runtime_profile": "resolved_runtime_profile" in uploads_source,
        "route_applies_owner_policy": "enforce_upload_owner_policy" in uploads_source,
        "protected_fallback_disabled": protected_projection["local_owner_fallback_allowed"] is False,
        "local_mock_fallback_preserved": local_projection["local_owner_fallback_allowed"] is True,
        "missing_scope_denied": denial_codes.count("ae.upload_owner_scope_required") == 2,
        "placeholder_scope_denied": "ae.upload_owner_scope_placeholder_forbidden" in denial_codes,
        "explicit_service_scope_accepted": accepted
        == {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1343",
        "requirement": "S135",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "protected_projection": protected_projection,
        "local_projection": local_projection,
        "denial_codes": sorted(set(denial_codes)),
        "next_slice": "1344",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "ae_protected_upload_owner_policy=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    checks = evidence.get("checks") or {}
    return (
        "ae_protected_upload_owner_policy=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"denials={len(evidence.get('denial_codes') or [])} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_protected_upload_owner_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
