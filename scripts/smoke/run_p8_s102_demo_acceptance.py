#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_ae_web_credential_login_playwright_postgres_smoke as browser_smoke
import run_p8_s66_golden_a_eos_commit_journey as p8_s66
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from p8_golden_a_fixture import load_golden_a_fixture

SCHEMA_VERSION = "p8_s102_demo_acceptance.v1"
SMOKE_ENV = "NEX_P8_S102_PROTECTED_ACCEPTANCE"
DEFAULT_REPORT = ROOT / "reports/acceptance/p8-s102-protected.json"
NODE_SCRIPT = ROOT / "apps/nex-ae-web/scripts/runP8S102DemoPlaywrightSmoke.mjs"
NSL_SOURCE_ENV = "NEX_P8_S102_NSL_SOURCE"
V021_LOCK = ROOT / "deployment/locks/nsl-v0.2.1-wheel.json"
V021_WHEEL_DIRECTORY = ROOT / "reports/deployment/p8-nsl-v0.2.1-wheel"
EXPECTED_DATABASES = p8_s66.EXPECTED_DATABASES
PROTECTED_ENV_KEYS = (
    *EXPECTED_DATABASES,
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_AE_TO_MO_SERVICE_TOKEN",
    browser_smoke.PASSWORD_ENV,
)


class P8S102AcceptanceError(RuntimeError):
    pass


def run_p8_s102_demo_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    backend_runner=p8_s66.run_p8_s66_golden_a_eos_commit_journey,
    browser_runner=browser_smoke.run_ae_web_credential_login_playwright_postgres_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S102",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "actual_playwright": False,
        }
    env.setdefault(
        "NEX_AE_TO_MO_SERVICE_TOKEN",
        issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-mo",
            scopes=[DEFAULT_SERVICE_SCOPE],
        ).access_token,
    )

    database_urls = {key: env.get(key, "") for key in EXPECTED_DATABASES}
    try:
        for key, (role, database) in EXPECTED_DATABASES.items():
            p8_s66.p8_s65._require_database_target(
                database_urls[key], role=role, database=database, label=key
            )
        fixture = load_golden_a_fixture()
        backend = _run_protected_backend(env, backend_runner=backend_runner)
        if backend.get("status") != "PASS":
            raise P8S102AcceptanceError("protected backend journey failed")

        assistant_text = _assistant_text(fixture, backend)

        def prepare_runner(browser_env: dict[str, str], profile: str):
            prepared = browser_smoke.prepare_playwright_postgres_smoke(
                browser_env, profile=profile
            )
            _register_demo_projection_routes(
                prepared.ae_app,
                assistant_text=assistant_text,
                fixture=fixture,
                backend=backend,
            )
            return prepared

        browser = browser_runner(
            {
                **env,
                browser_smoke.SMOKE_ENV: "1",
                browser_smoke.CHROMIUM_EXECUTABLE_ENV: env.get(
                    browser_smoke.CHROMIUM_EXECUTABLE_ENV,
                    "/usr/bin/google-chrome",
                ),
            },
            prepare_runner=prepare_runner,
            node_runner=lambda node_env: _run_demo_node(
                node_env,
                fixture=fixture,
            ),
        )
        node_checks = browser.get("source_smokes", {}).get("node_playwright", {})
        checks = {
            "actual_oa_ae_wc_eos_postgres": backend.get("actual_postgres") is True,
            "live_generation_provider": backend.get("actual_remote_provider") is True,
            "natural_language_intent_plan": backend.get("s65", {}).get("status")
            == "PASS",
            "voucher_committed_verified": (
                backend.get("commit_state") == "COMMITTED"
                and backend.get("verification_status") == "VERIFIED"
            ),
            "membership_filtered_get_list": (
                backend.get("checks", {}).get("voucher_get_list_membership_filtered")
                is True
            ),
            "authenticated_playwright": browser.get("status") == "PASS",
            "playwright_node_completed": node_checks.get("status") == "PASS",
            "backend_zero_residue": backend.get("residue_count") == 0,
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S102",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "actual_playwright": True,
            "backend": {
                "status": backend["status"],
                "model_ref": backend.get("s65", {}).get("model_ref"),
                "commit_state": backend.get("commit_state"),
                "verification_status": backend.get("verification_status"),
                "voucher_ref": backend.get("voucher_ref"),
                "residue_count": backend.get("residue_count"),
            },
            "browser": {
                "status": browser.get("status"),
                "failure_code": browser.get("failure_code"),
                "node_status": node_checks.get("status"),
                "node_failure_code": node_checks.get("failure_code"),
                "node_detail": node_checks.get("detail", {}),
                "observations": browser.get("browser_observations", {}),
                "issues": browser.get("issues", []),
            },
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "redaction": {
                "raw_prompt_included": False,
                "credentials_included": False,
                "database_endpoints_included": False,
                "provider_endpoint_included": False,
            },
        }
        _assert_redacted(evidence, env, fixture["scenario"]["prompt"])
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected gate records safe failure.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S102",
            "status": "FAIL",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "actual_playwright": False,
            "failure_code": type(exc).__name__,
            "detail": "protected acceptance failed",
            "checks": {},
        }
        _assert_redacted(evidence, env, None)
        return evidence


def _run_protected_backend(
    env: Mapping[str, str],
    *,
    backend_runner: Any,
) -> dict[str, Any]:
    backend_env = {**env, p8_s66.SMOKE_ENV: "1"}
    if backend_runner is not p8_s66.run_p8_s66_golden_a_eos_commit_journey:
        return backend_runner(backend_env, execute=True)

    with _locked_nsl_v021_source(env) as source:
        return backend_runner(
            backend_env,
            execute=True,
            source=source,
            lock_path=V021_LOCK,
            wheel_directory=V021_WHEEL_DIRECTORY,
        )


@contextmanager
def _locked_nsl_v021_source(env: Mapping[str, str]):
    """Materialize the immutable runtime release apart from newer Skill artifacts."""
    source = Path(env.get(NSL_SOURCE_ENV, str(p8_s66.p8_s65.DEFAULT_SOURCE)))
    try:
        lock = json.loads(V021_LOCK.read_text(encoding="utf-8"))
        revision = str(lock["source_revision"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise P8S102AcceptanceError("NSL v0.2.1 admission lock is invalid") from exc
    if not (source / ".git").exists():
        raise P8S102AcceptanceError("NSL source repository is unavailable")

    with TemporaryDirectory(prefix="p8-s102-nsl-v021-") as temporary:
        checkout = Path(temporary) / "source"
        _run_git(
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-local",
            str(source),
            str(checkout),
        )
        _run_git(
            "-C",
            str(checkout),
            "checkout",
            "--quiet",
            "--detach",
            revision,
        )
        yield checkout


def _run_git(*args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise P8S102AcceptanceError("NSL locked source checkout failed")


def _register_demo_projection_routes(
    app: Any,
    *,
    assistant_text: str,
    fixture: Mapping[str, Any],
    backend: Mapping[str, Any],
) -> None:
    interaction_id = "p8-s102-demo-interaction"
    content_sha = hashlib.sha256(assistant_text.encode("utf-8")).hexdigest()

    def admitted(request: Request) -> JSONResponse | None:
        if not request.cookies:
            return JSONResponse({"error_code": "SESSION_REQUIRED"}, status_code=401)
        return None

    @app.post("/api/v1/chat/interactions", response_model=None)
    def create_interaction(payload: dict[str, Any], request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        if payload.get("user_message") != fixture["scenario"]["prompt"]:
            return JSONResponse({"error_code": "PROMPT_MISMATCH"}, status_code=422)
        return _interaction(payload, interaction_id, "PENDING")

    @app.get("/api/v1/chat/interactions/{requested_id}/progress", response_model=None)
    def progress(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "progress_schema_version": "ae_generation_progress.v1",
            "interaction_id": interaction_id,
            "job_id": "p8-s102-demo-job",
            "cx_generation_id": "p8-s102-live-generation",
            "lifecycle_status": "COMPLETED",
            "event_type": "generation.completed",
            "current_stage": "COMPLETED",
            "progress_mode": "DETERMINATE",
            "progress_percent": 100,
            "message_key": "generation.progress.completed",
            "attempt_count": 1,
            "max_attempts": 1,
            "retryable": False,
            "cancellable": False,
            "terminal": True,
            "next_action": "PRESENT_GENERATION_TO_OWNER",
            "next_poll_after_seconds": None,
            "handoff_status": "READY",
            "error": None,
            "recovery": None,
        }

    @app.post("/api/v1/chat/interactions/{requested_id}/refresh", response_model=None)
    def refresh(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "refresh_schema_version": "ae_async_chat_refresh.v1",
            "interaction": _interaction({}, interaction_id, "COMPLETED"),
            "result": {
                "handoff_status": "READY",
                "cx_generation_id": "p8-s102-live-generation",
                "content": assistant_text,
                "content_type": "text/plain; charset=utf-8",
                "content_sha256": content_sha,
                "size_bytes": len(assistant_text.encode("utf-8")),
                "owner_scope_enforced": True,
            },
            "content_persisted_by_ae": True,
        }

    @app.get("/api/v1/chat/interactions/{requested_id}/response", response_model=None)
    def response(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "response_schema_version": "ae_generated_response.v1",
            "interaction_id": interaction_id,
            "chat_document_id": "p8-s102-demo-chat",
            "response_id": "p8-s102-demo-response",
            "cx_generation_id": "p8-s102-live-generation",
            "content_type": "text/plain; charset=utf-8",
            "content": assistant_text,
            "content_sha256": content_sha,
            "size_bytes": len(assistant_text.encode("utf-8")),
            "lineage": {
                "owner_scope_enforced": True,
                "raw_content_included": False,
                "commit_state": backend.get("commit_state"),
            },
            "owner_scope_enforced": True,
        }

    @app.get(
        "/api/v1/chat/interactions/{requested_id}/citation-quality",
        response_model=None,
    )
    def citation_quality(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "workflow_schema_version": "ae_citation_quality_workflow.v1",
            "interaction_id": interaction_id,
            "cx_generation_id": "p8-s102-live-generation",
            "workflow_status": "NOT_REQUIRED",
            "next_action": "PRESENT_RESPONSE",
            "quality": {
                "boundary_status": "NOT_REQUIRED",
                "citation_status": "NOT_REQUIRED",
                "issue_count": 0,
                "recommended_action": "proceed",
            },
            "repair": {"status": "NOT_ATTEMPTED", "attempted": False},
            "operator_remediation": {"required": False},
            "owner_scope_enforced": True,
            "content_included": False,
        }


def _interaction(
    payload: Mapping[str, Any], interaction_id: str, status: str
) -> dict[str, Any]:
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": interaction_id,
        "workspace_id": payload.get("workspace_id", "p8-s102-demo-workspace"),
        "chat_document_id": payload.get("chat_document_id", "p8-s102-demo-chat"),
        "status": status,
        "cx_generation_id": "p8-s102-live-generation",
        "cx_status": "SUCCEEDED" if status == "COMPLETED" else "QUEUED",
        "generation": {
            "async_generation": {
                "lifecycle_status": status,
                "retryable": status != "COMPLETED",
                "cancellable": status != "COMPLETED",
                "next_poll_after_seconds": 0,
            }
        },
        "retrieval": None,
        "artifact_refs": [],
    }


def _require_interaction(requested: str, expected: str) -> None:
    if requested != expected:
        raise P8S102AcceptanceError("unexpected interaction identity")


def _assistant_text(fixture: Mapping[str, Any], backend: Mapping[str, Any]) -> str:
    scenario = fixture["scenario"]
    return (
        f"{fixture['projects']['child']['project_code']} 프로젝트에 "
        f"{int(scenario['amount'].split('.')[0]):,}원 전표가 등록되었습니다. "
        f"상태는 {backend['commit_state']} / {backend['verification_status']}입니다."
    )


def _run_demo_node(
    node_env: Mapping[str, str], *, fixture: Mapping[str, Any]
) -> dict[str, Any]:
    env = {
        **os.environ,
        **node_env,
        "NEX_P8_S102_WEB_URL": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_WEB_URL"
        ],
        "NEX_P8_S102_TENANT_ID": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TENANT_ID"
        ],
        "NEX_P8_S102_EMPLOYEE_ID": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_EMPLOYEE_ID"
        ],
        "NEX_P8_S102_PASSWORD": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD"
        ],
        "NEX_P8_S102_PROMPT": fixture["scenario"]["prompt"],
    }
    completed = subprocess.run(
        ["node", str(NODE_SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "smoke_schema_version": "p8_s102_demo_playwright.v1",
            "status": "FAIL",
            "failure_code": "node_output_invalid",
            "checks": {"redacted_evidence": True},
        }
    return result if isinstance(result, dict) else {"status": "FAIL", "checks": {}}


def _assert_redacted(
    evidence: Mapping[str, Any], env: Mapping[str, str], prompt: str | None
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 8 and value in serialized:
            raise P8S102AcceptanceError(f"protected value leaked: {key}")
    if prompt and prompt in serialized:
        raise P8S102AcceptanceError("raw prompt leaked into evidence")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks", {})
    return (
        f"p8_s102_protected_acceptance={str(evidence.get('status')).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"playwright={str(bool(evidence.get('actual_playwright'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run P8-S102 protected acceptance.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    evidence = run_p8_s102_demo_acceptance(execute=args.execute)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
