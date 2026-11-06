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
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_s20qpa_vector_near_tie_ordering as s136_replay
import run_platform_grounded_generation_artifact_live_postgres_smoke as s137_replay
from nex_cx.retrieval_deferred_live_runner_reconciliation import (
    build_deferred_live_runner_reconciliation_contract,
    evaluate_deferred_live_runner_replay,
)

SCHEMA_VERSION = "gb2_s20ra_deferred_live_runner_runtime_reconciliation.v1"
SMOKE_ENV = "NEX_GB2_S20RA_DEFERRED_LIVE_RUNNER_RECONCILIATION"
PROFILE_ENV = "NEX_GB2_S20RA_PROFILE"
LIVE_ENV = "NEX_GB2_S20RA_EXECUTE_LIVE"
S136_EVIDENCE_PATH_ENV = "NEX_GB2_S20RA_S136_EVIDENCE_PATH"
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_deferred_live_runner_reconciliation_v1_design.json"
)
S20Q_CLOSURE_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20q_multi_signal_live_holdout_acceptance_closure.json"
)
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

ReplayRunner = Callable[[Mapping[str, str]], dict[str, Any]]


def run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
    environ: Mapping[str, str] | None = None,
    *,
    s136_runner: ReplayRunner | None = None,
    s137_runner: ReplayRunner | None = None,
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
    s136_result: dict[str, Any] | None = None
    s137_result: dict[str, Any] | None = None
    try:
        design = _load_json(DESIGN_PATH)
        closure = _load_json(S20Q_CLOSURE_PATH)
        contract = build_deferred_live_runner_reconciliation_contract(
            design=design,
            s20q_closure=closure,
            s20q_closure_document_hash=f"sha256:{_sha256_file(S20Q_CLOSURE_PATH)}",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _failure("source_contract_invalid", exc.__class__.__name__)

    if env.get(LIVE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "READY",
            "decision": "LIVE_REPLAY_NOT_REQUESTED",
            "contract_hash": contract["contract_hash"],
            "selected_policy_hash": contract["selected_policy_hash"],
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
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": provider["embedding"][
            "revision"
        ],
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": provider["embedding"]["model"],
        "NEX_MO_REMOTE_RERANKER_MODEL": provider["reranking"]["model"],
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": provider["reranking"][
            "revision"
        ],
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": provider["reranking"]["model"],
        "NEX_MO_VLLM_MODEL": provider["generation"]["model"],
        "NEX_MO_VLLM_MODEL_REVISION": provider["generation"]["revision"],
        "NEX_MO_VLLM_DEPLOYMENT_ID": provider["generation"]["deployment_id"],
        "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": provider["generation"]["model"],
        "NEX_CX_ANSWER_SUPPORT_POLICY_MODE": "CONTROLLED",
        "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_MODE": "CONTROLLED",
    }
    run_s136 = s136_runner or (
        lambda runtime_env: s136_replay.run_gb2_s20qpa_vector_near_tie_ordering(
            runtime_env
        )
    )
    run_s137 = s137_runner or (
        s137_replay.run_platform_grounded_generation_artifact_live_postgres_smoke
    )
    try:
        s136_evidence_path = str(env.get(S136_EVIDENCE_PATH_ENV, "")).strip()
        if s136_evidence_path:
            s136_result = _load_replay_evidence(Path(s136_evidence_path))
        else:
            s136_result = run_s136(
                {
                    **effective_env,
                    s136_replay.SMOKE_ENV: "1",
                    s136_replay.PROFILE_ENV: "test",
                }
            )
        if s136_result.get("status") != "PASS":
            result = _failure("s136_current_replay_failed")
            result["source_status"] = _source_status(s136_result)
            _assert_redacted(result, effective_env)
            return result
        s137_result = run_s137(
            {
                **effective_env,
                s137_replay.SMOKE_ENV: "1",
                s137_replay.PROFILE_ENV: "test",
            }
        )
        if s137_result.get("status") != "PASS":
            result = _failure("s137_current_replay_failed")
            result["source_status"] = _source_status(s137_result)
            _assert_redacted(result, effective_env)
            return result
        evidence = evaluate_deferred_live_runner_replay(
            contract=contract,
            s136_replay=s136_result,
            s137_replay=s137_result,
        )
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            **evidence,
            "source_status": {
                "s136": _source_status(s136_result),
                "s137": _source_status(s137_result),
            },
        }
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        safe_detail = getattr(exc, "error_code", None) or exc.__class__.__name__
        result = _failure("live_replay_execution_failed", safe_detail)
        contract_detail = getattr(exc, "detail", None)
        if isinstance(contract_detail, str):
            result["contract_error_detail"] = contract_detail
        result["source_status"] = {
            "s136": _source_status(s136_result or {}),
            "s137": _source_status(s137_result or {}),
        }
    _assert_redacted(result, effective_env)
    return result


def _source_status(value: Mapping[str, Any]) -> dict[str, Any]:
    failed_checks = [
        str(item)
        for item in value.get("failed_checks") or []
        if isinstance(item, str)
    ]
    return {
        "status": value.get("status"),
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "failure_code": value.get("failure_code"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _load_replay_evidence(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    live_root = (ROOT / "reports" / "live").resolve()
    if not resolved.is_relative_to(live_root):
        raise ValueError("S136 replay evidence must be under reports/live")
    return _load_json(resolved)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure(code: str, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
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


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20ra_deferred_live_runner_reconciliation=pass "
            f"checks={len(result.get('checks') or {})} "
            "s136=current s137=canonical qwen35=9b holdout=sealed"
        )
    if status == "ready":
        return "gb2_s20ra_deferred_live_runner_reconciliation=ready live=not_requested"
    if status == "skipped":
        return "gb2_s20ra_deferred_live_runner_reconciliation=skipped"
    return (
        "gb2_s20ra_deferred_live_runner_reconciliation=fail "
        f"code={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20ra_deferred_live_runner_runtime_reconciliation()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "READY", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
