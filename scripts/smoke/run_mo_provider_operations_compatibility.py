#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.runtime_hardening_audit import (  # noqa: E402
    build_mo_runtime_hardening_audit,
)
import run_mo_dgx_process_dtype_probe as dtype_probe  # noqa: E402
import run_protected_dgx_live_profile as live_profile  # noqa: E402
import run_protected_remote_provider_live_smoke as live_smoke  # noqa: E402


ACTIVATION_ENV = "NEX_MO_PROVIDER_OPERATIONS_COMPATIBILITY_LIVE"
EVIDENCE_SCHEMA_VERSION = "mo_provider_operations_compatibility.v1"
PROTECTED_ENV_KEYS = tuple(
    dict.fromkeys(
        (
            *live_profile.PROTECTED_PROFILE_ENV_KEYS,
            *live_smoke.PROTECTED_ENV_KEYS,
            dtype_probe.SSH_TARGET_ENV,
        )
    )
)

EvidenceRunner = Callable[[dict[str, str]], dict[str, Any]]
AuditRunner = Callable[[], dict[str, Any]]


def run_mo_provider_operations_compatibility(
    environ: dict[str, str] | None = None,
    *,
    architecture_runner: AuditRunner = build_mo_runtime_hardening_audit,
    profile_runner: EvidenceRunner = live_profile.run_protected_dgx_live_profile,
    provider_runner: EvidenceRunner = live_smoke.run_protected_remote_provider_live_smoke,
    dtype_runner: EvidenceRunner = dtype_probe.run_mo_dgx_process_dtype_probe,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    live_requested = env.get(ACTIVATION_ENV) == "1"
    effective_env = _effective_env(env, live_requested=live_requested)

    architecture = architecture_runner()
    profile = profile_runner(effective_env)
    providers = provider_runner(effective_env)
    dtype = dtype_runner(effective_env)
    component_status = {
        "architecture": _status(architecture),
        "profile_preflight": _status(profile),
        "provider_requests": _status(providers),
        "process_dtype": _status(dtype),
    }
    live_statuses = tuple(
        component_status[name]
        for name in ("profile_preflight", "provider_requests", "process_dtype")
    )
    checks = {
        "architecture_hardened": component_status["architecture"] == "PASS",
        "protected_components_not_failed": "FAIL" not in live_statuses,
        "requested_live_evidence_complete": (
            not live_requested or all(status == "PASS" for status in live_statuses)
        ),
    }
    passed = all(checks.values())
    evidence = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": _utc_now(),
        "slice": "1120",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "readiness": _readiness(passed, live_requested, live_statuses),
        "live_requested": live_requested,
        "component_status": component_status,
        "checks": checks,
        "summary": {
            "architecture_modules": _architecture_module_count(architecture),
            "profile_stages_passed": _passed_stage_count(profile),
            "provider_requests_passed": _provider_request_count(providers),
            "bf16_confirmed": _dtype_count(dtype, "bf16_confirmed"),
            "bf16_explicit": _dtype_count(dtype, "bf16_explicit"),
        },
        "issues": _issues(component_status, live_requested=live_requested),
        "redaction": {
            "status": "PASS",
            "excluded": [
                "provider_endpoint",
                "api_key",
                "ssh_target",
                "process_command_line",
                "model_path",
                "request_payload",
                "response_payload",
            ],
        },
        "next_slice": "1121" if passed else None,
    }
    assert_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        effective_env,
    )
    return evidence


def _effective_env(env: dict[str, str], *, live_requested: bool) -> dict[str, str]:
    if not live_requested:
        return env
    return {
        **env,
        live_profile.PROFILE_ENV: live_profile.DGX_PROFILE_NAME,
        live_smoke.LIVE_SMOKE_ENV: "1",
        dtype_probe.ACTIVATION_ENV: "1",
    }


def _status(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").upper()
    return status if status in {"PASS", "FAIL", "SKIPPED"} else "FAIL"


def _readiness(
    passed: bool,
    live_requested: bool,
    live_statuses: tuple[str, ...],
) -> str:
    if not passed:
        return "BLOCKED"
    if live_requested or all(status == "PASS" for status in live_statuses):
        return "LIVE_COMPATIBLE"
    return "DETERMINISTIC_COMPATIBLE_LIVE_NOT_REQUESTED"


def _architecture_module_count(evidence: Mapping[str, Any]) -> int:
    summary = evidence.get("summary")
    if not isinstance(summary, Mapping):
        return 0
    return int(summary.get("module_rule_pass_count") or 0)


def _passed_stage_count(evidence: Mapping[str, Any]) -> int:
    stages = evidence.get("stage_status")
    if not isinstance(stages, Mapping):
        return 0
    return sum(status == "PASS" for status in stages.values())


def _provider_request_count(evidence: Mapping[str, Any]) -> int:
    stages = evidence.get("stage_status")
    if not isinstance(stages, Mapping):
        return 0
    return sum(stages.get(name) == "PASS" for name in ("embedding", "reranking", "generation"))


def _dtype_count(evidence: Mapping[str, Any], field: str) -> int:
    observations = evidence.get("observations")
    if not isinstance(observations, list):
        return 0
    return sum(bool(item.get(field)) for item in observations if isinstance(item, Mapping))


def _issues(
    component_status: Mapping[str, str],
    *,
    live_requested: bool,
) -> list[dict[str, str]]:
    issues = [
        {
            "component": component,
            "error_code": "provider_operations_compatibility_component_failed",
        }
        for component, status in component_status.items()
        if status == "FAIL"
    ]
    if live_requested:
        issues.extend(
            {
                "component": component,
                "error_code": "requested_live_evidence_not_completed",
            }
            for component, status in component_status.items()
            if component != "architecture" and status == "SKIPPED"
        )
    return issues


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    leaked = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_value_leaked(serialized, env.get(key))
    ]
    if leaked:
        raise ValueError(
            "MO provider operations compatibility evidence contains protected value: "
            f"{leaked[0]}"
        )


def _protected_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    components = evidence.get("component_status") or {}
    return (
        "mo_provider_operations_compatibility="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"live={str(evidence.get('readiness') or 'BLOCKED').lower()} "
        f"profile={components.get('profile_preflight', 'FAIL')} "
        f"providers={summary.get('provider_requests_passed', 0)}/3 "
        f"bf16={summary.get('bf16_confirmed', 0)}/3 "
        f"explicit={summary.get('bf16_explicit', 0)}/3 "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_operations_compatibility()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
