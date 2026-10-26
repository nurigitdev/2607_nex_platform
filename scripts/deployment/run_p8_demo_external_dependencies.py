#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services/_shared", ROOT / "scripts/smoke"):
    sys.path.insert(0, str(path))

from nex_runtime.demo_external_dependencies import (  # noqa: E402
    DemoExternalDependencyError,
    admit_demo_external_dependencies,
)
import run_dgx_live_provider_preflight as dgx  # noqa: E402
import run_s146_object_storage_acceptance as rustfs  # noqa: E402


ENABLE_ENV = "NEX_P8_DEMO_EXTERNAL_DEPENDENCIES"
REPORT_PATH = ROOT / "reports/deployment/p8-demo-external-dependencies.json"
ProviderRunner = Callable[[dict[str, str]], Mapping[str, Any]]
ObjectRunner = Callable[[dict[str, str]], Mapping[str, Any]]


def run_p8_demo_external_dependencies(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    provider_runner: ProviderRunner | None = None,
    object_runner: ObjectRunner | None = None,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": "p8_demo_external_dependencies.v1",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ENABLE_ENV}=1 are required",
            "next_slice": "P8-DEMO-S09",
        }
    source_env = {
        **env,
        "NEX_MO_LIVE_PREFLIGHT": "1",
        "NEX_S146_PROTECTED_ACCEPTANCE": "1",
    }
    provider_call = provider_runner or dgx.run_dgx_live_provider_preflight
    object_call = object_runner or _run_rustfs
    try:
        result = admit_demo_external_dependencies(
            provider_call(source_env),
            object_call(source_env),
        )
    except (DemoExternalDependencyError, OSError, RuntimeError, ValueError):
        result = {
            "schema_version": "p8_demo_external_dependencies.v1",
            "status": "FAIL",
            "failure_code": "demo_external_dependency_admission_failed",
            "raw_secret_values_included": False,
            "provider_endpoints_included": False,
            "private_payloads_included": False,
            "next_slice": "blocked",
        }
    _assert_redacted(result, env)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _run_rustfs(environ: dict[str, str]) -> Mapping[str, Any]:
    return rustfs.run_s146_object_storage_acceptance(
        environ,
        execute=True,
        root=ROOT,
        report_path=ROOT / "reports/deployment/p8-demo-rustfs-acceptance.json",
    )


def _assert_redacted(result: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    protected_names = (
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_REMOTE_RERANKER_API_KEY",
        "NEX_MO_VLLM_BASE_URL",
        "NEX_MO_VLLM_API_KEY",
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_AE_TEST_DATABASE_URL",
    )
    for name in protected_names:
        value = str(environ.get(name) or "")
        if len(value) >= 8 and value in serialized:
            raise DemoExternalDependencyError(
                "Demo external dependency evidence contains protected material"
            )


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"p8_demo_external_dependencies={str(result.get('status')).lower()}"
    provider = dict(result.get("provider") or {})
    storage = dict(result.get("object_storage") or {})
    return (
        "p8_demo_external_dependencies=pass "
        f"providers={provider.get('capability_count', 0)}/3 "
        f"buckets={storage.get('bucket_count', 0)} "
        f"tls={str(storage.get('managed_tls')).lower()} "
        f"restart={str(storage.get('restart_recovery')).lower()} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_p8_demo_external_dependencies(
        execute=args.execute,
        report_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
