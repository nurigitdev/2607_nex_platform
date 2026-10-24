#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p8_s53_approval_resume_postgres as p8_s53
from nex_runtime import load_env_file
from p8_reliability_faults import ApprovalEventAckLossFaultClient

SCHEMA_VERSION = "p8_s81_approval_event_ack_loss.v1"
SMOKE_ENV = "NEX_P8_S81_PROTECTED_SMOKE"
DEFAULT_REPORT = ROOT / "reports/quality/p8-s81-approval-event-ack-loss.json"


def run_p8_s81_approval_event_ack_loss(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = p8_s53.DEFAULT_SOURCE,
    report_path: Path = DEFAULT_REPORT,
    python_bin: str = sys.executable,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S81",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
        }

    base_env = {**env, p8_s53.SMOKE_ENV: "1"}
    base = p8_s53.run_p8_s53_approval_resume_postgres(
        base_env,
        execute=True,
        source=source,
        report_path=Path("/tmp/p8-s81-approval-event-ack-loss-base.json"),
        python_bin=python_bin,
        approval_event_client_factory=ApprovalEventAckLossFaultClient,
    )
    scenarios = base.get("scenarios", {})
    checks = {
        "base_resume_gate_passed": base.get("status") == "PASS",
        "actual_ae_wc_postgres": base.get("actual_postgres") is True,
        "first_ack_lost_then_retry_confirmed": _all_scenarios(
            scenarios,
            _ack_loss_closed,
        ),
        "one_semantic_resume_job": _all_scenarios(
            scenarios,
            lambda case: case.get("resume_job_count") == 1
            and case.get("event_replay", {}).get("created") is False
            and case.get("event_replay", {}).get("resume_runtime_job_id")
            == case.get("matched_event", {}).get("resume_runtime_job_id"),
        ),
        "one_checkpoint_consume": _all_scenarios(
            scenarios,
            lambda case: case.get("resume", {}).get("claim_consumed") is True
            and case.get("resume", {}).get("checkpoint_consumed") is True
            and case.get("resume", {}).get("runtime_job_state") == "DONE",
        ),
        "approval_binding_preserved": _all_scenarios(
            scenarios,
            lambda case: case.get("lineage_exact") is True
            and case.get("platform_approval_evidence", {}).get(
                "approval_request_id"
            )
            == case.get("write_identity", {}).get("approval_request_id")
            and case.get("platform_approval_evidence", {}).get("payload_hash")
            == case.get("payload_hash"),
        ),
        "zero_eos_mutation": _all_scenarios(
            scenarios,
            lambda case: case.get("resume", {}).get("eos_mutation_count") == 0
            and case.get("prefix_audit", {}).get("write_requested_count") == 0,
        ),
        "cleanup_complete": _all_scenarios(
            scenarios, lambda case: case.get("cleanup_remaining") == 0
        ),
    }
    evidence: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "slice": "P8-S81",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "actual_postgres": base.get("actual_postgres", False),
        "remote_provider_required": False,
        "rustfs_required": False,
        "databases": base.get("databases", {}),
        "migrations": base.get("migrations", {}),
        "release": base.get("release", {}),
        "scenarios": scenarios,
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "decision": {
            "approval_event_ack_loss_closed": all(checks.values()),
            "semantic_resume_count_per_event": 1,
            "checkpoint_consume_count_per_event": 1,
        },
    }
    if base.get("issues"):
        evidence["issues"] = base["issues"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _all_scenarios(scenarios: object, predicate) -> bool:
    return (
        isinstance(scenarios, Mapping)
        and set(scenarios) == {"approve", "reject", "expiry"}
        and all(
            isinstance(case, Mapping) and predicate(case)
            for case in scenarios.values()
        )
    )


def _ack_loss_closed(case: Mapping[str, object]) -> bool:
    evidence = case.get("approval_event_ack_loss")
    if not isinstance(evidence, Mapping):
        return False
    binding_hash = evidence.get("approval_binding_hash")
    return evidence == {
        "delivery_attempts": 2,
        "downstream_acceptances": 2,
        "acknowledged_attempts": 1,
        "unique_event_count": 1,
        "unique_resume_job_count": 1,
        "approval_binding_hash": binding_hash,
    } and str(binding_hash).startswith("sha256:")


def summary_line(evidence: Mapping[str, object]) -> str:
    return (
        "p8_s81_approval_event_ack_loss="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"checks={evidence.get('checks_passed', 0)}/"
        f"{evidence.get('checks_total', 0)} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P8-S81 protected approval event ACK-loss gate"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=p8_s53.DEFAULT_SOURCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env.local")
    result = run_p8_s81_approval_event_ack_loss(
        execute=args.execute,
        source=args.source,
        report_path=args.report,
        python_bin=args.python_bin,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
