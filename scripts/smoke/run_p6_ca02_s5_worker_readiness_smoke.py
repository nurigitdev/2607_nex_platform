#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
):
    sys.path.insert(0, str(path))

from nex_ae_api.agent_runtime_worker import (
    LOCAL_SKILL_EXECUTOR,
    WORKER_BACKEND_PROFILES_ENV,
    WORKER_MODE_ENV,
    AgentRuntimeWorkerConfig,
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
    load_agent_runtime_worker_config,
    load_in_process_nsl_package_readiness,
)
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendRouter,
    build_v01_in_process_backend,
)
from nex_runtime import load_env_file

SCHEMA_VERSION = "p6_ca02_s5_worker_readiness_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S5_WORKER_READINESS_SMOKE"
DEFAULT_REPORT = ROOT / "reports/smoke/p6-ca02-s5-worker-readiness.json"


class _ProcessIsolatedProbe:
    backend_profile = NSL_V01_PROCESS_ISOLATED_BACKEND

    def execute(self, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError(
            "readiness smoke must not invoke the compatibility backend"
        )


def run_p6_ca02_s5_worker_readiness_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S5",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_installed_wheel": False,
        }
    try:
        readiness = load_in_process_nsl_package_readiness(env)
        config_env = {
            key: value
            for key, value in env.items()
            if key != WORKER_BACKEND_PROFILES_ENV
        }
        config_env[WORKER_MODE_ENV] = "enabled"
        config = load_agent_runtime_worker_config(config_env)
        in_process = build_v01_in_process_backend(
            lambda _artifact_handle, _progress: None
        )
        router = NSLReadBackendRouter({NSL_V01_IN_PROCESS_BACKEND: in_process})
        worker_check = build_agent_runtime_worker_check(
            config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=router.backend_profiles,
            in_process_package_readiness=readiness,
        )

        compatibility_config = AgentRuntimeWorkerConfig(
            mode="enabled",
            profile=build_agent_runtime_worker_profile(
                worker_id="ae-agent-runtime-worker-process-compatibility",
                declared_at=config.profile.declared_at,
                supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
                process_isolation_required=True,
            ),
        )
        compatibility_router = NSLReadBackendRouter(
            {NSL_V01_PROCESS_ISOLATED_BACKEND: _ProcessIsolatedProbe()}
        )
        compatibility_check = build_agent_runtime_worker_check(
            compatibility_config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=compatibility_router.backend_profiles,
        )
        checks = {
            "installed_package_readiness_passed": readiness.get("status") == "PASS",
            "admitted_wheel_digest_present": str(
                readiness.get("wheel_sha256", "")
            ).startswith("sha256:"),
            "dependency_lock_digest_present": str(
                readiness.get("platform_lock_sha256", "")
            ).startswith("sha256:"),
            "worker_default_is_in_process": (
                config.profile.supported_backend_profiles
                == (NSL_V01_IN_PROCESS_BACKEND,)
            ),
            "worker_default_needs_no_process_isolation": (
                config.profile.process_isolation_required is False
            ),
            "actual_router_advertises_exact_default": (
                router.backend_profiles == (NSL_V01_IN_PROCESS_BACKEND,)
            ),
            "worker_startup_readiness_passed": (
                worker_check.get("status") == "PASS"
                and worker_check.get("execution_composed") is True
                and worker_check.get("in_process_package_status") == "PASS"
            ),
            "process_isolated_compatibility_preserved": (
                compatibility_check.get("status") == "PASS"
                and compatibility_check.get("in_process_package_status")
                == "NOT_CONFIGURED"
            ),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S5",
            "status": status,
            "actual_installed_wheel": readiness.get("status") == "PASS",
            "default_backend_profile": NSL_V01_IN_PROCESS_BACKEND,
            "readiness": readiness,
            "worker_check": worker_check,
            "compatibility_check": compatibility_check,
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "actual_postgres": False,
            "remote_provider_required": False,
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _failure("execution_failed", str(exc))


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S5",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_installed_wheel": False,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        f"p6_ca02_s5_worker_readiness="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"actual_installed_wheel="
        f"{str(bool(evidence.get('actual_installed_wheel'))).lower()} "
        f"checks={evidence.get('checks_passed', 0)}/"
        f"{evidence.get('checks_total', 0)} "
        f"default_profile={evidence.get('default_backend_profile', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P6-CA02-S5 worker readiness protected smoke"
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env")
    evidence = run_p6_ca02_s5_worker_readiness_smoke()
    if evidence["status"] != "SKIPPED":
        DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_REPORT.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
