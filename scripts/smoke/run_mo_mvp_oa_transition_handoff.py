#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_mo_mvp_acceptance,
)
from nex_mo.mvp_oa_transition_handoff import (  # noqa: E402
    PRIVACY_FLAGS,
    REQUIRED_ASSET_PATHS,
    bind_mo_mvp_oa_transition_handoff,
    build_mo_mvp_oa_transition_candidate,
    verify_mo_mvp_oa_transition_attestation,
    verify_mo_mvp_oa_transition_handoff,
)
from run_mo_mvp_acceptance_evaluator import (  # noqa: E402
    build_passing_evidence,
)


SCHEMA_VERSION = "mo_mvp_oa_transition_handoff_evidence.v1"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def run_mo_mvp_oa_transition_handoff(
    root: Path = ROOT,
    *,
    observed_at: datetime = NOW,
) -> dict[str, Any]:
    try:
        candidate = build_mo_mvp_oa_transition_candidate(
            generated_at=observed_at,
            root=root,
        )
        report = evaluate_mo_mvp_acceptance(
            build_passing_evidence(),
            now=observed_at,
        )
        attestation = bind_mo_mvp_oa_transition_handoff(
            candidate,
            report,
            bound_at=observed_at,
        )
        manifest_verification = verify_mo_mvp_oa_transition_handoff(candidate)
        attestation_verification = verify_mo_mvp_oa_transition_attestation(
            attestation,
            candidate=candidate,
            acceptance_report=report,
        )
    except Exception as exc:
        return _failed_evidence(type(exc).__name__)

    checks = {
        "manifest_verified": manifest_verification["status"] == "VERIFIED",
        "required_assets_complete": len(candidate["assets"])
        == len(REQUIRED_ASSET_PATHS),
        "acceptance_ready": report["status"] == "ACCEPTED"
        and report["transition_status"] == "READY_FOR_OA",
        "attestation_verified": attestation_verification["status"] == "VERIFIED",
        "oa_target_bound": candidate["target_service"] == "nex-oa"
        and attestation["target_service"] == "nex-oa",
        "direct_database_access_forbidden": candidate["read_model"][
            "oa_direct_mo_database_access_allowed"
        ]
        is False,
        "privacy_flags_closed": candidate["privacy"] == PRIVACY_FLAGS
        and not any(candidate["privacy"].values()),
        "s121_entrypoint_declared": candidate["oa_entrypoint"]["requirement"]
        == "S121",
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    passed = not failed_checks
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1198",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo.oa_transition_handoff.evidence_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "asset_count": len(candidate["assets"]),
            "privacy_flag_count": len(candidate["privacy"]),
            "model_alias_count": len(candidate["model_aliases"]),
            "manifest_status": candidate["manifest_status"],
            "attestation_status": attestation["attestation_status"],
        },
        "acceptance_gate_evidence": {
            "oa_transition_handoff": {
                "status": "PASS" if passed else "FAIL",
                "observed_at": _timestamp(observed_at),
                "target_service": candidate["target_service"],
                "manifest_status": candidate["manifest_status"],
            }
        },
        "next_slice": "1199" if passed else "blocked",
    }


def _failed_evidence(detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1198",
        "requirement": "S120",
        "status": "FAIL",
        "failure_code": "mo.oa_transition_handoff.evidence_unavailable",
        "failure_detail": detail,
        "checks": {},
        "failed_checks": ["handoff_evidence_unavailable"],
        "summary": {},
        "acceptance_gate_evidence": {},
        "next_slice": "blocked",
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_mvp_oa_transition_handoff="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"assets={summary.get('asset_count', 0)} "
        f"privacy={summary.get('privacy_flag_count', 0)} "
        f"manifest={summary.get('manifest_status', 'UNAVAILABLE')} "
        f"attestation={summary.get('attestation_status', 'UNAVAILABLE')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_mvp_oa_transition_handoff()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
