#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from run_ae_web_credential_login_browser_harness_smoke import (  # noqa: E402
    NODE_SCRIPT,
    safe_browser_config,
)
from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    AE_WEB_URL_ENV,
    EMPLOYEE_ID_ENV,
    OA_DATABASE_URL_ENV,
    PASSWORD_ENV,
    SMOKE_ENV as BROWSER_SMOKE_ENV,
    TENANT_ID_ENV,
    assert_boundary_evidence_redacted,
    run_ae_web_credential_login_browser_smoke_boundary,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_credential_login_browser_execution_readiness.v1"
NEXT_EXECUTION_SLICE = "Slice 0265"
POSTGRES_HARDENING_SLICE = "Slice 0266"


@dataclass(frozen=True)
class ReadinessPath:
    name: str
    path: Path
    purpose: str


REQUIRED_PATHS = (
    ReadinessPath(
        "boundary_runner",
        ROOT_DIR / "scripts" / "smoke" / "run_ae_web_credential_login_browser_smoke_boundary.py",
        "Protected browser smoke activation and redaction boundary.",
    ),
    ReadinessPath(
        "harness_runner",
        ROOT_DIR / "scripts" / "smoke" / "run_ae_web_credential_login_browser_harness_smoke.py",
        "Deterministic browser harness smoke wrapper.",
    ),
    ReadinessPath(
        "node_harness_script",
        NODE_SCRIPT,
        "AE Web credential-login harness evidence producer.",
    ),
    ReadinessPath(
        "ae_web_shell",
        ROOT_DIR / "apps" / "nex-ae-web" / "index.html",
        "Static AE Web browser shell.",
    ),
    ReadinessPath(
        "ae_web_package",
        ROOT_DIR / "apps" / "nex-ae-web" / "package.json",
        "AE Web local Node command registry.",
    ),
    ReadinessPath(
        "quality_gate",
        ROOT_DIR / "scripts" / "quality" / "run_quality_gate.sh",
        "Default regression and smoke orchestration.",
    ),
)

REQUIRED_ANCHORS = (
    "credential-login-form",
    "credential-tenant-id",
    "credential-employee-id",
    "credential-password",
    "credential-login-submit-button",
    "credential-logout-button",
    "session-route-guard-summary",
)

REQUIRED_QUALITY_COMMANDS = (
    "run_ae_web_credential_login_browser_execution_readiness.py --summary",
    "run_ae_web_credential_login_browser_smoke_boundary.py --summary",
    "run_ae_web_credential_login_browser_harness_smoke.py --summary",
)

REQUIRED_PACKAGE_COMMANDS = (
    "smoke:credential-login-harness",
    "node scripts/runCredentialLoginBrowserHarnessSmoke.mjs --summary",
)

PROTECTED_ENV_KEYS = (
    AE_WEB_URL_ENV,
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    OA_DATABASE_URL_ENV,
    TENANT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
)


def run_ae_web_credential_login_browser_execution_readiness(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT_DIR,
    node_command: str = "node",
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    boundary = run_ae_web_credential_login_browser_smoke_boundary(
        env,
        browser_config=safe_browser_config(),
    )
    path_checks = path_readiness(root_dir)
    anchor_checks = anchor_readiness(root_dir)
    wiring_checks = wiring_readiness(root_dir)
    dependency_checks = dependency_readiness(node_command)
    execution_plan = build_execution_plan()
    checks = {
        "boundary_not_failed": boundary["status"] != "FAIL",
        "required_paths_present": all(item["present"] for item in path_checks),
        "credential_login_anchors_present": all(
            item["present"] for item in anchor_checks
        ),
        "quality_gate_wired": all(item["present"] for item in wiring_checks["quality_gate"]),
        "package_script_wired": all(item["present"] for item in wiring_checks["package"]),
        "node_available": dependency_checks["node_available"],
        "playwright_dependency_deferred": True,
        "test_database_envs_declared": {
            AE_DATABASE_URL_ENV,
            OA_DATABASE_URL_ENV,
        }.issubset({item["name"] for item in boundary["required_env"]}),
        "live_smoke_requires_explicit_env": boundary["activation"]["env"]
        == BROWSER_SMOKE_ENV,
        "postgres_hardening_next_slice_recorded": execution_plan[
            "postgres_hardening_slice"
        ]
        == POSTGRES_HARDENING_SLICE,
        "redacted_evidence_only": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "readiness_schema_version": SCHEMA_VERSION,
        "status": status,
        "boundary": {
            "schema_version": boundary["evidence_schema_version"],
            "status": boundary["status"],
            "activation_env": BROWSER_SMOKE_ENV,
            "required_env_count": len(boundary["required_env"]),
            "required_phase_count": len(boundary["required_phases"]),
            "browser_route_count": len(boundary["browser_routes"]),
        },
        "paths": path_checks,
        "anchors": anchor_checks,
        "wiring": wiring_checks,
        "dependencies": dependency_checks,
        "execution_plan": execution_plan,
        "checks": checks,
        "redaction": {
            "raw_password_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_readiness_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def path_readiness(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "present": item.path.exists(),
            "purpose": item.purpose,
        }
        for item in REQUIRED_PATHS
    ]


def anchor_readiness(root_dir: Path) -> list[dict[str, object]]:
    html_path = root_dir / "apps" / "nex-ae-web" / "index.html"
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    return [
        {
            "anchor": anchor,
            "present": anchor in html,
        }
        for anchor in REQUIRED_ANCHORS
    ]


def wiring_readiness(root_dir: Path) -> dict[str, list[dict[str, object]]]:
    quality_gate = read_text(root_dir / "scripts" / "quality" / "run_quality_gate.sh")
    package_json = read_text(root_dir / "apps" / "nex-ae-web" / "package.json")
    return {
        "quality_gate": [
            {"command": command, "present": command in quality_gate}
            for command in REQUIRED_QUALITY_COMMANDS
        ],
        "package": [
            {"command": command, "present": command in package_json}
            for command in REQUIRED_PACKAGE_COMMANDS
        ],
    }


def dependency_readiness(node_command: str) -> dict[str, object]:
    return {
        "node_command": node_command,
        "node_available": shutil.which(node_command) is not None,
        "playwright_required_for_current_runner": False,
        "playwright_adoption_status": "deferred_until_explicit_dependency_decision",
    }


def build_execution_plan() -> dict[str, object]:
    return {
        "execution_slice": NEXT_EXECUTION_SLICE,
        "postgres_hardening_slice": POSTGRES_HARDENING_SLICE,
        "default_quality_gate_mode": "readiness_pass_no_live_db_connection",
        "protected_execution_mode": "fastapi_testclient_with_real_ae_oa_test_databases",
        "future_browser_automation_mode": "playwright_or_equivalent_after_dependency_decision",
        "must_connect_test_databases_when_smoke_enabled": [
            AE_DATABASE_URL_ENV,
            OA_DATABASE_URL_ENV,
        ],
        "must_prove": [
            "ae_oa_migrations_current",
            "oa_credential_login",
            "ae_cookie_session_facade",
            "route_guard_allowed",
            "logout_revocation_readback",
            "redacted_evidence",
        ],
    }


def assert_readiness_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    assert_boundary_evidence_redacted(serialized_evidence, environ)
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and len(value) >= 8 and value in serialized_evidence:
            raise ValueError(
                "AE Web credential-login browser execution readiness evidence "
                f"contains unredacted environment value: {key}"
            )


def write_readiness_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_readiness_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ae_web_credential_login_browser_execution_readiness=pass "
            f"boundary={str(evidence['boundary']['status']).lower()} "
            f"paths={sum(1 for item in evidence['paths'] if item['present'])}/{len(evidence['paths'])} "
            f"anchors={sum(1 for item in evidence['anchors'] if item['present'])}/{len(evidence['anchors'])} "
            f"next={str(evidence['execution_plan']['execution_slice']).replace(' ', '_')}"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return (
        "ae_web_credential_login_browser_execution_readiness=fail "
        f"checks={failed_checks}"
    )


def relative_label(path: Path, root_dir: Path = ROOT_DIR) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AE Web credential-login protected browser execution readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    parser.add_argument("--node-command", default="node")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_web_credential_login_browser_execution_readiness(
            node_command=args.node_command,
        )
        if args.output:
            write_readiness_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except ValueError as exc:
        print(
            "ae_web_credential_login_browser_execution_readiness=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
