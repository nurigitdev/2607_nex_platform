from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
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
