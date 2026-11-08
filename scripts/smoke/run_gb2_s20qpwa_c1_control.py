#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_sync_capacity import (
    evaluate_sync_capacity_receipt,
)
from nex_cx.retrieval_answer_support_sync_capacity_control import (
    evaluate_sync_capacity_control_receipt,
    validate_sync_capacity_control_entry,
)
from nex_mo import remote_provider
from nex_runtime.model_artifact_revision import (
    admit_model_artifact_revision_evidence,
    model_artifact_revision_evidence_digest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpw_sync_capacity import (
    ARTIFACT_PATH,
    CASES_PATH,
    REQUEST_PROFILE_PATH,
    SIGNAL_DESIGN_PATH,
    _assert_redacted,
    _bind_provider,
    _budgeted_requester,
    _capacity_cases,
    _configuration_issues,
    _load,
    _mapping,
    _probe_ports,
    _replace_json,
    _run_profile,
    _write_exclusive_json,
)
from run_gb2_s20qpw_sync_capacity import (
    DESIGN_PATH as CAPACITY_DESIGN_PATH,
)
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpwa_c1_control.v1"
SMOKE_ENV = "NEX_GB2_S20QPWA_C1_CONTROL"
APPROVED_ENV = "NEX_GB2_S20QPWA_OPERATOR_APPROVED"
IDLE_ENV = "NEX_GB2_S20QPWA_DGX_IDLE_CONFIRMED"
OPERATOR_ENV = "NEX_GB2_S20QPWA_OPERATOR_ID"
RECEIPT_ENV = "NEX_GB2_S20QPWA_RECEIPT_PATH"

CONTROL_DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_sync_capacity_c1_control_v1_design.json"
)
CAPACITY_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpw_sync_capacity_receipt.json"
DEFAULT_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpwa_c1_control_receipt.json"
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpwa_c1_control.json"


def run_gb2_s20qpwa_c1_control(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Any = None,
    collector: Any = None,
    port_probe: Any = None,
    control_design: Mapping[str, Any] | None = None,
    capacity_design: Mapping[str, Any] | None = None,
    capacity_receipt: Mapping[str, Any] | None = None,
    cases_document: Mapping[str, Any] | None = None,
    signal_design: Mapping[str, Any] | None = None,
    request_profile: Mapping[str, Any] | None = None,
    artifact_evidence: Mapping[str, Any] | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(APPROVED_ENV) != "1" or not env.get(OPERATOR_ENV):
        return _failure("operator_approval_required")
    if env.get(IDLE_ENV) != "1":
        return _failure("dgx_idle_confirmation_required")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
        "NEX_MO_VLLM_TIMEOUT_SECONDS": "60",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)
    target = receipt_path or Path(
        effective_env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH))
    )
    if target.exists():
        return _failure("c1_control_already_consumed")

    provider_counts = {"total": 0}
    protected_cases: list[Mapping[str, Any]] = []
    try:
        control_design_value = dict(control_design or _load(CONTROL_DESIGN_PATH))
        capacity_design_value = dict(capacity_design or _load(CAPACITY_DESIGN_PATH))
        capacity_receipt_value = dict(capacity_receipt or _load(CAPACITY_RECEIPT_PATH))
        cases_value = dict(cases_document or _load(CASES_PATH))
        signal_value = dict(signal_design or _load(SIGNAL_DESIGN_PATH))
        request_profile_value = dict(request_profile or _load(REQUEST_PROFILE_PATH))
        artifact_value = dict(artifact_evidence or _load(ARTIFACT_PATH))
        artifact_revision = admit_model_artifact_revision_evidence(artifact_value)
        artifact_hash = model_artifact_revision_evidence_digest(artifact_value)
        normalized_control = validate_sync_capacity_control_entry(
            design=control_design_value,
            capacity_receipt=capacity_receipt_value,
            artifact_evidence_hash=artifact_hash,
        )
        evaluate_sync_capacity_receipt(
            capacity_receipt_value, design=capacity_design_value
        )
        capacity_source = capacity_receipt_value["source_binding"]
        if (
            semantic_sha256_hash_ref(cases_value) != capacity_source["case_set_hash"]
            or semantic_sha256_hash_ref(signal_value)
            != capacity_source["signal_design_hash"]
            or semantic_sha256_hash_ref(request_profile_value)
            != capacity_source["request_profile_hash"]
        ):
            raise ValueError("capacity control source drift")

        binding = _provider_binding(capacity_design_value, capacity_receipt_value)
        _bind_provider(effective_env, binding, artifact_revision)
        config = remote_provider.build_remote_generation_execution_config(effective_env)
        host = urlparse(config.url).hostname
        if not host:
            raise ValueError("generation provider host is missing")
        ports = capacity_design_value["capacity_experiment"][
            "co_resident_provider_ports"
        ]
        probe = port_probe or _probe_ports
        reachability = dict(probe(host, ports))
        if set(reachability) != {str(port) for port in ports} or any(
            value is not True for value in reachability.values()
        ):
            raise ValueError("co-resident provider reachability is incomplete")

        protected_cases = _capacity_cases(cases_value)
        reservation = {
            "receipt_schema_version": (
                "cx_answer_support_sync_capacity_control_reservation.v1"
            ),
            "status": "RUNNING",
            "control_design_hash": normalized_control["design_hash"],
            "operator_approval_hash": semantic_sha256_hash_ref(
                {
                    "operator_id": effective_env[OPERATOR_ENV],
                    "control_design_hash": normalized_control["design_hash"],
                    "dgx_idle_confirmed": True,
                }
            ),
        }
        reservation["receipt_hash"] = semantic_sha256_hash_ref(reservation)
        _write_exclusive_json(target, reservation)

        experiment = normalized_control["control_experiment"]
        guarded_request = _budgeted_requester(
            requester,
            expected_url=config.url,
            counts=provider_counts,
            maximum_requests=experiment["maximum_provider_calls"],
        )
        effective_collector = collector
        if effective_collector is None:
            from nex_cx.retrieval_answer_support_collection import (
                collect_answer_support_calibration,
            )

            effective_collector = collect_answer_support_calibration
        profile = _run_profile(
            concurrency=1,
            cases=protected_cases,
            collector=effective_collector,
            requester=guarded_request,
            environ=effective_env,
            design=signal_value,
            request_profile=request_profile_value,
            artifact_revision=artifact_revision,
            artifact_hash=artifact_hash,
            case_set_hash=capacity_source["case_set_hash"],
        )
        profile["source"] = "SYNCHRONOUS_LIVE_TRAILING_CONTROL"
        receipt = {
            "receipt_schema_version": (
                "cx_answer_support_sync_capacity_control_receipt.v1"
            ),
            "status": "PASS",
            "control_design_hash": normalized_control["design_hash"],
            "capacity_receipt_hash": capacity_receipt_value["receipt_hash"],
            "source_binding": dict(normalized_control["source_binding"]),
            "operator_observation": {
                "dgx_idle_confirmed": True,
                "operator_id_hash": semantic_sha256_hash_ref(
                    {"operator_id": effective_env[OPERATOR_ENV]}
                ),
                "port_reachability": reachability,
            },
            "control_profile": profile,
            "provider_http_requests": provider_counts["total"],
            "database_calls": 0,
            "holdout_accessed": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
        manifest = evaluate_sync_capacity_control_receipt(
            receipt,
            design=normalized_control,
            capacity_receipt=capacity_receipt_value,
        )
        _replace_json(target, receipt)
    except Exception as exc:  # noqa: BLE001 - protected evidence boundary
        result = _failure(
            "c1_control_observation_failed",
            detail={"exception": exc.__class__.__name__},
        )
        result["provider_http_requests"] = provider_counts["total"]
        _assert_redacted(result, effective_env, cases=protected_cases)
        return result

    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-W-A",
        "status": "PASS",
        "observation": manifest["observation"],
        "control_design_hash": normalized_control["design_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "trailing_control_profile": manifest["trailing_control_profile"],
        "p95_ratio_trailing_to_original_c1": manifest[
            "p95_ratio_trailing_to_original_c1"
        ],
        "p95_ratio_trailing_to_c2": manifest["p95_ratio_trailing_to_c2"],
        "p95_ratio_trailing_to_c4": manifest["p95_ratio_trailing_to_c4"],
        "background_slo_met": manifest["background_slo_met"],
        "timeout_bound_met": manifest["timeout_bound_met"],
        "provider_http_requests": provider_counts["total"],
        "database_calls": 0,
        "holdout_accessed": False,
        "causal_concurrency_attribution_permitted": False,
        "execution_mode_selected": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": manifest["next_boundary"],
    }
    _assert_redacted(result, effective_env, cases=protected_cases)
    return result


def _provider_binding(
    capacity_design: Mapping[str, Any], capacity_receipt: Mapping[str, Any]
) -> Mapping[str, Any]:
    source = _mapping(capacity_design.get("source_binding"), "capacity source")
    receipt_source = _mapping(
        capacity_receipt.get("source_binding"), "capacity receipt source"
    )
    if source != receipt_source:
        raise ValueError("capacity receipt source binding differs from design")
    readiness = _load(
        ROOT / "reports/live/gb2_ca00_s20qpr_runtime_activation_readiness.json"
    )
    manifest = _mapping(readiness.get("manifest"), "readiness manifest")
    profile = _mapping(manifest.get("candidate_profile"), "candidate profile")
    binding = _mapping(profile.get("provider_binding"), "provider binding")
    if semantic_sha256_hash_ref(dict(binding)) != source["provider_binding_hash"]:
        raise ValueError("provider binding hash differs from capacity design")
    return binding


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-W-A",
        "status": "FAIL",
        "failure_code": code,
        "database_calls": 0,
        "holdout_accessed": False,
        "execution_mode_selected": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        profile = result.get("trailing_control_profile")
        row = profile if isinstance(profile, Mapping) else {}
        return (
            "gb2_s20qpwa_c1_control=pass "
            f"p95_ms={row.get('p95_latency_ms')} "
            f"throughput_rps={row.get('throughput_rps')} "
            f"observation={result.get('observation')} "
            "mode_selected=false"
        )
    if status == "skipped":
        return "gb2_s20qpwa_c1_control=skipped"
    return (
        "gb2_s20qpwa_c1_control=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpwa_c1_control()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
