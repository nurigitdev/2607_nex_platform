#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime.platform_trust_evidence import (  # noqa: E402
    REQUIRED_DENIALS,
    REQUIRED_HOPS,
    evaluate_platform_trust_evidence,
)


def sample_platform_trust_evidence() -> dict[str, Any]:
    hops = []
    for hop_id in REQUIRED_HOPS:
        browser = hop_id == "nex-ae-api"
        hops.append(
            {
                "hop_id": hop_id,
                "service_id": "nex-oa" if hop_id == "oa_user_login" else hop_id,
                "status_code": 200,
                "auth_kind": "OPAQUE_USER_SESSION" if browser else "SIGNED_SERVICE",
                "jwks_verified": not browser,
                "scope_enforced": not browser,
                "introspection_status": "NOT_APPLICABLE" if browser else "ACTIVE",
                "owner_claim_authoritative": browser,
                "request_id_propagated": True,
                "trace_id_propagated": True,
            }
        )
    return evaluate_platform_trust_evidence(
        {
            "hops": hops,
            "denials": [
                {
                    "scenario": scenario,
                    "service_id": "nex-oa" if "revoked" in scenario else "nex-cx",
                    "status_code": 401 if "revoked" in scenario else 403,
                    "error_code": f"nex.{scenario}",
                    "failed_closed": True,
                }
                for scenario in REQUIRED_DENIALS
            ],
            "restart": {
                "generation_count": 2,
                "user_session_restored": True,
                "signing_key_restored": True,
                "revoked_service_token_denied": True,
            },
            "databases": {
                "service_count": 5,
                "migration_count": 89,
                "cleanup_residue_count": 0,
                "temporary_key_residue_count": 0,
            },
        }
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    if evidence.get("status") != "PASS":
        return (
            "platform_trust_evidence=fail "
            f"checks={len(evidence.get('failed_checks') or [])} "
            f"privacy={summary.get('privacy_violation_count', 0)}"
        )
    return (
        "platform_trust_evidence=pass "
        f"hops={summary.get('passed_hop_count', 0)}/{summary.get('hop_count', 0)} "
        f"denials={summary.get('passed_denial_count', 0)}/{summary.get('denial_count', 0)} "
        f"restarts={summary.get('restart_generation_count', 0)} "
        f"databases={summary.get('database_service_count', 0)} next=1337"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = sample_platform_trust_evidence()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

