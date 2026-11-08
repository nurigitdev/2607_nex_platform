#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import monotonic
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

from nex_cx.retrieval_answer_support_collection import (
    collect_answer_support_calibration,
    validate_answer_support_calibration_collection,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    validate_answer_support_shadow_configuration,
)
from nex_cx.retrieval_answer_support_sync_capacity import (
    evaluate_sync_capacity_receipt,
    validate_sync_capacity_entry,
)
from nex_mo import remote_provider
from nex_runtime.model_artifact_revision import (
    admit_model_artifact_revision_evidence,
    model_artifact_revision_evidence_digest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpw_sync_capacity.v1"
SMOKE_ENV = "NEX_GB2_S20QPW_SYNC_CAPACITY"
APPROVED_ENV = "NEX_GB2_S20QPW_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPW_OPERATOR_ID"
RECEIPT_ENV = "NEX_GB2_S20QPW_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_sync_capacity_v1_design.json"
)
CASES_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
)
SIGNAL_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_generation_profile_v1.json"
)
READINESS_PATH = ROOT / "reports/live/gb2_ca00_s20qpr_runtime_activation_readiness.json"
ARTIFACT_PATH = ROOT / "reports/live/gb2_s20qpi_qwen3_5_9b_revision.json"
BASELINE_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpv_extended_shadow_receipt.json"
)
SLO_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpv_latency_slo_receipt.json"
DEFAULT_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpw_sync_capacity_receipt.json"
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpw_sync_capacity.json"

PROTECTED_ENV_KEYS = (
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

Collector = Callable[..., dict[str, Any]]
HttpRequester = Callable[..., Any]
PortProbe = Callable[[str, Sequence[int]], Mapping[str, bool]]


def run_gb2_s20qpw_sync_capacity(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    collector: Collector = collect_answer_support_calibration,
    port_probe: PortProbe | None = None,
    design: Mapping[str, Any] | None = None,
    cases_document: Mapping[str, Any] | None = None,
    signal_design: Mapping[str, Any] | None = None,
    request_profile: Mapping[str, Any] | None = None,
    readiness_report: Mapping[str, Any] | None = None,
    artifact_evidence: Mapping[str, Any] | None = None,
    baseline_receipt: Mapping[str, Any] | None = None,
    latency_slo_receipt: Mapping[str, Any] | None = None,
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
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)
    target = receipt_path or Path(
        effective_env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH))
    )
    if target.exists():
        return _failure("capacity_observation_already_consumed")

    provider_counts = {"total": 0}
    protected_cases: list[Mapping[str, Any]] = []
    try:
        design_value = dict(design or _load(DESIGN_PATH))
        cases_value = dict(cases_document or _load(CASES_PATH))
        signal_value = dict(signal_design or _load(SIGNAL_DESIGN_PATH))
        request_profile_value = dict(request_profile or _load(REQUEST_PROFILE_PATH))
        readiness_value = dict(readiness_report or _load(READINESS_PATH))
        artifact_value = dict(artifact_evidence or _load(ARTIFACT_PATH))
        baseline_value = dict(baseline_receipt or _load(BASELINE_RECEIPT_PATH))
        slo_value = dict(latency_slo_receipt or _load(SLO_RECEIPT_PATH))
        artifact_revision = admit_model_artifact_revision_evidence(artifact_value)
        artifact_hash = model_artifact_revision_evidence_digest(artifact_value)
        normalized_design = validate_sync_capacity_entry(
            design=design_value,
            cases_document=cases_value,
            signal_design=signal_value,
            request_profile=request_profile_value,
            baseline_receipt=baseline_value,
            latency_slo_receipt=slo_value,
            artifact_evidence_hash=artifact_hash,
        )
        manifest = _mapping(readiness_value.get("manifest"), "readiness manifest")
        configuration = validate_answer_support_shadow_configuration(
            manifest,
            signal_design=signal_value,
            request_profile=request_profile_value,
        )
        binding = configuration["candidate_profile"]["provider_binding"]
        _bind_provider(effective_env, binding, artifact_revision)
        execution = normalized_design["capacity_experiment"]
        config = remote_provider.build_remote_generation_execution_config(effective_env)
        host = urlparse(config.url).hostname
        if not host:
            raise ValueError("generation provider host is missing")
        probe = port_probe or _probe_ports
        reachability = dict(probe(host, execution["co_resident_provider_ports"]))
        if set(reachability) != {
            str(port) for port in execution["co_resident_provider_ports"]
        } or any(value is not True for value in reachability.values()):
            raise ValueError("co-resident provider reachability is incomplete")
        protected_cases = _capacity_cases(cases_value)
        reservation = {
            "receipt_schema_version": "cx_answer_support_sync_capacity_reservation.v1",
            "status": "RUNNING",
            "design_hash": normalized_design["design_hash"],
            "operator_approval_hash": semantic_sha256_hash_ref(
                {
                    "operator_id": effective_env[OPERATOR_ENV],
                    "design_hash": normalized_design["design_hash"],
                }
            ),
        }
        reservation["receipt_hash"] = semantic_sha256_hash_ref(reservation)
        _write_exclusive_json(target, reservation)
        profiles = [_baseline_profile(baseline_value)]
        maximum_requests = execution["maximum_additional_provider_calls"]
        guarded_request = _budgeted_requester(
            requester,
            expected_url=config.url,
            counts=provider_counts,
            maximum_requests=maximum_requests,
        )

        for concurrency in execution["live_profiles_to_execute"]:
            profiles.append(
                _run_profile(
                    concurrency=concurrency,
                    cases=protected_cases,
                    collector=collector,
                    requester=guarded_request,
                    environ=effective_env,
                    design=signal_value,
                    request_profile=request_profile_value,
                    artifact_revision=artifact_revision,
                    artifact_hash=artifact_hash,
                    case_set_hash=normalized_design["source_binding"]["case_set_hash"],
                )
            )
        receipt = {
            "receipt_schema_version": "cx_answer_support_sync_capacity_receipt.v1",
            "status": "PASS",
            "design_hash": normalized_design["design_hash"],
            "source_binding": dict(normalized_design["source_binding"]),
            "environment_observation": {
                "evidence_level": execution["co_resident_evidence_level"],
                "operator_declared_vllm_max_num_seqs": execution[
                    "operator_declared_vllm_max_num_seqs"
                ],
                "port_reachability": reachability,
            },
            "profiles": profiles,
            "provider_http_requests": provider_counts["total"],
            "database_calls": 0,
            "holdout_accessed": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
        manifest_result = evaluate_sync_capacity_receipt(
            receipt, design=normalized_design
        )
        _replace_json(target, receipt)
    except Exception as exc:  # noqa: BLE001 - protected boundary consumes failure
        result = _failure(
            "sync_capacity_observation_failed",
            detail={"exception": exc.__class__.__name__},
        )
        result["provider_http_requests"] = provider_counts["total"]
        _assert_redacted(result, effective_env, cases=protected_cases)
        return result

    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-W",
        "status": "PASS",
        "decision": manifest_result["decision"],
        "design_hash": normalized_design["design_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "manifest_hash": manifest_result["manifest_hash"],
        "profile_assessments": manifest_result["profile_assessments"],
        "throughput_gain_vs_concurrency_1": manifest_result[
            "throughput_gain_vs_concurrency_1"
        ],
        "recommended_synchronous_concurrency": manifest_result[
            "recommended_synchronous_concurrency"
        ],
        "co_resident_evidence_level": manifest_result["co_resident_evidence_level"],
        "all_bound_endpoints_reachable": manifest_result[
            "all_bound_endpoints_reachable"
        ],
        "provider_http_requests": provider_counts["total"],
        "database_calls": 0,
        "holdout_accessed": False,
        "execution_mode_selected": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": manifest_result["next_boundary"],
    }
    _assert_redacted(result, effective_env, cases=protected_cases)
    return result


def _run_profile(
    *,
    concurrency: int,
    cases: Sequence[Mapping[str, Any]],
    collector: Collector,
    requester: HttpRequester,
    environ: Mapping[str, str],
    design: Mapping[str, Any],
    request_profile: Mapping[str, Any],
    artifact_revision: str,
    artifact_hash: str,
    case_set_hash: str,
) -> dict[str, Any]:
    latencies: list[float] = []
    total_tokens = 0
    metrics_lock = Lock()

    def evaluate(
        payload: Mapping[str, Any], request_id: str, trace_id: str
    ) -> Mapping[str, Any]:
        nonlocal total_tokens
        started = monotonic()
        result = remote_provider.execute_remote_generation_request(
            dict(payload),
            request_id=request_id,
            trace_id=trace_id,
            environ=dict(environ),
            requester=requester,
        )
        elapsed_ms = round((monotonic() - started) * 1_000.0, 6)
        usage = result.get("usage")
        tokens = usage.get("total_tokens", 0) if isinstance(usage, Mapping) else 0
        with metrics_lock:
            latencies.append(elapsed_ms)
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
                total_tokens += tokens
        return result

    started = monotonic()
    collection = collector(
        cases,
        dataset_id="s136-sync-capacity-public-synthetic-v1",
        dataset_sha256=case_set_hash,
        design=design,
        profile=request_profile,
        artifact_revision=artifact_revision,
        artifact_evidence_hash=artifact_hash,
        source_retrieval_evidence_hash=case_set_hash,
        evaluator=evaluate,
        maximum_concurrency=concurrency,
        request_namespace=f"s20qpw-c{concurrency}",
    )
    validate_answer_support_calibration_collection(collection)
    elapsed_seconds = max(monotonic() - started, 0.000001)
    if len(latencies) != len(cases):
        raise ValueError("capacity latency sample count is incomplete")
    ordered = sorted(latencies)
    return {
        "concurrency": concurrency,
        "source": "SYNCHRONOUS_LIVE_REPLAY",
        "request_count": len(cases),
        "provider_request_count": len(cases),
        "error_count": 0,
        "latency_sample_count": len(ordered),
        "p95_latency_ms": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
        "maximum_latency_ms": ordered[-1],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "throughput_rps": round(len(cases) / elapsed_seconds, 9),
        "total_tokens": total_tokens,
    }


def _baseline_profile(receipt: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _mapping(receipt.get("snapshot"), "baseline snapshot")
    started = _parse_time(receipt.get("started_at"))
    completed = _parse_time(receipt.get("completed_at"))
    elapsed_seconds = (completed - started).total_seconds()
    if elapsed_seconds <= 0:
        raise ValueError("baseline elapsed time is invalid")
    return {
        "concurrency": 1,
        "source": "P_V_BASELINE_RECEIPT",
        "request_count": snapshot["provider_calls"],
        "provider_request_count": receipt["provider_http_requests"]["generation"],
        "error_count": snapshot["failed_count"],
        "latency_sample_count": snapshot["latency_sample_count"],
        "p95_latency_ms": snapshot["p95_latency_ms"],
        "maximum_latency_ms": snapshot["maximum_latency_ms"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "throughput_rps": round(snapshot["provider_calls"] / elapsed_seconds, 9),
        "total_tokens": snapshot["total_tokens"],
    }


def _capacity_cases(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = document.get("cases")
    if (
        document.get("case_schema_version")
        != "cx_answer_support_shadow_canary_cases.v1"
        or document.get("status") != "FROZEN_PUBLIC_SYNTHETIC"
        or not isinstance(source, list)
        or len(source) != 30
    ):
        raise ValueError("capacity case set is invalid")
    cases = []
    for row in source:
        case = _mapping(row, "capacity case")
        candidates = case.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("capacity candidates are invalid")
        cases.append(
            {
                "case_id": str(case["case_id"]),
                "partition": "CALIBRATION",
                "query": str(case["query"]),
                "candidates": [
                    {
                        "candidate_id": f"{case['case_id']}-candidate-{index}",
                        "text": str(text),
                    }
                    for index, text in enumerate(candidates, start=1)
                ],
            }
        )
    return cases


def _bind_provider(
    environ: dict[str, str], binding: Mapping[str, Any], artifact_revision: str
) -> None:
    revision = str(binding["model_revision"])
    deployment = str(binding["deployment_id"])
    if artifact_revision != revision:
        raise ValueError("artifact revision differs from readiness binding")
    if environ.get("NEX_MO_VLLM_MODEL_REVISION") not in {None, "", revision}:
        raise ValueError("configured revision differs from readiness binding")
    if environ.get("NEX_MO_VLLM_DEPLOYMENT_ID") not in {None, "", deployment}:
        raise ValueError("configured deployment differs from readiness binding")
    environ["NEX_MO_VLLM_MODEL_REVISION"] = revision
    environ["NEX_MO_VLLM_DEPLOYMENT_ID"] = deployment


def _probe_ports(host: str, ports: Sequence[int]) -> Mapping[str, bool]:
    result = {}
    for port in ports:
        try:
            with socket.create_connection((host, int(port)), timeout=3.0):
                result[str(port)] = True
        except OSError:
            result[str(port)] = False
    return result


def _budgeted_requester(
    requester: HttpRequester | None,
    *,
    expected_url: str,
    counts: dict[str, int],
    maximum_requests: int,
) -> HttpRequester:
    base = requester or remote_provider.httpx.request
    lock = Lock()

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        with lock:
            if url != expected_url:
                raise ValueError("capacity observation used an unbound route")
            if counts["total"] >= maximum_requests:
                raise ValueError("capacity provider request budget exceeded")
            counts["total"] += 1
        return base(method, url, **kwargs)

    return guarded


def _configuration_issues(environ: Mapping[str, str]) -> list[str]:
    issues = []
    if not (
        environ.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
        or environ.get("NEX_MO_VLLM_BASE_URL")
    ):
        issues.append("generation_endpoint")
    for key in ("NEX_MO_VLLM_API_KEY", "NEX_MO_VLLM_MODEL"):
        if not environ.get(key):
            issues.append(key)
    return issues


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("evidence timestamp is invalid")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-W",
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


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    *,
    cases: Sequence[Mapping[str, Any]],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)
    ]
    protected.extend(str(case["query"]) for case in cases)
    protected.extend(
        str(candidate["text"]) for case in cases for candidate in case["candidates"]
    )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q-P-W evidence contains protected data")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        profiles = result.get("profile_assessments")
        rows = profiles if isinstance(profiles, list) else []
        metrics = ",".join(
            f"c{row.get('concurrency')}:{row.get('p95_latency_ms')}ms/{row.get('throughput_rps')}rps"
            for row in rows
            if isinstance(row, Mapping)
        )
        return (
            "gb2_s20qpw_sync_capacity=pass "
            f"profiles={metrics} "
            f"recommended={result.get('recommended_synchronous_concurrency')} "
            "mode_selected=false"
        )
    if status == "skipped":
        return "gb2_s20qpw_sync_capacity=skipped"
    return (
        "gb2_s20qpw_sync_capacity=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpw_sync_capacity()
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
