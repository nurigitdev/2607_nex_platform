from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "_shared"))
sys.path.insert(0, str(ROOT_DIR / "services" / "nex-mo"))

from nex_mo.providers import build_model_profile_catalog
from nex_mo.remote_provider import (
    build_remote_provider_preflight_configs,
    expected_models_from_env,
    run_remote_provider_preflight_check,
)

LIVE_PROVIDER_CHECKS = build_remote_provider_preflight_configs({})
PROTECTED_EVIDENCE_ENV_KEYS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
    "NEX_MO_LIVE_RERANKER_HEALTH_URL",
    "NEX_MO_LIVE_VLLM_MODELS_URL",
)


def run_dgx_live_provider_preflight(
    environ: dict[str, str] | None = None,
    *,
    requester=None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get("NEX_MO_LIVE_PREFLIGHT") != "1":
        return {
            "preflight_schema_version": "dgx_live_provider_preflight.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_MO_LIVE_PREFLIGHT is not enabled.",
            "checks": [],
            "model_profiles": selected_profile_summary(env),
        }

    configs = build_remote_provider_preflight_configs(env)
    checks = [
        run_remote_provider_preflight_check(config, requester=requester)
        if requester is not None
        else run_remote_provider_preflight_check(config)
        for config in configs
    ]
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    return {
        "preflight_schema_version": "dgx_live_provider_preflight.v1",
        "status": status,
        "checks": checks,
        "model_profiles": selected_profile_summary(env),
    }


def selected_profile_summary(env: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "profile_name": profile.profile_name,
            "provider_capability": profile.provider_capability,
            "alias": profile.alias,
            "model_name": profile.model_name,
            "precision": profile.precision,
            "runtime_engine": profile.runtime_engine,
            "selected": profile.selected,
            "status": profile.status,
            "candidate_role": profile.candidate_role,
        }
        for profile in build_model_profile_catalog(env)
        if profile.selected or profile.provider_capability == "generation"
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DGX live provider preflight.")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument(
        "--output",
        "--evidence-output",
        dest="output",
        type=Path,
        help="Optional protected JSON evidence output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_dgx_live_provider_preflight()
    protected_evidence = build_protected_preflight_evidence(evidence)
    if args.output:
        write_protected_preflight_evidence(args.output, protected_evidence)

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(protected_evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def build_protected_preflight_evidence(
    evidence: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    protected_evidence = {
        **evidence,
        "evidence_schema_version": "dgx_live_provider_preflight_evidence.v1",
        "evidence_generated_at": _utc_now(),
        "redaction": {
            "status": "PASS",
            "policy": "provider endpoints and credentials are excluded",
            "checked_env_keys": [
                key for key in PROTECTED_EVIDENCE_ENV_KEYS if env.get(key)
            ],
        },
    }
    serialized = json.dumps(protected_evidence, ensure_ascii=False, sort_keys=True)
    assert_protected_evidence_is_redacted(serialized, env)
    return protected_evidence


def write_protected_preflight_evidence(
    output_path: Path,
    evidence: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_protected_evidence_is_redacted(
        serialized,
        environ if environ is not None else os.environ,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_protected_evidence_is_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_EVIDENCE_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            f"protected evidence contains unredacted environment value: {leaked_keys[0]}"
        )


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return "dgx_live_provider_preflight=skipped reason=NEX_MO_LIVE_PREFLIGHT"
    passed = sum(1 for check in evidence["checks"] if check["status"] == "PASS")
    total = len(evidence["checks"])
    return (
        f"dgx_live_provider_preflight={evidence['status'].lower()} "
        f"checks={passed}/{total}"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
