#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "deployment",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_ca00_s18_installed_current_platform_golden_journey as s149_current
import run_gb2_ca00_s19_fail_closed_restart_acceptance as s150_current
import run_platform_release_candidate_protected_matrix as s140_current
import run_s147_model_rollout_live_acceptance as s147_current
from nex_runtime.calibration_deferred_live_matrix import (
    build_calibration_deferred_live_matrix_contract,
    build_reconciled_release_candidate_provider_source,
    evaluate_calibration_deferred_live_matrix,
)


SCHEMA_VERSION = "gb2_s20r_calibration_closure_deferred_live_matrix.v1"
SMOKE_ENV = "NEX_GB2_S20R_DEFERRED_LIVE_MATRIX"
PROFILE_ENV = "NEX_GB2_S20R_PROFILE"
LIVE_ENV = "NEX_GB2_S20R_EXECUTE_LIVE"
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/gb2_s20r_calibration_closure_deferred_live_matrix_v1_design.json"
)
S20Q_PATH = (
    ROOT / "reports/live/gb2_ca00_s20q_multi_signal_live_holdout_acceptance_closure.json"
)
S20RA_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20ra_deferred_live_runner_runtime_reconciliation.json"
)
DEFAULT_OUTPUT = (
    ROOT / "reports/live/gb2_ca00_s20r_calibration_closure_deferred_live_matrix.json"
)
PROTECTED_ENV_KEYS = (
    *(f"NEX_{service}_TEST_DATABASE_URL" for service in ("OA", "AG", "AE", "CX", "MO", "WC", "EOS")),
    *(f"NEX_{service}_DATABASE_URL" for service in ("OA", "AG", "AE", "CX", "MO", "WC", "EOS")),
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

StageRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]


def run_gb2_s20r_calibration_closure_deferred_live_matrix(
    environ: Mapping[str, str] | None = None,
    *,
    s140_runner: StageRunner | None = None,
    s147_runner: StageRunner | None = None,
    s149_runner: StageRunner | None = None,
    s150_runner: StageRunner | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")
    try:
        contract = build_calibration_deferred_live_matrix_contract(
            design=_load_json(DESIGN_PATH),
            s20q_closure=_load_json(S20Q_PATH),
            s20ra_reconciliation=_load_json(S20RA_PATH),
            s20q_document_hash=f"sha256:{_sha256_file(S20Q_PATH)}",
            s20ra_document_hash=f"sha256:{_sha256_file(S20RA_PATH)}",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure("source_contract_invalid", exc.__class__.__name__)

    if env.get(LIVE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "READY",
            "decision": "DEFERRED_LIVE_MATRIX_NOT_REQUESTED",
            "contract_hash": contract["contract_hash"],
            "provider_binding": contract["provider_binding"],
            "holdout_accessed": False,
            "holdout_reexecuted": False,
        }
    missing = [key for key in PROTECTED_ENV_KEYS if not str(env.get(key, "")).strip()]
    if missing:
        return _failure("protected_configuration_incomplete", missing)

    provider = contract["provider_binding"]
    effective_env = {
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": provider["embedding"]["model"],
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": provider["embedding"]["revision"],
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": provider["embedding"]["model"],
        "NEX_MO_REMOTE_RERANKER_MODEL": provider["reranking"]["model"],
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": provider["reranking"]["revision"],
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": provider["reranking"]["model"],
        "NEX_MO_VLLM_MODEL": provider["generation"]["model"],
        "NEX_MO_VLLM_MODEL_REVISION": provider["generation"]["revision"],
        "NEX_MO_VLLM_DEPLOYMENT_ID": provider["generation"]["deployment_id"],
        "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": provider["generation"]["model"],
        "NEX_MO_GENERATION_REASONING_MODE": "disabled",
        "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "live",
        "NEX_MO_RUNTIME_GENERATION_PORT": "9116",
        "NEX_MO_GENERATION_PROFILE": "qwen3_5_9b_bf16",
        "NEX_MO_GENERATION_MODEL_NAME": provider["generation"]["model"],
        "NEX_MO_GENERATION_MODEL_PRECISION": "BF16",
    }

    runners = {
        "S140": s140_runner or _run_s140,
        "S147": s147_runner or _run_s147,
        "S149": s149_runner or _run_s149,
        "S150": s150_runner or _run_s150,
    }
    results: dict[str, dict[str, Any]] = {}
    try:
        for stage in ("S140", "S147", "S149", "S150"):
            result = dict(runners[stage](effective_env))
            results[stage] = result
            if result.get("status") != "PASS":
                failure = _failure(
                    f"{stage.lower()}_current_replay_failed",
                    {
                        "stage": stage,
                        "source_status": result.get("status"),
                        "source_failure_code": result.get("failure_code"),
                    },
                )
                failure["stage_status"] = _stage_status(results)
                _assert_redacted(failure, effective_env)
                return failure
        evaluated = evaluate_calibration_deferred_live_matrix(
            contract=contract,
            s140=results["S140"],
            s147=results["S147"],
            s149=results["S149"],
            s150=results["S150"],
        )
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            **evaluated,
            "source_status": _stage_status(results),
        }
    except Exception as exc:  # noqa: BLE001 - protected replay fails closed
        safe_detail = getattr(exc, "error_code", None) or exc.__class__.__name__
        evidence = _failure("deferred_live_matrix_execution_failed", safe_detail)
        evidence["stage_status"] = _stage_status(results)
    _assert_redacted(evidence, effective_env)
    return evidence


def _run_s140(env: Mapping[str, str]) -> Mapping[str, Any]:
    s20q_closure = _load_json(S20Q_PATH)
    s20ra_reconciliation = _load_json(S20RA_PATH)
    contract = build_calibration_deferred_live_matrix_contract(
        design=_load_json(DESIGN_PATH),
        s20q_closure=s20q_closure,
        s20ra_reconciliation=s20ra_reconciliation,
        s20q_document_hash=f"sha256:{_sha256_file(S20Q_PATH)}",
        s20ra_document_hash=f"sha256:{_sha256_file(S20RA_PATH)}",
    )
    provider_source = build_reconciled_release_candidate_provider_source(
        contract=contract,
        s20q_closure=s20q_closure,
        s20ra_reconciliation=s20ra_reconciliation,
    )
    stage_env = {
        **env,
        "NEX_S140_RELEASE_CANDIDATE_ACCEPTANCE": "1",
        "NEX_S140_RELEASE_CANDIDATE_PROFILE": "test_live",
        "NEX_S140_BROWSER_VIEWPORTS": "desktop,mobile",
        "NEX_PERSISTENCE_MODE": "postgres",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_AG_OPERATIONS_SOURCE_MODE": "api",
        "NEX_AE_AUTH_SESSION_MODE": "oa",
        "NEX_MO_PROTECTED_LIVE_PROFILE": "dgx_vllm",
    }
    for service in ("OA", "AG", "AE", "CX", "MO"):
        stage_env[f"NEX_{service}_DATABASE_URL"] = env[
            f"NEX_{service}_TEST_DATABASE_URL"
        ]
    return s140_current.run_platform_release_candidate_protected_matrix(
        {**stage_env, s140_current.ENABLE_ENV: "1"},
        provider_runner=lambda _env: provider_source,
    )


def _run_s147(env: Mapping[str, str]) -> Mapping[str, Any]:
    return s147_current.run_s147_model_rollout_live_acceptance(
        {
            **env,
            s147_current.ACTIVATION_ENV: "1",
            s147_current.PROFILE_ENV: "test",
        }
    )


def _run_s149(env: Mapping[str, str]) -> Mapping[str, Any]:
    model_ref = str(
        env.get("NEX_MO_VLLM_MODEL")
        or s149_current.canonical_journey.DEFAULT_MODEL_REF
    ).strip()
    stage_env = {
        **env,
        s149_current.canonical_journey.CALIBRATION_ENV: (
            s149_current.canonical_journey.build_semantic_calibration_json(
                model_ref=model_ref
            )
        ),
    }
    return s149_current.run_installed_current_platform_continuity(
        {**stage_env, s149_current.EXECUTION_ENV: "1"}, execute=True
    )


def _run_s150(env: Mapping[str, str]) -> Mapping[str, Any]:
    return s150_current.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {**env, s150_current.EXECUTION_ENV: "1"}, execute=True
    )


def _stage_status(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        stage: {
            "status": result.get("status"),
            "failure_code": result.get("failure_code"),
        }
        for stage, result in results.items()
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure(code: str, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "holdout_accessed": False,
        "holdout_reexecuted": False,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def _assert_redacted(result: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = str(environ.get(key, "")).strip()
        if value and value in serialized:
            raise AssertionError(f"protected evidence leaked {key}")


def write_evidence(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    path.chmod(0o600)


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        stages = result.get("stage_status") or {}
        return (
            "gb2_s20r_calibration_closure_deferred_live_matrix=pass "
            f"stages={sum(value == 'PASS' or str(value).startswith('PASS_') for value in stages.values())}/6 "
            "holdout=sealed next=full_gate"
        )
    if status == "ready":
        return "gb2_s20r_calibration_closure_deferred_live_matrix=ready live=not_requested"
    if status == "skipped":
        return "gb2_s20r_calibration_closure_deferred_live_matrix=skipped"
    return (
        "gb2_s20r_calibration_closure_deferred_live_matrix=fail "
        f"code={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20r_calibration_closure_deferred_live_matrix()
    if result.get("status") not in {"SKIPPED", "READY"}:
        write_evidence(args.output, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "READY", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
