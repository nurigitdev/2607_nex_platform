#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "smoke"
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    AE_WEB_URL_ENV,
    DEFAULT_PROFILE,
    EMPLOYEE_ID_ENV,
    OA_DATABASE_URL_ENV,
    PASSWORD_ENV,
    PROFILE_ENV,
    REQUIRED_ENV_SPECS,
    SMOKE_ENV as BROWSER_SMOKE_ENV,
    TENANT_ID_ENV,
    assert_boundary_evidence_redacted,
)


SCHEMA_VERSION = "ae_web_credential_login_browser_operator_profile.v1"
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "ae_web_credential_login_browser_smoke.md"
LIVE_RUNNER_PATH = (
    ROOT / "scripts" / "smoke" / "run_ae_web_credential_login_browser_live_smoke.py"
)
HARDENING_RUNNER_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_ae_web_credential_login_browser_postgres_evidence_hardening.py"
)
QUALITY_GATE_PATH = ROOT / "scripts" / "quality" / "run_quality_gate.sh"

REQUIRED_RUNBOOK_TOKENS = (
    BROWSER_SMOKE_ENV,
    PROFILE_ENV,
    AE_WEB_URL_ENV,
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    OA_DATABASE_URL_ENV,
    TENANT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
    "run_ae_web_credential_login_browser_live_smoke.py --summary",
    "run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary",
    "live_db=true",
    "issues=0",
)

REQUIRED_QUALITY_COMMANDS = (
    "run_ae_web_credential_login_browser_operator_profile.py --summary",
    "run_ae_web_credential_login_browser_live_smoke.py --summary",
    "run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary",
)

PROTECTED_ENV_KEYS = tuple(spec.name for spec in REQUIRED_ENV_SPECS) + (PROFILE_ENV,)


def run_ae_web_credential_login_browser_operator_profile(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    enabled = env.get(BROWSER_SMOKE_ENV) == "1"
    mode = "protected" if enabled else "default"
    path_checks = _path_checks(root_dir)
    runbook_checks = _runbook_checks(root_dir)
    quality_checks = _quality_gate_checks(root_dir)
    env_checks = _env_checks(env, enabled=enabled)
    issues = [
        *[
            _issue("path_missing", item["name"], "required path is missing")
            for item in path_checks
            if not item["present"]
        ],
        *[
            _issue("runbook_missing_token", item["token"], "runbook token is missing")
            for item in runbook_checks
            if not item["present"]
        ],
        *[
            _issue(
                "quality_gate_missing_command",
                item["command"],
                "quality gate command is missing",
            )
            for item in quality_checks
            if not item["present"]
        ],
        *[
            _issue(item["status"], item["name"], item["detail"])
            for item in env_checks
            if item["status"] not in {"configured", "deferred"}
        ],
    ]
    checks = {
        "paths_present": all(item["present"] for item in path_checks),
        "runbook_complete": all(item["present"] for item in runbook_checks),
        "quality_gate_wired": all(item["present"] for item in quality_checks),
        "default_mode_skips_live_db": True,
        "protected_mode_env_ready": (not enabled)
        or all(item["status"] == "configured" for item in env_checks),
        "test_database_guard": (not enabled)
        or all(
            item["status"] == "configured"
            for item in env_checks
            if item["name"] in {AE_DATABASE_URL_ENV, OA_DATABASE_URL_ENV}
        ),
        "redacted_evidence": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "profile_schema_version": SCHEMA_VERSION,
        "status": status,
        "mode": mode,
        "activation": {
            "env": BROWSER_SMOKE_ENV,
            "enabled": enabled,
            "profile_env": PROFILE_ENV,
            "requested_profile": env.get(PROFILE_ENV, DEFAULT_PROFILE),
            "required_profile": DEFAULT_PROFILE,
        },
        "paths": path_checks,
        "runbook_tokens": runbook_checks,
        "quality_gate_commands": quality_checks,
        "env": env_checks,
        "execution_order": [
            "operator_profile",
            "live_smoke",
            "postgres_evidence_hardening",
        ],
        "checks": checks,
        "issues": issues,
        "redaction": {
            "raw_password_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_operator_profile_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _path_checks(root_dir: Path) -> list[dict[str, object]]:
    paths = (
        ("runbook", root_dir / "docs" / "runbooks" / RUNBOOK_PATH.name),
        (
            "live_runner",
            root_dir / "scripts" / "smoke" / LIVE_RUNNER_PATH.name,
        ),
        (
            "hardening_runner",
            root_dir / "scripts" / "smoke" / HARDENING_RUNNER_PATH.name,
        ),
        ("quality_gate", root_dir / "scripts" / "quality" / QUALITY_GATE_PATH.name),
    )
    return [
        {
            "name": name,
            "path": _relative_label(path, root_dir),
            "present": path.exists(),
        }
        for name, path in paths
    ]


def _runbook_checks(root_dir: Path) -> list[dict[str, object]]:
    runbook = root_dir / "docs" / "runbooks" / RUNBOOK_PATH.name
    text = _read_text(runbook)
    return [
        {
            "token": token,
            "present": token in text,
        }
        for token in REQUIRED_RUNBOOK_TOKENS
    ]


def _quality_gate_checks(root_dir: Path) -> list[dict[str, object]]:
    text = _read_text(root_dir / "scripts" / "quality" / QUALITY_GATE_PATH.name)
    return [
        {
            "command": command,
            "present": command in text,
        }
        for command in REQUIRED_QUALITY_COMMANDS
    ]


def _env_checks(env: Mapping[str, str], *, enabled: bool) -> list[dict[str, str]]:
    if not enabled:
        return [
            {
                "name": spec.name,
                "scope": spec.scope,
                "status": "deferred",
                "detail": "not required until protected smoke is enabled",
            }
            for spec in REQUIRED_ENV_SPECS
        ]

    checks = []
    for spec in REQUIRED_ENV_SPECS:
        value = env.get(spec.name)
        status = "configured" if value else "required_env_missing"
        detail = "configured" if value else f"{spec.name} is required"
        if value and spec.name in {AE_DATABASE_URL_ENV, OA_DATABASE_URL_ENV}:
            if not _is_test_database_url(value):
                status = "database_not_test"
                detail = f"{spec.name} must target a *_test database"
        checks.append(
            {
                "name": spec.name,
                "scope": spec.scope,
                "status": status,
                "detail": detail,
            }
        )
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        checks.append(
            {
                "name": PROFILE_ENV,
                "scope": "operator-only",
                "status": "profile_not_allowed",
                "detail": f"{PROFILE_ENV} must be {DEFAULT_PROFILE}",
            }
        )
    return checks


def _is_test_database_url(value: str) -> bool:
    try:
        parsed = make_url(value)
    except SQLAlchemyError:
        return False
    return bool(parsed.database and parsed.database.endswith("_test"))


def assert_operator_profile_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    assert_boundary_evidence_redacted(serialized_evidence, dict(environ))
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and len(value) >= 8 and value not in {"1", DEFAULT_PROFILE}:
            if value in serialized_evidence:
                raise ValueError(
                    "AE Web credential-login browser operator profile evidence "
                    f"contains unredacted environment value: {key}"
                )


def write_operator_profile_evidence(
    output_path: Path,
    evidence: dict[str, Any],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_operator_profile_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def _issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        configured = sum(1 for item in evidence["env"] if item["status"] == "configured")
        return (
            "ae_web_credential_login_browser_operator_profile=pass "
            f"mode={evidence['mode']} "
            f"env={configured}/{len(REQUIRED_ENV_SPECS)} "
            f"order={len(evidence['execution_order'])}"
        )
    return (
        "ae_web_credential_login_browser_operator_profile=fail "
        f"mode={evidence.get('mode')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AE Web credential-login browser smoke operator profile."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_credential_login_browser_operator_profile()
        if args.output:
            write_operator_profile_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_credential_login_browser_operator_profile=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
