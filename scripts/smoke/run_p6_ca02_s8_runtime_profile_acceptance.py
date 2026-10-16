#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p6_ca02_s5_worker_readiness_smoke as s5
import run_p6_ca02_s6_recovery_smoke as s6
import run_p6_ca02_s7_dual_profile_postgres_smoke as s7
from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_V01_BACKEND_PROFILES,
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    normalize_nsl_backend_profile,
)
from nex_runtime import load_env_file

SCHEMA_VERSION = "p6_ca02_s8_runtime_profile_acceptance.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S8_ACCEPTANCE"
DEFAULT_REPORT = ROOT / "reports/smoke/p6-ca02-s8-runtime-profile-acceptance.json"
REQUIRED_DOCUMENTS = tuple(
    Path(f"docs/slices/p6_ca02_s{number}_{name}.md")
    for number, name in (
        (1, "nsl_dependency_wheel_admission"),
        (2, "dual_profile_compatibility"),
        (3, "in_process_nsl_read_backend"),
        (4, "profile_aware_backend_routing"),
        (5, "worker_readiness_default_activation"),
        (6, "timeout_crash_lease_recovery"),
        (7, "dual_profile_parity_postgres_e2e"),
    )
)
RUNTIME_SOURCE = Path("services/nex-ae-api/nex_ae_api")
ALLOWED_NSL_IMPORTS = frozenset({"nsl.api", "nsl.process_isolation"})

EvidenceRunner = Callable[[Mapping[str, str]], dict[str, Any]]


def run_p6_ca02_s8_runtime_profile_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    root: Path = ROOT,
    readiness_runner: EvidenceRunner = s5.run_p6_ca02_s5_worker_readiness_smoke,
    recovery_runner: EvidenceRunner = s6.run_p6_ca02_s6_recovery_smoke,
    parity_runner: EvidenceRunner = s7.run_p6_ca02_s7_dual_profile_postgres_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "acceptance_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S8",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    static = _static_evidence(root)
    readiness = readiness_runner({**env, s5.SMOKE_ENV: "1"})
    recovery = recovery_runner({**env, s6.SMOKE_ENV: "1"})
    parity = parity_runner({**env, s7.SMOKE_ENV: "1"})
    readiness_checks = dict(readiness.get("checks") or {})
    recovery_checks = dict(recovery.get("checks") or {})
    parity_checks = dict(parity.get("checks") or {})
    parity_dimensions = dict(parity.get("parity") or {})
    cleanup = dict(recovery.get("cleanup_counts") or {})
    profile_cleanup = dict(parity.get("profile_cleanup_counts") or {})

    checks = {
        **static["checks"],
        "installed_wheel_and_worker_readiness_passed": (
            readiness.get("status") == "PASS"
            and readiness.get("actual_installed_wheel") is True
            and bool(readiness_checks)
            and all(bool(value) for value in readiness_checks.values())
        ),
        "in_process_default_activation_passed": (
            readiness.get("default_backend_profile")
            == NSL_V01_IN_PROCESS_BACKEND
            and readiness_checks.get("worker_default_is_in_process") is True
            and readiness_checks.get("process_isolated_compatibility_preserved")
            is True
        ),
        "timeout_crash_and_lease_recovery_passed": (
            recovery.get("status") == "PASS"
            and recovery.get("actual_postgres") is True
            and bool(recovery_checks)
            and all(bool(value) for value in recovery_checks.values())
            and cleanup.get("remaining") == 0
        ),
        "dual_profile_postgres_e2e_passed": (
            parity.get("status") == "PASS"
            and parity.get("actual_postgres") is True
            and bool(parity_checks)
            and all(bool(value) for value in parity_checks.values())
        ),
        "stable_contract_and_lineage_parity_passed": (
            bool(parity_dimensions)
            and all(bool(value) for value in parity_dimensions.values())
            and parity_checks.get("skill_execution_request_parity") is True
            and parity_checks.get("nsl_result_summary_parity") is True
            and parity_checks.get("step_result_v1_2_parity") is True
            and parity_checks.get("identity_lineage_preserved_per_profile") is True
        ),
        "dual_profile_zero_residue_passed": (
            set(profile_cleanup) == set(NSL_V01_BACKEND_PROFILES)
            and all(
                values.get("remaining") == 0
                and values.get("s7_remaining") == 0
                for values in profile_cleanup.values()
            )
        ),
        "remote_model_provider_not_required": (
            readiness.get("remote_provider_required") is False
            and parity.get("remote_provider_required") is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "acceptance_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S8",
        "requirement": "Runtime-profile acceptance and P7 entry closure",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "p7_entry_profile": NSL_V01_IN_PROCESS_BACKEND,
        "optional_compatibility_profile": NSL_V01_PROCESS_ISOLATED_BACKEND,
        "static": static,
        "readiness": _projection(readiness),
        "recovery": _projection(recovery, cleanup=cleanup),
        "parity": _projection(
            parity,
            parity=parity_dimensions,
            cleanup=profile_cleanup,
        ),
        "remote_provider_required": False,
    }


def _static_evidence(root: Path) -> dict[str, Any]:
    missing_documents = [
        str(path) for path in REQUIRED_DOCUMENTS if not (root / path).is_file()
    ]
    private_imports = _disallowed_nsl_imports(root / RUNTIME_SOURCE)
    unknown_profile_rejected = False
    try:
        normalize_nsl_backend_profile("NSL_UNKNOWN_PROFILE")
    except ValueError:
        unknown_profile_rejected = True
    return {
        "checks": {
            "s1_through_s7_evidence_present": not missing_documents,
            "in_process_profile_is_canonical_default": (
                DEFAULT_NSL_V01_BACKEND_PROFILE == NSL_V01_IN_PROCESS_BACKEND
            ),
            "process_isolated_profile_remains_optional": (
                NSL_V01_BACKEND_PROFILES
                == frozenset(
                    {
                        NSL_V01_IN_PROCESS_BACKEND,
                        NSL_V01_PROCESS_ISOLATED_BACKEND,
                    }
                )
            ),
            "unknown_profile_fails_closed": unknown_profile_rejected,
            "ae_runtime_avoids_private_nsl_modules": not private_imports,
        },
        "missing_documents": missing_documents,
        "allowed_nsl_imports": sorted(ALLOWED_NSL_IMPORTS),
        "disallowed_nsl_imports": private_imports,
    }


def _disallowed_nsl_imports(source_root: Path) -> list[str]:
    hits: set[str] = set()
    for source in sorted(source_root.glob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError) as exc:
            hits.add(f"{source.name}:unreadable:{type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if (module == "nsl" or module.startswith("nsl.")) and not any(
                    module == allowed or module.startswith(f"{allowed}.")
                    for allowed in ALLOWED_NSL_IMPORTS
                ):
                    hits.add(f"{source.name}:{node.lineno}:{module}")
    return sorted(hits)


def _projection(
    evidence: Mapping[str, Any],
    *,
    cleanup: Mapping[str, Any] | None = None,
    parity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    checks = dict(evidence.get("checks") or {})
    result = {
        "status": evidence.get("status"),
        "actual_postgres": evidence.get("actual_postgres") is True,
        "check_count": len(checks),
        "passed_check_count": sum(bool(value) for value in checks.values()),
    }
    if cleanup is not None:
        result["cleanup"] = dict(cleanup)
    if parity is not None:
        result["parity"] = dict(parity)
    return result


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return "p6_ca02_s8_runtime_profile_acceptance=skipped"
    checks = dict(evidence.get("checks") or {})
    return (
        "p6_ca02_s8_runtime_profile_acceptance="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"postgres={str((evidence.get('parity') or {}).get('actual_postgres') is True).lower()} "
        f"p7_profile={evidence.get('p7_entry_profile', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected P6-CA02 runtime-profile/P7-entry acceptance"
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_ca02_s8_runtime_profile_acceptance()
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
