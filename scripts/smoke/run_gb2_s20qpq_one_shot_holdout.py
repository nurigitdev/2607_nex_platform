#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from check_retrieval_calibration_v4_dataset import (
    DEFAULT_DATASET_PATH,
    check_retrieval_calibration_v4_dataset,
)
from nex_cx.retrieval_answer_support_holdout_execution import (
    build_holdout_receipt_reservation,
    collect_answer_support_holdout,
    complete_holdout_receipt,
    evaluate_answer_support_holdout,
)
from nex_cx.retrieval_answer_support_holdout_freeze import (
    HOLDOUT_RECEIPT_PATH,
    freeze_holdout_one_shot_execution,
)
from nex_mo import remote_provider
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpq_one_shot_holdout.v1"
SMOKE_ENV = "NEX_GB2_S20QPQ_ONE_SHOT_HOLDOUT"
PROFILE_ENV = "NEX_GB2_S20QPQ_PROFILE"
RECEIPT_PATH_ENV = "NEX_GB2_S20QPQ_RECEIPT_PATH"
P_O_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpo_canonical_threshold_admission.json"
)
P_P_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpp_pre_holdout_freeze.json"
)
P_L_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpl_canonical_profile_freeze.json"
)
HOLDOUT_DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_holdout_one_shot_v1_design.json"
)
SIGNAL_DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_generation_profile_v1.json"
)
DEFAULT_RECEIPT_PATH = ROOT / HOLDOUT_RECEIPT_PATH
OUTPUT_PATH = ROOT / "reports" / "live" / "gb2_ca00_s20qpq_one_shot_holdout.json"
MAXIMUM_CONCURRENCY = 4
EXPECTED_PACKAGES = 40
EXPECTED_CANDIDATES = 160
PROTECTED_ENV_KEYS = (
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

Collector = Callable[..., dict[str, Any]]
Evaluator = Callable[..., dict[str, Any]]
Executor = Callable[..., Mapping[str, Any]]
HttpRequester = Callable[..., Any]
Clock = Callable[[], str]
ReceiptWriter = Callable[[Path, Mapping[str, Any]], None]


def run_gb2_s20qpq_one_shot_holdout(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    collector: Collector = collect_answer_support_holdout,
    evaluator: Evaluator = evaluate_answer_support_holdout,
    executor: Executor = remote_provider.execute_remote_generation_request,
    clock: Clock | None = None,
    reservation_writer: ReceiptWriter | None = None,
    terminal_writer: ReceiptWriter | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)
    receipt_path = Path(
        effective_env.get(RECEIPT_PATH_ENV, str(DEFAULT_RECEIPT_PATH))
    )
    if receipt_path.is_file():
        return _failure("one_shot_authorization_already_consumed")
    now = clock or _utc_now
    reserve = reservation_writer or _write_exclusive_json
    finalize = terminal_writer or _replace_json

    try:
        context = _load_execution_context(effective_env)
        freeze = context["freeze"]
        authorization = _mapping(freeze.get("authorization"), "authorization")
        provider_binding = _mapping(
            authorization.get("provider_binding"), "provider binding"
        )
        _bind_effective_provider(effective_env, provider_binding)
        reservation = build_holdout_receipt_reservation(
            freeze, started_at=now()
        )
        reserve(receipt_path, reservation)
    except FileExistsError:
        return _failure("one_shot_authorization_already_consumed")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "pre_execution_admission_failed",
            detail={"exception": exc.__class__.__name__},
        )

    request_counts = {"total": 0, "generation": 0}
    evaluation_count = 0
    evaluation_lock = Lock()
    guarded = _budgeted_requester(
        requester,
        environ=effective_env,
        counts=request_counts,
        maximum_requests=EXPECTED_PACKAGES,
    )
    try:
        def evaluate_provider(
            payload: Mapping[str, Any], request_id: str, trace_id: str
        ) -> Mapping[str, Any]:
            nonlocal evaluation_count
            with evaluation_lock:
                if evaluation_count >= EXPECTED_PACKAGES:
                    raise ValueError("HOLDOUT provider evaluation budget exceeded")
                evaluation_count += 1
            return executor(
                dict(payload),
                request_id=request_id,
                trace_id=trace_id,
                environ=effective_env,
                requester=guarded,
            )

        collection = collector(
            context["holdout_cases"],
            dataset_id=context["dataset_manifest"]["dataset_id"],
            dataset_sha256=(
                "sha256:" + context["dataset_manifest"]["dataset_sha256"]
            ),
            design=context["signal_design"],
            profile=context["request_profile"],
            artifact_revision=provider_binding["model_revision"],
            artifact_evidence_hash=context["artifact_evidence_hash"],
            evaluator=evaluate_provider,
            maximum_concurrency=MAXIMUM_CONCURRENCY,
            request_namespace="s20qpq",
        )
        evaluation = evaluator(
            collection,
            context["holdout_cases"],
            canonical_profile=context["canonical_profile"],
            frozen_candidate=authorization["candidate"],
            admission=freeze["admission"],
        )
        terminal_status = str(evaluation["terminal_status"])
        terminal = complete_holdout_receipt(
            reservation,
            terminal_status=terminal_status,
            completed_at=now(),
            provider_evaluation_count=evaluation_count,
            provider_http_request_count=request_counts["generation"],
            evaluation_hash=str(evaluation["evaluation_hash"]),
        )
        finalize(receipt_path, terminal)
    except Exception as exc:  # noqa: BLE001 - every post-reservation failure consumes the run
        terminal = complete_holdout_receipt(
            reservation,
            terminal_status="INCONCLUSIVE",
            completed_at=now(),
            provider_evaluation_count=evaluation_count,
            provider_http_request_count=request_counts["generation"],
            terminal_reason=exc.__class__.__name__,
        )
        finalize(receipt_path, terminal)
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-Q",
            "status": "FAIL",
            "decision": "HOLDOUT_INCONCLUSIVE_AUTHORIZATION_CONSUMED",
            "execution_id": reservation["execution_id"],
            "receipt": terminal,
            "provider_evaluation_count": evaluation_count,
            "provider_http_request_counts": request_counts,
            "runtime_activation_permitted": False,
        }
        _assert_redacted(result, effective_env, dataset=context["dataset"])
        return result

    dataset = _mapping(collection.get("dataset"), "collection dataset")
    checks = {
        "one_shot_receipt_terminal": terminal["status"] in {"PASS", "FAIL"},
        "execution_id_preserved": terminal["execution_id"] == freeze["execution_id"],
        "holdout_package_count_complete": dataset.get("package_count")
        == EXPECTED_PACKAGES,
        "holdout_candidate_count_complete": dataset.get("candidate_count")
        == EXPECTED_CANDIDATES,
        "provider_evaluations_exact": evaluation_count == EXPECTED_PACKAGES,
        "provider_http_requests_exact": request_counts
        == {"total": EXPECTED_PACKAGES, "generation": EXPECTED_PACKAGES},
        "fixed_threshold_preserved": evaluation.get("threshold_reselected") is False,
        "fixed_profile_preserved": evaluation.get("profile_reselected") is False,
        "runtime_activation_prohibited": evaluation.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-Q",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "HOLDOUT_EXECUTED_CANDIDATE_ADMITTED_SEPARATE_ACTIVATION_REQUIRED"
            if terminal["status"] == "PASS"
            else "HOLDOUT_EXECUTED_CANDIDATE_REJECTED"
        ),
        "execution_id": freeze["execution_id"],
        "authorization_hash": freeze["authorization_hash"],
        "receipt": terminal,
        "provider_evaluation_count": evaluation_count,
        "provider_http_request_counts": request_counts,
        "collection": collection,
        "evaluation": evaluation,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "runtime_activation_permitted": False,
    }
    _assert_redacted(result, effective_env, dataset=context["dataset"])
    return result


def _load_execution_context(environ: Mapping[str, str]) -> dict[str, Any]:
    p_o = _load(P_O_SOURCE_PATH)
    p_p = _load(P_P_SOURCE_PATH)
    p_l = _load(P_L_SOURCE_PATH)
    design = _load(HOLDOUT_DESIGN_PATH)
    dataset = _load(DEFAULT_DATASET_PATH)
    dataset_manifest = check_retrieval_calibration_v4_dataset()
    signal_design = _load(SIGNAL_DESIGN_PATH)
    request_profile = _load(REQUEST_PROFILE_PATH)
    if p_p.get("status") != "PASS" or p_o.get("status") != "PASS":
        raise ValueError("P-O/P-P source evidence is not admitted")
    expected = freeze_holdout_one_shot_execution(
        p_o_calibration=_mapping(p_o.get("calibration"), "P-O calibration"),
        dataset_manifest=dataset_manifest,
        design=design,
        existing_receipt=None,
    )
    freeze = _mapping(p_p.get("freeze"), "P-P freeze")
    if dict(freeze) != expected:
        raise ValueError("P-P freeze binding drifted")
    profile_freeze = _mapping(p_l.get("freeze"), "P-L freeze")
    canonical_profile = _mapping(
        profile_freeze.get("canonical_profile"), "canonical profile"
    )
    candidate = _mapping(
        _mapping(freeze.get("authorization"), "authorization").get("candidate"),
        "frozen candidate",
    )
    if canonical_profile.get("profile_hash") != candidate.get("profile_hash"):
        raise ValueError("canonical profile hash drifted")
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Dataset v4 cases are invalid")
    holdout = sorted(
        (case for case in cases if case.get("partition") == "HOLDOUT"),
        key=lambda row: str(row["case_id"]),
    )
    if len(holdout) != EXPECTED_PACKAGES or sum(
        len(case["candidates"]) for case in holdout
    ) != EXPECTED_CANDIDATES:
        raise ValueError("Dataset v4 HOLDOUT scope drifted")
    source = _mapping(design.get("source_binding"), "HOLDOUT source binding")
    return {
        "freeze": dict(freeze),
        "dataset": dataset,
        "dataset_manifest": dataset_manifest,
        "holdout_cases": holdout,
        "signal_design": signal_design,
        "request_profile": request_profile,
        "canonical_profile": dict(canonical_profile),
        "artifact_evidence_hash": source["artifact_evidence_hash"],
    }


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
    if environ.get("NEX_MO_GENERATION_MAX_ATTEMPTS", "1") != "1":
        issues.append("NEX_MO_GENERATION_MAX_ATTEMPTS")
    return issues


def _bind_effective_provider(
    environ: dict[str, str], binding: Mapping[str, Any]
) -> None:
    revision = _required_text(binding.get("model_revision"), "model_revision")
    deployment = _required_text(binding.get("deployment_id"), "deployment_id")
    configured_revision = environ.get("NEX_MO_VLLM_MODEL_REVISION")
    configured_deployment = environ.get("NEX_MO_VLLM_DEPLOYMENT_ID")
    if configured_revision not in {None, "", "Qwen3.5-4B", revision}:
        raise ValueError("configured generation revision differs from freeze")
    if configured_deployment not in {None, "", "vllm-generation-http", deployment}:
        raise ValueError("configured generation deployment differs from freeze")
    environ["NEX_MO_VLLM_MODEL_REVISION"] = revision
    environ["NEX_MO_VLLM_DEPLOYMENT_ID"] = deployment
    environ["NEX_MO_GENERATION_MAX_ATTEMPTS"] = "1"


def _budgeted_requester(
    requester: HttpRequester | None,
    *,
    environ: Mapping[str, str],
    counts: dict[str, int],
    maximum_requests: int,
) -> HttpRequester:
    base = requester or remote_provider.httpx.request
    config = remote_provider.build_remote_generation_execution_config(dict(environ))
    lock = Lock()

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        with lock:
            if url != config.url:
                raise ValueError("HOLDOUT attempted an unbound provider route")
            if counts["total"] >= maximum_requests:
                raise ValueError("HOLDOUT provider HTTP budget exceeded")
            counts["total"] += 1
            counts["generation"] += 1
        return base(method, url, **kwargs)

    return guarded


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(path.parent)
    except (OSError, TypeError, ValueError):
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    *,
    dataset: Mapping[str, Any] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)
    ]
    if dataset is not None:
        cases = dataset.get("cases")
        if isinstance(cases, list):
            protected.extend(str(case["query"]) for case in cases)
            protected.extend(
                str(candidate["text"])
                for case in cases
                for candidate in case["candidates"]
            )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("P-Q evidence contains protected data")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        evaluation = result.get("evaluation")
        evaluation = evaluation if isinstance(evaluation, Mapping) else {}
        metrics = evaluation.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        return (
            "gb2_s20qpq_one_shot_holdout=pass "
            f"decision={evaluation.get('status')} "
            f"false_ready={metrics.get('false_ready_rate')} "
            f"recall={metrics.get('ready_recall')} "
            f"auc={evaluation.get('package_auc')} "
            f"provider_calls={result.get('provider_evaluation_count')} "
            "authorization=consumed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpq_one_shot_holdout=skipped"
    return (
        "gb2_s20qpq_one_shot_holdout=fail "
        f"reason={result.get('failure_code', result.get('decision', 'checks_failed'))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpq_one_shot_holdout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
