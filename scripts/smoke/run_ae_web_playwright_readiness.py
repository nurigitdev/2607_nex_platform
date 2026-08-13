#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "smoke"
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_same_origin_runtime_boundary import (  # noqa: E402
    PROXY_TARGET_ENV,
    assert_same_origin_evidence_redacted,
    run_ae_web_same_origin_runtime_boundary,
)


SCHEMA_VERSION = "ae_web_playwright_readiness.v1"
NODE_SCHEMA_VERSION = "ae_web_playwright_readiness_node.v1"
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
PACKAGE_JSON = WEB_ROOT / "package.json"
PACKAGE_LOCK = WEB_ROOT / "package-lock.json"
NODE_READINESS_SCRIPT = WEB_ROOT / "scripts" / "runCredentialLoginPlaywrightReadiness.mjs"
NODE_READINESS_TEST = WEB_ROOT / "test" / "playwrightReadiness.test.mjs"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "ae_web_credential_login_browser_smoke.md"
PLAYWRIGHT_PACKAGE = "@playwright/test"
NODE_SMOKE_SCRIPT_NAME = "smoke:playwright-readiness"

Runner = Callable[..., subprocess.CompletedProcess[str]]

REQUIRED_NODE_SCRIPT_TOKENS = (
    "AE_WEB_PLAYWRIGHT_READINESS_SCHEMA_VERSION",
    "runPlaywrightReadiness",
    "import(\"playwright\")",
    "PLAYWRIGHT_LAUNCH_CHECK_ENV",
    "NEX_AE_WEB_PLAYWRIGHT_BROWSER",
    "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE",
    "chromium",
    "credential_login_route",
    "/ae-api/api/v1/auth/session/login",
    "postgres_test_databases_required_for_live_smoke",
    "assertPlaywrightReadinessEvidenceRedacted",
)

REQUIRED_NODE_TEST_TOKENS = (
    "runPlaywrightReadiness",
    "fakePlaywright",
    "launchCheck: true",
    "browser_launch_failed",
    "assertPlaywrightReadinessEvidenceRedacted",
)

REQUIRED_RUNBOOK_TOKENS = (
    "AE_API_PROXY_TARGET",
    "run_ae_web_same_origin_runtime_boundary.py --summary",
)

REQUIRED_QUALITY_TOKENS = (
    "run_ae_web_playwright_readiness.py --summary",
    "run_ae_web_same_origin_runtime_boundary.py --summary",
)

PROTECTED_ENV_KEYS = (PROXY_TARGET_ENV,)


def run_ae_web_playwright_readiness(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
    require_installed: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    package = _load_json(root_dir / _relative(PACKAGE_JSON))
    package_lock = _load_json(root_dir / _relative(PACKAGE_LOCK))
    node_source = _read_text(root_dir / _relative(NODE_READINESS_SCRIPT))
    node_test_source = _read_text(root_dir / _relative(NODE_READINESS_TEST))
    quality_source = _read_text(root_dir / _relative(QUALITY_GATE))
    runbook_source = _read_text(root_dir / _relative(RUNBOOK_PATH))
    same_origin_boundary = run_ae_web_same_origin_runtime_boundary(
        {},
        root_dir=root_dir,
    )
    node_execution = (
        run_node_readiness(root_dir=root_dir, runner=runner)
        if require_installed
        else {
            "status": "SKIPPED",
            "reason": "require_installed_false",
            "node_schema_version": NODE_SCHEMA_VERSION,
        }
    )

    file_checks = _file_checks(root_dir)
    token_checks = {
        "node_script": _token_checks(node_source, REQUIRED_NODE_SCRIPT_TOKENS),
        "node_test": _token_checks(node_test_source, REQUIRED_NODE_TEST_TOKENS),
        "runbook": _token_checks(runbook_source, REQUIRED_RUNBOOK_TOKENS),
        "quality_gate": _token_checks(quality_source, REQUIRED_QUALITY_TOKENS),
    }
    package_checks = {
        "dev_dependency_declared": (
            package.get("devDependencies", {}).get(PLAYWRIGHT_PACKAGE) is not None
        ),
        "lockfile_pins_playwright_test": (
            "node_modules/@playwright/test" in package_lock.get("packages", {})
        ),
        "npm_script_wired": (
            NODE_SMOKE_SCRIPT_NAME in package.get("scripts", {})
            and "runCredentialLoginPlaywrightReadiness.mjs"
            in package.get("scripts", {}).get(NODE_SMOKE_SCRIPT_NAME, "")
        ),
    }
    checks = {
        "same_origin_boundary_pass": same_origin_boundary["status"] == "PASS",
        "files_present": all(item["present"] for item in file_checks),
        "package_playwright_declared": all(package_checks.values()),
        "node_readiness_contract_present": all(
            item["present"] for item in token_checks["node_script"]
        ),
        "node_regression_present": all(
            item["present"] for item in token_checks["node_test"]
        ),
        "runbook_mentions_same_origin_proxy": all(
            item["present"] for item in token_checks["runbook"]
        ),
        "quality_gate_wired": all(
            item["present"] for item in token_checks["quality_gate"]
        ),
        "node_dependency_import_checked": (
            node_execution["status"] in {"PASS", "SKIPPED"}
        ),
        "redacted_evidence": True,
    }
    issues = [
        *[
            _issue("file_missing", item["path"], "required file is missing")
            for item in file_checks
            if not item["present"]
        ],
        *[
            _issue("token_missing", f"{group}:{item['token']}", "required token is missing")
            for group, items in token_checks.items()
            for item in items
            if not item["present"]
        ],
        *[
            _issue("package_missing", name, "required Playwright package wiring is missing")
            for name, present in package_checks.items()
            if not present
        ],
    ]
    if node_execution["status"] == "FAIL":
        issues.append(
            _issue(
                "node_readiness_failed",
                str(node_execution.get("reason", "unknown")),
                "Node Playwright readiness execution failed.",
            )
        )

    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "readiness_schema_version": SCHEMA_VERSION,
        "status": status,
        "mode": "installed" if require_installed else "static",
        "playwright": {
            "package": PLAYWRIGHT_PACKAGE,
            "browser": "chromium",
            "launch_check_default": "deferred",
            "launch_check_env": "NEX_AE_WEB_PLAYWRIGHT_LAUNCH_CHECK",
            "chromium_executable_env": "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE",
            "next_execution_slice": "Slice 0270",
        },
        "same_origin_boundary": {
            "schema_version": same_origin_boundary["boundary_schema_version"],
            "status": same_origin_boundary["status"],
            "proxy_prefix": same_origin_boundary["proxy"]["prefix"],
        },
        "node_execution": node_execution,
        "files": file_checks,
        "package_checks": package_checks,
        "tokens": token_checks,
        "checks": checks,
        "issues": issues,
        "redaction": {
            "proxy_target_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "password_in_evidence": False,
            "cookie_material_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_playwright_readiness_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def run_node_readiness(
    *,
    root_dir: Path = ROOT,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    try:
        completed = runner(
            [
                "node",
                str(root_dir / _relative(NODE_READINESS_SCRIPT)),
                "--json",
            ],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "reason": "node_timeout", "node_schema_version": NODE_SCHEMA_VERSION}
    except OSError:
        return {"status": "FAIL", "reason": "node_unavailable", "node_schema_version": NODE_SCHEMA_VERSION}

    if completed.returncode != 0:
        return {
            "status": "FAIL",
            "reason": "node_failed",
            "returncode": completed.returncode,
            "node_schema_version": NODE_SCHEMA_VERSION,
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "FAIL",
            "reason": "node_json_invalid",
            "returncode": completed.returncode,
            "node_schema_version": NODE_SCHEMA_VERSION,
        }
    return {
        "status": payload.get("status", "FAIL"),
        "reason": None if payload.get("status") == "PASS" else "node_payload_failed",
        "node_schema_version": payload.get("readiness_schema_version"),
        "mode": payload.get("runner", {}).get("mode"),
        "launch_check_requested": payload.get("checks", {}).get("launch_check_requested"),
    }


def _file_checks(root_dir: Path) -> list[dict[str, object]]:
    paths = (
        PACKAGE_JSON,
        PACKAGE_LOCK,
        NODE_READINESS_SCRIPT,
        NODE_READINESS_TEST,
        QUALITY_GATE,
        RUNBOOK_PATH,
    )
    return [
        {
            "path": _relative_label(path, root_dir),
            "present": (root_dir / _relative(path)).exists(),
        }
        for path in paths
    ]


def _token_checks(text: str, tokens: tuple[str, ...]) -> list[dict[str, object]]:
    return [{"token": token, "present": token in text} for token in tokens]


def assert_playwright_readiness_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    assert_same_origin_evidence_redacted(serialized_evidence, {})
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and len(value) >= 8 and value in serialized_evidence:
            raise ValueError(
                "AE Web Playwright readiness evidence contains "
                f"unredacted environment value: {key}"
            )


def write_readiness_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_playwright_readiness_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def _issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _relative(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return Path(path.name)


def _relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ae_web_playwright_readiness=pass "
            f"dependency={evidence['playwright']['package']} "
            f"mode={evidence['mode']} "
            f"launch={evidence['playwright']['launch_check_default']}"
        )
    return f"ae_web_playwright_readiness=fail issues={len(evidence.get('issues', []))}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AE Web Playwright browser smoke readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    parser.add_argument(
        "--require-installed",
        action="store_true",
        help="Also execute the Node readiness script, requiring installed npm dependencies.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_playwright_readiness(
            require_installed=args.require_installed
        )
        if args.output:
            write_readiness_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except (json.JSONDecodeError, ValueError) as exc:
        print(
            "ae_web_playwright_readiness=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
