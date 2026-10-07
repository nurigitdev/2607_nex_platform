#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_tls_lifecycle import (  # noqa: E402
    ManagedCertificateMetadata,
    build_production_tls_lifecycle_plan,
    certificate_expiry_alert,
    evaluate_production_tls_lifecycle,
    production_tls_lifecycle_projection,
)
from run_platform_production_startup_admission import _synthetic_environment  # noqa: E402


SCHEMA_VERSION = "platform_production_tls_lifecycle_evidence.v1"
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)


def run_platform_production_tls_lifecycle(root: Path = ROOT) -> dict[str, Any]:
    environment = _tls_v2_environment(root)
    current = _certificate("platform-current", "v1", "ACTIVE", NOW - timedelta(days=60), NOW + timedelta(days=45))
    candidate = _certificate("platform-candidate", "v2", "CANDIDATE", NOW - timedelta(hours=3), NOW + timedelta(days=90))
    plan = build_production_tls_lifecycle_plan(environment, current, candidate, root=root)
    staged = evaluate_production_tls_lifecycle(
        plan, observed_at=NOW, activation_attempted=False, candidate_probe_verified=False
    )
    overlap = evaluate_production_tls_lifecycle(
        plan,
        observed_at=NOW,
        activation_attempted=True,
        candidate_probe_verified=True,
        candidate_verified_at=NOW - timedelta(minutes=30),
    )
    verified = evaluate_production_tls_lifecycle(
        plan,
        observed_at=NOW,
        activation_attempted=True,
        candidate_probe_verified=True,
        candidate_verified_at=NOW - timedelta(hours=2),
    )
    rollback = evaluate_production_tls_lifecycle(
        plan, observed_at=NOW, activation_attempted=True, candidate_probe_verified=False
    )
    projection = production_tls_lifecycle_projection(plan, verified)
    alert_checks = {
        "ok": certificate_expiry_alert(current, observed_at=NOW) == "OK",
        "warning": certificate_expiry_alert(
            replace(current, not_after=NOW + timedelta(days=20)), observed_at=NOW
        ) == "WARNING",
        "critical": certificate_expiry_alert(
            replace(current, not_after=NOW + timedelta(days=3)), observed_at=NOW
        ) == "CRITICAL",
        "expired": certificate_expiry_alert(
            replace(current, not_after=NOW), observed_at=NOW
        ) == "EXPIRED",
    }
    passed = (
        staged.status == "STAGED"
        and overlap.status == "OVERLAP_VERIFYING"
        and overlap.retire_current_approved is False
        and verified.status == "VERIFIED"
        and verified.retire_current_approved
        and rollback.status == "ROLLBACK_REQUIRED"
        and rollback.rollback_to_current_required
        and all(alert_checks.values())
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1429",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "tls_lifecycle": projection,
        "alert_checks": alert_checks,
        "summary": {
            "rotation_phase_count": len(plan.rotation_phases),
            "rollback_phase_count": len(plan.rollback_phases),
            "expiry_alert_level_count": len(alert_checks),
            "private_key_exposure_count": int(plan.current.private_key_exposed) + int(plan.candidate.private_key_exposed),
        },
        "decision": {
            "managed_tls_lifecycle_verified": passed,
            "actual_certificate_rotated": False,
            "external_tls_endpoint_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1430" if passed else "blocked",
        },
    }


def _tls_v2_environment(root: Path = ROOT) -> dict[str, str]:
    environment = _synthetic_environment(root)
    environment["NEX_TLS_GENERATION"] = "tls:2026-10-07.2"
    environment["NEX_TLS_CERTIFICATE_REF"] = "tls://managed/platform/certificate@v2"
    environment["NEX_TLS_TRUST_BUNDLE_REF"] = "tls://managed/platform/trust-bundle@v2"
    return environment


def _certificate(certificate_id, version, state, not_before, not_after):
    return ManagedCertificateMetadata(
        certificate_id=certificate_id,
        version=version,
        state=state,
        not_before=not_before,
        not_after=not_after,
        issuer_id="managed-ca",
        dns_name_count=9,
        private_key_exposed=False,
    )


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_tls_lifecycle=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_tls_lifecycle=pass "
        f"phases={summary.get('rotation_phase_count', 0)} "
        f"rollback={summary.get('rollback_phase_count', 0)} "
        f"alerts={summary.get('expiry_alert_level_count', 0)} "
        f"private_keys={summary.get('private_key_exposure_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_tls_lifecycle()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
