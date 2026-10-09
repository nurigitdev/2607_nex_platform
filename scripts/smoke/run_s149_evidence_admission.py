#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s149_evidence_admission.v1"
ACTIVATION_ENV = "NEX_S149_EVIDENCE_ADMISSION"
PROFILE_ENV = "NEX_S149_EVIDENCE_ADMISSION_PROFILE"
DEFAULT_PROFILE = "test"
REPORT_PATH = ROOT / "reports" / "deployment" / "s149-evidence-admission.json"
INPUT_REPORTS = {
    "1490": (
        ROOT / "reports" / "deployment" / "s149-single-host-live-acceptance.json",
        "s149_single_host_live_acceptance.v1",
    ),
    "1491": (
        ROOT / "reports" / "deployment" / "s149-release-bound-workload.json",
        "s149_release_bound_target_workload.v1",
    ),
    "1492": (
        ROOT / "reports" / "deployment" / "s149-under-load-acceptance.json",
        "s149_under_load_fault_security_rollback.v1",
    ),
}
SINGLE_HOST_BACKLOG = (
    (
        "multi_node_service_failover",
        "multi-node orchestrator and replicated service state",
    ),
    (
        "postgres_automatic_failover",
        "replicated PostgreSQL topology with promotion control",
    ),
    (
        "object_store_node_loss",
        "distributed object storage with quorum recovery",
    ),
    (
        "gpu_autoscaling_failover",
        "multiple GPU serving nodes and model revisions",
    ),
    (
        "external_dead_man_monitoring",
        "independent management node or external receiver",
    ),
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RELEASE_ID = re.compile(r"rc:s149:[0-9a-f]{16}\Z")


def run_s149_evidence_admission(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    input_reports: Mapping[str, tuple[Path, str]] = INPUT_REPORTS,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1493",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ACTIVATION_ENV}=1 are required.",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")

    try:
        evidence = {
            slice_id: _load_report(path, slice_id, schema)
            for slice_id, (path, schema) in input_reports.items()
        }
        if set(evidence) != set(INPUT_REPORTS):
            raise ValueError("S149 admission evidence set is incomplete")
        result = _evaluate(evidence)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - release admission fails closed
        return _failure(
            "evidence_admission_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )


def _load_report(path: Path, slice_id: str, schema: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Slice {slice_id} evidence is not an object")
    if value.get("slice") != slice_id:
        raise ValueError(f"Slice {slice_id} evidence identity drift")
    if value.get("evidence_schema_version") != schema:
        raise ValueError(f"Slice {slice_id} evidence schema drift")
    return value


def _evaluate(evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    s1490 = evidence["1490"]
    s1491 = evidence["1491"]
    s1492 = evidence["1492"]
    binding0 = _mapping(s1490.get("release_binding"))
    binding1 = _mapping(s1491.get("release_binding"))
    binding2 = _mapping(s1492.get("release_binding"))
    release_ids = {
        str(item.get("release_candidate_id") or "")
        for item in (binding0, binding1, binding2)
    }
    release_digests = {
        str(item.get("release_set_digest") or "")
        for item in (binding0, binding1, binding2)
    }
    workload1 = _mapping(s1491.get("workload"))
    metrics1 = _mapping(workload1.get("metrics"))
    shadow2 = _mapping(s1492.get("shadow_load"))
    metrics2 = _mapping(shadow2.get("metrics"))
    faults2 = _mapping(s1492.get("faults"))
    fault_summary2 = _mapping(faults2.get("summary"))
    cleanup1 = _mapping(s1491.get("cleanup"))
    cleanup2 = _mapping(s1492.get("cleanup"))
    scope0 = _mapping(s1490.get("execution_scope"))
    scope1 = _mapping(s1491.get("execution_scope"))
    scope2 = _mapping(s1492.get("execution_scope"))
    external = _mapping(s1490.get("external_notification"))
    backlog = _backlog_projection()
    checks = {
        "all_required_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "release_candidate_identity_consistent": len(release_ids) == 1
        and _RELEASE_ID.fullmatch(next(iter(release_ids))) is not None,
        "immutable_release_digest_consistent": len(release_digests) == 1
        and _DIGEST.fullmatch(next(iter(release_digests))) is not None,
        "evidence_chain_complete": binding1.get("s1490_evidence_digest")
        == _digest(s1490)
        and binding2.get("s1491_evidence_digest") == _digest(s1491),
        "workload_identity_consistent": binding1.get("workload_digest")
        == binding2.get("workload_digest")
        and bool(binding1.get("workload_digest")),
        "all_nested_checks_passed": all(
            _all_checks_pass(item) for item in evidence.values()
        ),
        "target_workload_exact_and_clean": metrics1.get("request_count") == 7_200
        and metrics1.get("success_count") == 7_200
        and cleanup1.get("residue_count") == 0,
        "under_load_workload_exact_and_clean": shadow2.get("request_count")
        == 1_440
        and metrics2.get("success_count") == 1_440
        and cleanup2.get("shadow_residue_count") == 0,
        "fault_recovery_complete": faults2.get("status") == "PASS"
        and fault_summary2.get("scenario_count") == 8
        and fault_summary2.get("recovered_count") == 8,
        "generation_reasoning_disabled": shadow2.get(
            "generation_reasoning_mode"
        )
        == "disabled",
        "all_rehearsal_residue_zero": all(
            cleanup2.get(name) == 0
            for name in (
                "shadow_residue_count",
                "client_fault_residue_count",
                "provider_residue_count",
            )
        )
        and cleanup2.get("storage_status") == "PASS",
        "production_and_provider_processes_untouched": scope0.get(
            "production_contacted"
        )
        is False
        and scope1.get("production_contacted") is False
        and scope2.get("production_contacted") is False
        and scope2.get("provider_process_mutation_performed") is False,
        "single_host_backlog_classified": len(backlog) == 5
        and all(
            item["disposition"] == "NOT_APPLICABLE_SINGLE_HOST"
            for item in backlog
        ),
        "external_notification_condition_explicit": external.get("status")
        == "EXTERNAL_NOT_ACTIVATED"
        and external.get("s150_requirement")
        == "time_bounded_p1_waiver_and_local_compensating_control",
    }
    passed = all(checks.values())
    release_candidate_id = next(iter(release_ids)) if len(release_ids) == 1 else None
    release_set_digest = (
        next(iter(release_digests)) if len(release_digests) == 1 else None
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1493",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s149_evidence_admission_failed",
        "release_binding": {
            "release_candidate_id": release_candidate_id,
            "release_set_digest": release_set_digest,
            "workload_digest": binding1.get("workload_digest"),
            "fault_plan_digest": binding2.get("fault_plan_digest"),
            "evidence_chain_digest": _digest_sequence(
                tuple(_digest(evidence[slice_id]) for slice_id in sorted(evidence))
            ),
        },
        "checks": checks,
        "evidence_sources": {
            slice_id: {
                "status": item.get("status"),
                "schema_version": item.get("evidence_schema_version"),
                "digest": _digest(item),
            }
            for slice_id, item in evidence.items()
        },
        "single_host_backlog": backlog,
        "s150_admission": {
            "status": (
                "CONDITIONALLY_READY" if passed else "NOT_ADMITTED"
            ),
            "s149_full_gate_complete": False,
            "external_notification_waiver": "REQUIRED_NOT_GRANTED",
            "local_compensating_control_required": True,
            "production_go_eligible": False,
            "open_conditions": (
                ["s149_full_gate", "external_notification_p1_waiver"]
                if passed
                else ["s149_evidence_failure"]
            ),
        },
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "evidence_source_count": len(evidence),
            "backlog_count": len(backlog),
            "target_request_count": metrics1.get("request_count"),
            "under_load_request_count": shadow2.get("request_count"),
            "recovered_fault_count": fault_summary2.get("recovered_count"),
        },
        "redaction": {
            "status": "PASS",
            "raw_nested_evidence_included": False,
            "credentials_included": False,
            "endpoint_urls_included": False,
            "private_payloads_included": False,
        },
        "next_slice": "1494" if passed else "blocked",
    }


def _backlog_projection() -> list[dict[str, str]]:
    return [
        {
            "backlog_id": backlog_id,
            "disposition": "NOT_APPLICABLE_SINGLE_HOST",
            "required_environment": required_environment,
            "target": "post-S150 distributed topology",
        }
        for backlog_id, required_environment in SINGLE_HOST_BACKLOG
    ]


def _all_checks_pass(value: Mapping[str, Any]) -> bool:
    checks = _mapping(value.get("checks"))
    return bool(checks) and all(item is True for item in checks.values())


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_sequence(values: Sequence[str]) -> str:
    payload = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _failure(code: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1493",
        "status": "FAIL",
        "failure_code": code,
        "next_slice": "blocked",
    }
    if diagnostics:
        result["diagnostics"] = dict(diagnostics)
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s149_evidence_admission=skipped"
    summary = _mapping(result.get("summary"))
    admission = _mapping(result.get("s150_admission"))
    return (
        "s149_evidence_admission="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"evidence={summary.get('evidence_source_count', 0)}/3 "
        f"backlog={summary.get('backlog_count', 0)}/5 "
        f"s150={str(admission.get('status') or 'NOT_ADMITTED').lower()} "
        f"next={result.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_s149_evidence_admission(
        execute=args.execute,
        report_path=args.report_path,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
