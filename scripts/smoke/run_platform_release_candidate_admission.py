#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime import evaluate_release_candidate_admission  # noqa: E402


def build_sample_release_candidate_environment() -> dict[str, str]:
    database_specs = (
        ("OA", "nex_oa_user", "nex_oa_test"),
        ("MO", "nex_mo_user", "nex_mo_test"),
        ("CX", "nex_cx_user", "nex_cx_test"),
        ("AE", "nex_ae_user", "nex_ae_test"),
        ("AG", "nex_ag_user", "nex_ag_test"),
    )
    env = {
        "NEX_S140_RELEASE_CANDIDATE_ACCEPTANCE": "1",
        "NEX_S140_RELEASE_CANDIDATE_PROFILE": "test_live",
        "NEX_S140_BROWSER_VIEWPORTS": "desktop,mobile",
        "NEX_PERSISTENCE_MODE": "postgres",
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_AG_OPERATIONS_SOURCE_MODE": "api",
        "NEX_AE_AUTH_SESSION_MODE": "oa",
        "NEX_MO_PROTECTED_LIVE_PROFILE": "dgx_vllm",
        "NEX_MO_REMOTE_EMBEDDING_URL": (
            "http://provider.invalid:9112/v1/embeddings"
        ),
        "NEX_MO_REMOTE_RERANKER_URL": (
            "http://provider.invalid:9113/v1/rerank"
        ),
        "NEX_MO_VLLM_BASE_URL": "http://provider.invalid:9111",
    }
    env.update(
        {
            f"NEX_{service}_TEST_DATABASE_URL": (
                "postgresql+psycopg://"
                f"{role}:contract-only@127.0.0.1:5432/{database}"
            )
            for service, role, database in database_specs
        }
    )
    return env


def run_platform_release_candidate_admission(
    environ: Mapping[str, str] | None = None,
    *,
    contract_sample: bool = False,
) -> dict[str, Any]:
    env = (
        build_sample_release_candidate_environment()
        if contract_sample
        else dict(os.environ if environ is None else environ)
    )
    result = evaluate_release_candidate_admission(env)
    result["contract_sample"] = contract_sample
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "platform_release_candidate_admission="
            f"{status} admitted={str(result.get('admitted') is True).lower()} "
            f"next={dict(result.get('decision') or {}).get('next_slice', 'blocked')}"
        )
    database = dict(result.get("database_profile") or {})
    provider = dict(result.get("provider_profile") or {})
    browser = dict(result.get("browser_profile") or {})
    return (
        "platform_release_candidate_admission=pass "
        f"databases={database.get('service_count', 0)} "
        f"providers={provider.get('capability_count', 0)} "
        f"viewports={browser.get('viewport_count', 0)} "
        f"next={dict(result.get('decision') or {}).get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sample", action="store_true")
    mode.add_argument("--environment", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_admission(
        contract_sample=args.sample or not args.environment
    )
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
