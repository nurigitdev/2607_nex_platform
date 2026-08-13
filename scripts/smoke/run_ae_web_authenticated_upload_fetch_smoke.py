#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
NODE_SCRIPT = (
    ROOT
    / "apps"
    / "nex-ae-web"
    / "scripts"
    / "runAuthenticatedUploadFetchSmoke.mjs"
)
SCHEMA_VERSION = "ae_web_authenticated_upload_fetch_smoke_runner.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_authenticated_upload_fetch_smoke.v1"

Runner = Callable[..., subprocess.CompletedProcess[str]]

PROTECTED_ENV_KEYS = (
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_OA_TEST_DATABASE_URL",
    "NEX_AE_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_OA_DATABASE_URL",
    "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD",
)


@dataclass(frozen=True)
class NodeExecution:
    status: str
    payload: dict[str, Any] | None = None
    returncode: int | None = None
    error: str | None = None


def run_ae_web_authenticated_upload_fetch_smoke(
    environ: dict[str, str] | None = None,
    *,
    node_script: Path = NODE_SCRIPT,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    node = run_node_smoke(
        node_script=node_script,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    evidence = build_smoke_evidence(node=node, node_script=node_script)
    assert_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def run_node_smoke(
    *,
    node_script: Path,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15.0,
) -> NodeExecution:
    try:
        completed = runner(
            ["node", str(node_script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return NodeExecution(status="FAIL", error="node_timeout")
    except OSError:
        return NodeExecution(status="FAIL", error="node_unavailable")

    if completed.returncode != 0:
        return NodeExecution(
            status="FAIL",
            returncode=completed.returncode,
            error="node_failed",
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return NodeExecution(
            status="FAIL",
            returncode=completed.returncode,
            error="node_json_invalid",
        )
    if not valid_node_payload(payload):
        return NodeExecution(
            status="FAIL",
            payload=payload if isinstance(payload, dict) else None,
            returncode=completed.returncode,
            error="node_evidence_invalid",
        )
    return NodeExecution(status="PASS", payload=payload, returncode=completed.returncode)


def valid_node_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("smoke_schema_version") == NODE_SMOKE_SCHEMA_VERSION
        and payload.get("status") == "PASS"
        and payload.get("runner", {}).get("live_network_used") is False
        and payload.get("runner", {}).get("postgresql_used") is False
        and payload.get("workflow", {}).get("summary", {}).get("checks_passed") is True
        and payload.get("workflow", {}).get("summary", {}).get("route")
        == "/api/v1/uploads"
        and payload.get("request_observations", {}).get("fetch_call_count") == 4
    )


def build_smoke_evidence(*, node: NodeExecution, node_script: Path) -> dict[str, Any]:
    payload = node.payload or {}
    workflow = payload.get("workflow", {})
    summary = workflow.get("summary", {})
    request_observations = payload.get("request_observations", {})
    checks = payload.get("checks", {})
    status = "PASS" if node.status == "PASS" else "FAIL"
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": None if status == "PASS" else node.error,
        "node": {
            "script": node_script_label(node_script),
            "status": node.status,
            "returncode": node.returncode,
            "error": node.error,
        },
        "workflow": {
            "node_schema_version": payload.get("smoke_schema_version"),
            "mode": payload.get("runner", {}).get("mode"),
            "browser_api_path": payload.get("runner", {}).get("browser_api_path"),
            "workflow_schema_version": workflow.get("schema_version"),
            "route": summary.get("route"),
            "upload_status": summary.get("upload_status"),
            "dedupe_status": summary.get("dedupe_status"),
            "owner_scope_source": summary.get("owner_scope_source"),
            "document_id_present": summary.get("document_id_present"),
            "fetch_call_count": request_observations.get("fetch_call_count", 0),
            "upload_body_summary": request_observations.get("upload_body_summary"),
            "routes": request_observations.get("routes", []),
        },
        "checks": {
            "node_smoke_passed": node.status == "PASS",
            "same_origin_sequence_matches": checks.get(
                "same_origin_sequence_matches"
            )
            is True,
            "upload_body_owner_from_session_claims": checks.get(
                "upload_body_owner_from_session_claims"
            )
            is True,
            "upload_body_metadata_only": checks.get("upload_body_metadata_only")
            is True,
            "live_network_not_used": checks.get("live_network_not_used") is True,
        },
        "redaction": {
            "rawPasswordInEvidence": False,
            "rawSourceInEvidence": False,
            "rawTokenInEvidence": False,
            "serviceCredentialInEvidence": False,
            "databaseEndpointInEvidence": False,
            "providerEndpointInEvidence": False,
        },
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test"} and value in serialized_evidence:
            raise ValueError(
                "AE Web authenticated upload fetch smoke evidence contains "
                f"unredacted environment value: {key}"
            )


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ae_web_authenticated_upload_fetch_smoke=pass "
            f"mode={evidence['workflow']['mode']} "
            f"route={evidence['workflow']['route']} "
            f"status={evidence['workflow']['upload_status']} "
            f"fetch_calls={evidence['workflow']['fetch_call_count']}"
        )
    return (
        "ae_web_authenticated_upload_fetch_smoke=fail "
        f"reason={evidence.get('reason')}"
    )


def node_script_label(node_script: Path) -> str:
    try:
        return str(node_script.relative_to(ROOT))
    except ValueError:
        return node_script.name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic AE Web authenticated upload fetch smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_web_authenticated_upload_fetch_smoke()
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
            "ae_web_authenticated_upload_fetch_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
