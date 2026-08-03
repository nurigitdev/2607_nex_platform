from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "_shared"))
sys.path.insert(0, str(ROOT_DIR / "services" / "nex-mo"))

from nex_mo.providers import build_model_profile_catalog

DEFAULT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class LiveProviderCheck:
    capability: str
    endpoint_env: str
    expected_models_env: str
    default_expected_models: tuple[str, ...]


LIVE_PROVIDER_CHECKS: tuple[LiveProviderCheck, ...] = (
    LiveProviderCheck(
        capability="embedding",
        endpoint_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
        expected_models_env="NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS",
        default_expected_models=("Qwen3-embedding-4B",),
    ),
    LiveProviderCheck(
        capability="reranking",
        endpoint_env="NEX_MO_LIVE_RERANKER_HEALTH_URL",
        expected_models_env="NEX_MO_LIVE_EXPECTED_RERANKER_MODELS",
        default_expected_models=("Qwen3-reranker-4B",),
    ),
    LiveProviderCheck(
        capability="generation",
        endpoint_env="NEX_MO_LIVE_VLLM_MODELS_URL",
        expected_models_env="NEX_MO_LIVE_EXPECTED_GENERATION_MODELS",
        default_expected_models=(
            "Qwen3.5-122B-A10B-NVFP4",
            "Qwen3.6-27B-NVFP4",
        ),
    ),
)


def run_dgx_live_provider_preflight(
    environ: dict[str, str] | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
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

    timeout_seconds = int(env.get("NEX_MO_LIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    checks = [
        run_live_provider_check(
            check,
            env,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        for check in LIVE_PROVIDER_CHECKS
    ]
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    return {
        "preflight_schema_version": "dgx_live_provider_preflight.v1",
        "status": status,
        "checks": checks,
        "model_profiles": selected_profile_summary(env),
    }


def run_live_provider_check(
    check: LiveProviderCheck,
    env: dict[str, str],
    *,
    opener: Callable[..., Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    configured = bool(env.get(check.endpoint_env))
    expected_models = expected_models_from_env(
        env.get(check.expected_models_env),
        check.default_expected_models,
    )
    base_result: dict[str, Any] = {
        "capability": check.capability,
        "endpoint_env": check.endpoint_env,
        "configured": configured,
        "expected_models": list(expected_models),
    }
    if not configured:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": "endpoint_not_configured",
        }

    try:
        response_text = fetch_text(env[check.endpoint_env], opener, timeout_seconds)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": exc.__class__.__name__,
        }

    missing_models = [
        model_name for model_name in expected_models if model_name not in response_text
    ]
    if missing_models:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": "expected_model_missing",
            "missing_expected_models": missing_models,
        }
    return {
        **base_result,
        "status": "PASS",
        "response_observed": True,
    }


def fetch_text(
    url: str,
    opener: Callable[..., Any],
    timeout_seconds: int,
) -> str:
    with opener(url, timeout=timeout_seconds) as response:
        raw_body = response.read()
    return raw_body.decode("utf-8", errors="replace")


def expected_models_from_env(
    value: str | None,
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    if not value:
        return defaults
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    return parsed or defaults


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
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_dgx_live_provider_preflight()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return "dgx_live_provider_preflight=skipped reason=NEX_MO_LIVE_PREFLIGHT"
    passed = sum(1 for check in evidence["checks"] if check["status"] == "PASS")
    total = len(evidence["checks"])
    return (
        f"dgx_live_provider_preflight={evidence['status'].lower()} "
        f"checks={passed}/{total}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
