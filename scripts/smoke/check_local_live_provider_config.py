from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "_shared"))
sys.path.insert(0, str(ROOT_DIR / "services" / "nex-mo"))

from nex_mo.providers import build_model_profile_catalog
from nex_mo.remote_provider import (
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_provider_preflight_configs,
    build_remote_reranker_execution_config,
)

PROTECTED_CONFIG_ENV_KEYS = (
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


def build_local_live_provider_config_snapshot(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    provider_mode = env.get("NEX_MO_PROVIDER_MODE", "mock")
    try:
        execution_configs = [
            build_remote_embedding_execution_config(env),
            build_remote_reranker_execution_config(env),
            build_remote_generation_execution_config(env),
        ]
        preflight_configs = list(build_remote_provider_preflight_configs(env))
    except ValueError as exc:
        return _snapshot(
            provider_mode=provider_mode,
            status="FAIL",
            execution_configs=[],
            preflight_configs=[],
            issues=[
                {
                    "capability": "all",
                    "error_code": "live_timeout_invalid",
                    "detail": str(exc),
                }
            ],
            env=env,
        )

    if provider_mode != "live":
        return _snapshot(
            provider_mode=provider_mode,
            status="SKIPPED",
            skip_reason="NEX_MO_PROVIDER_MODE is not live.",
            execution_configs=execution_configs,
            preflight_configs=preflight_configs,
            issues=[],
            env=env,
        )

    issues = [
        *missing_endpoint_issues(execution_configs),
        *missing_endpoint_issues(preflight_configs),
        *expected_model_mismatch_issues(execution_configs, preflight_configs),
    ]
    return _snapshot(
        provider_mode=provider_mode,
        status="PASS" if not issues else "FAIL",
        execution_configs=execution_configs,
        preflight_configs=preflight_configs,
        issues=issues,
        env=env,
    )


def missing_endpoint_issues(configs: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "capability": config.capability,
            "error_code": "endpoint_not_configured",
            "endpoint_env": config.endpoint_env,
        }
        for config in configs
        if not config.configured
    ]


def expected_model_mismatch_issues(
    execution_configs: list[Any],
    preflight_configs: list[Any],
) -> list[dict[str, Any]]:
    expected_by_capability = {
        config.capability: set(config.expected_models)
        for config in preflight_configs
        if config.expected_models
    }
    issues = []
    for config in execution_configs:
        expected_models = expected_by_capability.get(config.capability, set())
        if expected_models and config.model_name not in expected_models:
            issues.append(
                {
                    "capability": config.capability,
                    "error_code": "expected_model_mismatch",
                    "model_name": config.model_name,
                    "expected_models": sorted(expected_models),
                }
            )
    return issues


def _snapshot(
    *,
    provider_mode: str,
    status: str,
    execution_configs: list[Any],
    preflight_configs: list[Any],
    issues: list[dict[str, Any]],
    env: dict[str, str],
    skip_reason: str | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "config_schema_version": "local_live_provider_config_snapshot.v1",
        "checked_at": _utc_now(),
        "provider_mode": provider_mode,
        "status": status,
        "execution_configs": [config.to_safe_summary() for config in execution_configs],
        "preflight_configs": [config.to_safe_summary() for config in preflight_configs],
        "model_profiles": selected_model_profile_summary(env),
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "policy": "provider endpoints and credentials are excluded",
            "checked_env_keys": [
                key for key in PROTECTED_CONFIG_ENV_KEYS if env.get(key)
            ],
        },
    }
    if skip_reason is not None:
        snapshot["skip_reason"] = skip_reason
    assert_config_snapshot_redacted(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        env,
    )
    return snapshot


def selected_model_profile_summary(env: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "profile_name": profile.profile_name,
            "provider_capability": profile.provider_capability,
            "alias": profile.alias,
            "provider_mode": profile.provider_mode,
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


def write_config_snapshot(
    output_path: Path,
    snapshot: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> None:
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2)
    assert_config_snapshot_redacted(
        serialized,
        environ if environ is not None else os.environ,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_config_snapshot_redacted(
    serialized_snapshot: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_CONFIG_ENV_KEYS
        if _protected_env_value_leaked(serialized_snapshot, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            f"local-live config snapshot contains unredacted environment value: {leaked_keys[0]}"
        )


def _protected_env_value_leaked(
    serialized_snapshot: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_snapshot


def summary_line(snapshot: dict[str, Any]) -> str:
    if snapshot["status"] == "SKIPPED":
        return "local_live_provider_config=skipped reason=NEX_MO_PROVIDER_MODE"
    return (
        f"local_live_provider_config={snapshot['status'].lower()} "
        f"issues={len(snapshot['issues'])}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local-live provider configuration without network calls."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON snapshot output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    snapshot = build_local_live_provider_config_snapshot()
    if args.output:
        write_config_snapshot(args.output, snapshot)
    if args.summary:
        print(summary_line(snapshot))
    else:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0 if snapshot["status"] in {"PASS", "SKIPPED"} else 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
