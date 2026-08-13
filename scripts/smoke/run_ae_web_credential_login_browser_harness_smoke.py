#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    AE_WEB_URL_ENV,
    EMPLOYEE_ID_ENV,
    OA_DATABASE_URL_ENV,
    PASSWORD_ENV,
    SMOKE_ENV as BOUNDARY_SMOKE_ENV,
    TENANT_ID_ENV,
    assert_boundary_evidence_redacted,
    run_ae_web_credential_login_browser_smoke_boundary,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
NODE_SCRIPT = (
    ROOT_DIR
    / "apps"
    / "nex-ae-web"
    / "scripts"
    / "runCredentialLoginBrowserHarnessSmoke.mjs"
)
SCHEMA_VERSION = "ae_web_credential_login_browser_harness_smoke_runner.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_credential_login_browser_harness_smoke.v1"

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class NodeHarnessExecution:
    status: str
    payload: dict[str, Any] | None = None
    returncode: int | None = None
    error: str | None = None


def run_ae_web_credential_login_browser_harness_smoke(
    environ: dict[str, str] | None = None,
    *,
    node_script: Path = NODE_SCRIPT,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    boundary = run_ae_web_credential_login_browser_smoke_boundary(
        env,
        browser_config=safe_browser_config(),
    )
    if boundary["status"] == "FAIL":
        evidence = build_runner_evidence(
            status="FAIL",
            reason="boundary_invalid",
            boundary=boundary,
            node_execution=NodeHarnessExecution(status="NOT_RUN"),
            node_script=node_script,
        )
        assert_smoke_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
        return evidence

    node_execution = run_node_harness(
        node_script=node_script,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    evidence = build_runner_evidence(
        status="PASS" if node_execution.status == "PASS" else "FAIL",
        reason=None if node_execution.status == "PASS" else node_execution.error,
        boundary=boundary,
        node_execution=node_execution,
        node_script=node_script,
    )
    assert_smoke_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def safe_browser_config() -> dict[str, Any]:
    return {
        "config_schema_version": "ae_web_runtime_config.v1",
        "client_mode": "fetch",
        "ae_base_url": "/ae-api",
        "features": {
            "fetch_clients_enabled": True,
            "document_detail_enabled": True,
            "upload_submit_enabled": True,
            "retrieval_submit_enabled": True,
        },
        "session_route": "/api/v1/auth/session",
        "login_route": "/api/v1/auth/session/login",
        "logout_route": "/api/v1/auth/session/logout",
    }


def run_node_harness(
    *,
    node_script: Path,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15.0,
) -> NodeHarnessExecution:
    try:
        completed = runner(
            ["node", str(node_script)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return NodeHarnessExecution(status="FAIL", error="node_timeout")
    except OSError:
        return NodeHarnessExecution(status="FAIL", error="node_unavailable")

    if completed.returncode != 0:
        return NodeHarnessExecution(
            status="FAIL",
            returncode=completed.returncode,
            error="node_failed",
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return NodeHarnessExecution(
            status="FAIL",
            returncode=completed.returncode,
            error="node_json_invalid",
        )

    if not valid_node_payload(payload):
        return NodeHarnessExecution(
            status="FAIL",
            payload=payload if isinstance(payload, dict) else None,
            returncode=completed.returncode,
            error="node_evidence_invalid",
        )
    return NodeHarnessExecution(
        status="PASS",
        payload=payload,
        returncode=completed.returncode,
    )


def valid_node_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("smoke_schema_version") == NODE_SMOKE_SCHEMA_VERSION
        and payload.get("status") == "PASS"
        and payload.get("runner", {}).get("live_network_used") is False
        and payload.get("harness", {}).get("summary", {}).get("route_guard_status")
        == "allowed"
    )


def build_runner_evidence(
    *,
    status: str,
    reason: str | None,
    boundary: dict[str, Any],
    node_execution: NodeHarnessExecution,
    node_script: Path,
) -> dict[str, Any]:
    node_payload = node_execution.payload or {}
    summary = node_payload.get("harness", {}).get("summary", {})
    checks = node_payload.get("checks", {})
    fetch_calls = node_payload.get("harness", {}).get("fetch_calls", [])
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "boundary": {
            "schema_version": boundary["evidence_schema_version"],
            "status": boundary["status"],
            "activation_env": BOUNDARY_SMOKE_ENV,
            "required_phase_count": len(boundary["required_phases"]),
            "browser_route_count": len(boundary["browser_routes"]),
        },
        "node": {
            "script": node_script_label(node_script),
            "status": node_execution.status,
            "returncode": node_execution.returncode,
            "error": node_execution.error,
        },
        "harness": {
            "node_schema_version": node_payload.get("smoke_schema_version"),
            "mode": node_payload.get("runner", {}).get("mode"),
            "route_guard_status": summary.get("route_guard_status"),
            "fetch_call_count": summary.get("fetch_call_count", 0),
            "login_route": summary.get("login_route"),
            "current_session_status": summary.get("current_session_status"),
            "authenticated_session_status": summary.get(
                "authenticated_session_status"
            ),
            "logout_session_status": summary.get("logout_session_status"),
            "fetch_calls": [
                {
                    "url": call.get("url"),
                    "method": call.get("method"),
                    "credentials": call.get("credentials"),
                    "request_body_redacted": call.get("request_body_redacted"),
                }
                for call in fetch_calls
                if isinstance(call, dict)
            ],
        },
        "checks": {
            "boundary_not_failed": boundary["status"] != "FAIL",
            "node_harness_passed": node_execution.status == "PASS",
            "route_guard_allowed": checks.get("route_guard_allowed") is True,
            "login_body_redacted": checks.get("login_body_redacted") is True,
            "logout_returns_anonymous": checks.get("logout_returns_anonymous") is True,
            "live_network_used": False,
        },
        "redaction": {
            "raw_password_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }


def node_script_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return path.name


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    assert_boundary_evidence_redacted(serialized_evidence, environ)
    for key in [
        AE_WEB_URL_ENV,
        AE_API_BASE_URL_ENV,
        AE_DATABASE_URL_ENV,
        OA_DATABASE_URL_ENV,
        TENANT_ID_ENV,
        EMPLOYEE_ID_ENV,
        PASSWORD_ENV,
    ]:
        value = environ.get(key)
        if value and len(value) >= 8 and value in serialized_evidence:
            raise ValueError(
                "AE Web credential-login browser harness smoke evidence contains "
                f"unredacted environment value: {key}"
            )


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ae_web_credential_login_browser_harness_smoke=pass "
            f"boundary={str(evidence['boundary']['status']).lower()} "
            f"route_guard={evidence['harness']['route_guard_status']} "
            f"fetch_calls={evidence['harness']['fetch_call_count']}"
        )
    return (
        "ae_web_credential_login_browser_harness_smoke=fail "
        f"reason={evidence['reason']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic AE Web credential-login browser harness smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    parser.add_argument(
        "--node-script",
        type=Path,
        default=NODE_SCRIPT,
        help="Path to the AE Web Node harness smoke script.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = subprocess.run,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_web_credential_login_browser_harness_smoke(
            node_script=args.node_script,
            runner=runner,
            timeout_seconds=args.timeout,
        )
        if args.output:
            write_smoke_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except ValueError as exc:
        print(
            "ae_web_credential_login_browser_harness_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
