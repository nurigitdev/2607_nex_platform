#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
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

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_runtime import (
    validate_answer_support_shadow_configuration,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    ACCEPTED_DECISION,
    BoundedSynchronousGenerationClient,
    SynchronousRuntimeAcceptanceError,
    build_bounded_synchronous_answer_support_runtime,
    evaluate_synchronous_runtime_e2e_receipt,
    validate_synchronous_runtime_e2e_design,
    validate_synchronous_runtime_policy,
)
from nex_mo import remote_provider
from nex_runtime.model_artifact_revision import (
    admit_model_artifact_revision_evidence,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpw_sync_capacity import (
    _bind_provider,
    _budgeted_requester,
    _capacity_cases,
    _configuration_issues,
    _probe_ports,
)
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpy_sync_runtime_e2e.v1"
SMOKE_ENV = "NEX_GB2_S20QPY_SYNC_RUNTIME_E2E"
APPROVED_ENV = "NEX_GB2_S20QPY_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPY_OPERATOR_ID"
RECEIPT_ENV = "NEX_GB2_S20QPY_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_sync_runtime_e2e_v1_design.json"
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
POLICY_DECISION_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpx_interactive_slo_policy_decision.json"
)
POLICY_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpx_interactive_slo_decision_receipt.json"
)
DEFAULT_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpy_sync_runtime_e2e_receipt.json"
)
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpy_sync_runtime_e2e.json"

HttpRequester = Callable[..., Any]
PortProbe = Callable[[str, Sequence[int]], Mapping[str, bool]]


class _RecordingSink:
    def __init__(self) -> None:
        self._lock = Lock()
        self.events: list[dict[str, Any]] = []

    def record(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            self.events.append(dict(value))


class _LiveGenerationClient:
    def __init__(self, environ: Mapping[str, str], requester: HttpRequester) -> None:
        self.environ = dict(environ)
        self.requester = requester

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return remote_provider.execute_remote_generation_request(
            payload,
            request_id=request_id,
            trace_id=trace_id,
            environ=self.environ,
            requester=self.requester,
        )


def run_gb2_s20qpy_sync_runtime_e2e(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    port_probe: PortProbe | None = None,
    design: Mapping[str, Any] | None = None,
    cases_document: Mapping[str, Any] | None = None,
    signal_design: Mapping[str, Any] | None = None,
    request_profile: Mapping[str, Any] | None = None,
    readiness_report: Mapping[str, Any] | None = None,
    artifact_evidence: Mapping[str, Any] | None = None,
    policy_decision: Mapping[str, Any] | None = None,
    policy_receipt: Mapping[str, Any] | None = None,
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
        return _failure("runtime_e2e_acceptance_already_consumed")

    provider_counts = {"total": 0}
    protected_cases: list[Mapping[str, Any]] = []
    try:
        design_value = dict(design or _load(DESIGN_PATH))
        normalized_design = validate_synchronous_runtime_e2e_design(design_value)
        cases_value = dict(cases_document or _load(CASES_PATH))
        signal_value = dict(signal_design or _load(SIGNAL_DESIGN_PATH))
        request_profile_value = dict(request_profile or _load(REQUEST_PROFILE_PATH))
        readiness_value = dict(readiness_report or _load(READINESS_PATH))
        artifact_value = dict(artifact_evidence or _load(ARTIFACT_PATH))
        policy_value = dict(policy_decision or _load(POLICY_DECISION_PATH))
        policy_receipt_value = dict(policy_receipt or _load(POLICY_RECEIPT_PATH))
        manifest = _mapping(readiness_value.get("manifest"), "readiness manifest")
        configuration = validate_answer_support_shadow_configuration(
            manifest,
            signal_design=signal_value,
            request_profile=request_profile_value,
        )
        policy = validate_synchronous_runtime_policy(
            _mapping(policy_value.get("selected_policy"), "selected policy")
        )
        artifact_revision = admit_model_artifact_revision_evidence(artifact_value)
        _validate_sources(
            normalized_design,
            cases_document=cases_value,
            signal_design=signal_value,
            request_profile=request_profile_value,
            readiness_manifest=manifest,
            artifact_evidence=artifact_value,
            policy_decision=policy_value,
            policy_receipt=policy_receipt_value,
            selected_policy=policy,
            provider_binding=configuration["candidate_profile"]["provider_binding"],
        )
        _bind_provider(
            effective_env,
            configuration["candidate_profile"]["provider_binding"],
            artifact_revision,
        )
        config = remote_provider.build_remote_generation_execution_config(effective_env)
        host = urlparse(config.url).hostname
        port = urlparse(config.url).port
        if not host or not port:
            raise ValueError("generation provider route is incomplete")
        reachability = dict((port_probe or _probe_ports)(host, [port]))
        if reachability != {str(port): True}:
            raise ValueError("generation provider is unreachable")
        protected_cases = _capacity_cases(cases_value)
        reservation = {
            "receipt_schema_version": "cx_answer_support_sync_runtime_e2e_reservation.v1",
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
        guarded_request = _budgeted_requester(
            requester,
            expected_url=config.url,
            counts=provider_counts,
            maximum_requests=normalized_design["acceptance_policy"]["sample_count"],
        )
        progress_sink = _RecordingSink()
        outcome_sink = _RecordingSink()
        runtime = build_bounded_synchronous_answer_support_runtime(
            policy=policy,
            readiness_manifest=manifest,
            signal_design=signal_value,
            request_profile=request_profile_value,
            generation_client=_LiveGenerationClient(effective_env, guarded_request),
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
        )
        started = monotonic()
        observations = _run_acceptance_waves(
            runtime,
            protected_cases,
            maximum_concurrency=normalized_design["acceptance_policy"][
                "maximum_concurrency"
            ],
        )
        elapsed_seconds = max(monotonic() - started, 0.000001)
        gateway = runtime.generation_client.snapshot()
        overload_retryable = _overload_probe()
        e2e_latencies = [row["e2e_latency_ms"] for row in observations]
        receipt = {
            "receipt_schema_version": "cx_answer_support_sync_runtime_e2e_receipt.v1",
            "status": "PASS",
            "design_hash": normalized_design["design_hash"],
            "selected_policy_hash": policy["policy_hash"],
            "source_binding": dict(normalized_design["source_binding"]),
            "execution": {
                "sample_count": len(observations),
                "accepted_count": gateway["admitted_count"],
                "provider_call_count": provider_counts["total"],
                "provider_error_count": sum(
                    row["status"] != "OBSERVED" for row in observations
                ),
                "rejected_count": gateway["rejected_count"],
                "maximum_in_flight": gateway["maximum_in_flight"],
                "peak_in_flight": gateway["peak_in_flight"],
                "progress_failure_count": gateway["progress_failure_count"],
                "overload_probe_retryable": overload_retryable,
                "progress_event_count": len(progress_sink.events),
                "outcome_count": len(outcome_sink.events),
            },
            "metrics": {
                "feedback_sample_count": len(gateway["feedback_latencies_ms"]),
                "feedback_p95_latency_ms": _p95(gateway["feedback_latencies_ms"]),
                "feedback_maximum_latency_ms": max(
                    gateway["feedback_latencies_ms"], default=0.0
                ),
                "provider_sample_count": len(gateway["provider_latencies_ms"]),
                "provider_p95_latency_ms": _p95(gateway["provider_latencies_ms"]),
                "provider_maximum_latency_ms": max(
                    gateway["provider_latencies_ms"], default=0.0
                ),
                "e2e_sample_count": len(e2e_latencies),
                "e2e_p95_latency_ms": _p95(e2e_latencies),
                "e2e_maximum_latency_ms": max(e2e_latencies, default=0.0),
                "elapsed_seconds": round(elapsed_seconds, 6),
                "throughput_rps": round(len(observations) / elapsed_seconds, 9),
                "total_tokens": sum(row["total_tokens"] for row in observations),
            },
            "database_calls": 0,
            "holdout_accessed": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
        acceptance = evaluate_synchronous_runtime_e2e_receipt(
            receipt,
            design=normalized_design,
            decision_receipt=policy_receipt_value,
        )
        _replace_json(target, receipt)
    except Exception as exc:  # noqa: BLE001 - protected live boundary
        result = _failure(
            "sync_runtime_e2e_acceptance_failed",
            detail={"exception": exc.__class__.__name__},
        )
        result["provider_http_requests"] = provider_counts["total"]
        _assert_redacted(result, effective_env, protected_cases)
        return result

    accepted = acceptance["decision"] == ACCEPTED_DECISION
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-Y",
        "status": "PASS" if accepted else "FAIL",
        "decision": acceptance["decision"],
        "design_hash": normalized_design["design_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "manifest_hash": acceptance["manifest_hash"],
        "selected_policy_hash": policy["policy_hash"],
        "checks": acceptance["checks"],
        "failed_checks": acceptance["failed_checks"],
        "execution": acceptance["execution"],
        "metrics": acceptance["metrics"],
        "provider_http_requests": provider_counts["total"],
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": acceptance["next_boundary"],
    }
    _assert_redacted(result, effective_env, protected_cases)
    return result


def _run_acceptance_waves(
    runtime: Any,
    cases: Sequence[Mapping[str, Any]],
    *,
    maximum_concurrency: int,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for start in range(0, len(cases), maximum_concurrency):
        batch = cases[start : start + maximum_concurrency]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = [executor.submit(_observe_case, runtime, case) for case in batch]
            observations.extend(future.result() for future in futures)
    return observations


def _observe_case(runtime: Any, case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case["case_id"])
    package_id = f"s20qpy-{case_id}"
    started = monotonic()
    outcome = runtime.observe(
        query_text=str(case["query"]),
        evidence_items=[
            {
                "evidence_id": str(row["candidate_id"]),
                "text": str(row["text"]),
                "permission_result": {"visible": True},
            }
            for row in case["candidates"]
        ],
        primary_package={
            "retrieval_package_id": package_id,
            "status": "READY",
            "purpose": "grounded_answer",
        },
        access_context=CxAccessContext(
            caller_service_id="nex-ae-api",
            tenant_id="VO00",
            subject_id="s20qpy-operator",
            request_id=f"request-{case_id}",
            trace_id=hashlib.sha256(case_id.encode()).hexdigest()[:32],
            scopes=("service:call",),
        ),
    )
    usage = outcome.get("usage")
    tokens = usage.get("total_tokens", 0) if isinstance(usage, Mapping) else 0
    return {
        "status": outcome.get("status"),
        "e2e_latency_ms": round((monotonic() - started) * 1_000.0, 6),
        "total_tokens": tokens if isinstance(tokens, int) else 0,
    }


def _overload_probe() -> bool:
    entered = Event()
    release = Event()

    class BlockingClient:
        def create_generation(self, payload: dict[str, Any], **kwargs: Any) -> dict:
            del payload, kwargs
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("overload probe release timed out")
            return {}

    sink = _RecordingSink()
    gateway = BoundedSynchronousGenerationClient(
        BlockingClient(), progress_sink=sink, maximum_in_flight=1
    )
    gateway.begin_request("probe-one")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            gateway.create_generation,
            {},
            request_id="probe-one",
            trace_id="1" * 32,
        )
        if not entered.wait(timeout=1):
            release.set()
            future.result()
            return False
        gateway.begin_request("probe-two")
        try:
            gateway.create_generation({}, request_id="probe-two", trace_id="2" * 32)
        except SynchronousRuntimeAcceptanceError as exc:
            retryable = exc.retryable
        else:
            retryable = False
        finally:
            release.set()
        future.result()
    return retryable


def _validate_sources(
    design: Mapping[str, Any],
    *,
    cases_document: Mapping[str, Any],
    signal_design: Mapping[str, Any],
    request_profile: Mapping[str, Any],
    readiness_manifest: Mapping[str, Any],
    artifact_evidence: Mapping[str, Any],
    policy_decision: Mapping[str, Any],
    policy_receipt: Mapping[str, Any],
    selected_policy: Mapping[str, Any],
    provider_binding: Mapping[str, Any],
) -> None:
    source = design["source_binding"]
    checks = {
        "case_set_hash": semantic_sha256_hash_ref(dict(cases_document)),
        "signal_design_hash": semantic_sha256_hash_ref(dict(signal_design)),
        "request_profile_hash": semantic_sha256_hash_ref(dict(request_profile)),
        "readiness_manifest_hash": readiness_manifest.get("manifest_hash"),
        "runtime_profile_hash": _mapping(
            readiness_manifest.get("candidate_profile"), "runtime profile"
        ).get("profile_hash"),
        "artifact_evidence_hash": semantic_sha256_hash_ref(dict(artifact_evidence)),
        "interactive_slo_design_hash": policy_decision.get("design_hash"),
        "interactive_slo_manifest_hash": policy_decision.get("manifest_hash"),
        "interactive_slo_decision_receipt_hash": policy_receipt.get("receipt_hash"),
        "interactive_slo_decision_receipt_document_hash": (
            semantic_sha256_hash_ref(dict(policy_receipt))
        ),
        "selected_policy_hash": selected_policy.get("policy_hash"),
        "provider_binding_hash": semantic_sha256_hash_ref(dict(provider_binding)),
    }
    if checks != source:
        raise ValueError("synchronous runtime source binding drifted")


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-Y",
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _assert_redacted(
    result: Mapping[str, Any],
    environ: Mapping[str, str],
    cases: Sequence[Mapping[str, Any]],
) -> None:
    serialized = json.dumps(result, ensure_ascii=False)
    secrets = [environ.get("NEX_MO_VLLM_API_KEY")]
    private_texts = [
        str(candidate["text"])
        for case in cases
        for candidate in case.get("candidates", [])
        if isinstance(candidate, Mapping)
    ]
    if any(value and value in serialized for value in [*secrets, *private_texts]):
        raise ValueError("protected result leaked private or secret material")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        metrics = _mapping(result.get("metrics"), "metrics")
        return (
            "gb2_s20qpy_sync_runtime_e2e=pass "
            f"feedback_p95_ms={metrics.get('feedback_p95_latency_ms')} "
            f"provider_p95_ms={metrics.get('provider_p95_latency_ms')} "
            f"e2e_p95_ms={metrics.get('e2e_p95_latency_ms')} "
            "activation=pending_operator_decision"
        )
    if status == "skipped":
        return "gb2_s20qpy_sync_runtime_e2e=skipped"
    return (
        "gb2_s20qpy_sync_runtime_e2e=fail "
        f"reason={result.get('failure_code', result.get('decision', 'checks_failed'))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpy_sync_runtime_e2e()
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
