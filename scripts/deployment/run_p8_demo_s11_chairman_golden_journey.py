#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "services/_shared"),
    str(ROOT / "services/nex-oa"),
    str(ROOT / "scripts/deployment"),
    str(ROOT / "scripts/smoke"),
]

import run_p8_demo_s10_installed_domain_acceptance as installed
import run_p8_demo_s10b_installed_runtime as composed
from nex_oa.credentials import hash_password, password_hash_algorithm
from nex_runtime.demo_database import resolve_demo_database_targets

EXECUTION_ENV = "NEX_P8_DEMO_S11_LIVE"
SCHEMA_VERSION = "p8_demo_s11_chairman_golden_journey.v1"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-s11-chairman-golden-journey.json"
PLAYWRIGHT_RUNNER = (
    ROOT / "apps/nex-ae-web/scripts/runP8DemoS11ChairmanGoldenJourney.mjs"
)
TENANT_ID = "VO00"
REQUESTER_EMPLOYEE_ID = "1001"
APPROVER_EMPLOYEE_ID = "2001"
GOLDEN_PROMPT = (
    "2026-10-23에 PROJECT-A-2 프로젝트의 출장비 84,000원을 일반 전표로 "
    "현금 정산 초안 생성해줘."
)
MODEL_PROFILE = "general-llm-default"
MODEL_REF = "Qwen3.5-4B"


class P8DemoS11Error(RuntimeError):
    pass


def run_p8_demo_s11_chairman_golden_journey(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    protected_runner: Any | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}
    try:
        runner = protected_runner or _execute_protected_acceptance
        protected = dict(runner(env, root=root))
        return {**source, **protected, "executed": True}
    except (OSError, TypeError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "secret_included": False,
            "token_value_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    s10 = installed._source_admission(root)
    if not PLAYWRIGHT_RUNNER.is_file():
        raise P8DemoS11Error("S11 Playwright runner is missing")
    package = json.loads((root / "apps/nex-ae-web/package.json").read_text(encoding="utf-8"))
    if "smoke:p8-demo-s11-chairman-golden-journey" not in package.get("scripts", {}):
        raise P8DemoS11Error("S11 Playwright command is not registered")
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "P8-DEMO-S11",
        "source_admitted": True,
        "installed_prerequisite": s10["source_admitted"],
        "actual_postgres_required": True,
        "actual_openbao_required": True,
        "actual_rustfs_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "embedding_required": False,
        "reranking_required": False,
        "secret_included": False,
        "token_value_included": False,
    }


def _execute_protected_acceptance(env: Mapping[str, str], *, root: Path) -> dict[str, Any]:
    targets = resolve_demo_database_targets(env)
    urls = {target.target.service_id: target.database_url for target in targets}
    engines = {
        service: create_engine(urls[service], poolclass=NullPool)
        for service in ("nex-oa", "nex-ae-api", "nex-wc", "nex-eos")
    }
    requester_password = secrets.token_urlsafe(28)
    approver_password = secrets.token_urlsafe(28)
    sensitive = {requester_password, approver_password, GOLDEN_PROMPT}
    credential_snapshot: list[dict[str, Any]] = []
    live_state: dict[str, Any] = {}
    try:
        composed._cleanup_dynamic_rows(engines, tenant_id=TENANT_ID)
        credential_snapshot = _rotate_demo_credentials(
            engines["nex-oa"],
            passwords={
                REQUESTER_EMPLOYEE_ID: requester_password,
                APPROVER_EMPLOYEE_ID: approver_password,
            },
        )
        fixture = _fixture_visibility(engines)
        if fixture != {
            "active_employee_count": 2,
            "nvt_project_count": 1,
            "project_count": 2,
            "project_membership_count": 2,
            "account_count": 2,
            "organization_unit_count": 4,
        }:
            raise P8DemoS11Error("VO00 installed fixture visibility drift")

        runtime_env = {
            **env,
            "NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON": (
                _semantic_calibration_json()
            ),
        }

        def live_hook(**_: Any) -> Mapping[str, Any]:
            browser = _run_playwright(
                runtime_env,
                requester_password=requester_password,
                approver_password=approver_password,
            )
            runtime = browser.get("runtime")
            if browser.get("status") != "PASS" or not isinstance(runtime, Mapping):
                raise P8DemoS11Error(
                    "installed Chairman browser journey failed at "
                    f"{browser.get('observations', {}).get('stage', 'unknown')}"
                )
            interaction_id = str(runtime.get("interaction_id") or "")
            if not interaction_id:
                raise P8DemoS11Error("installed browser journey omitted interaction lineage")
            database = _database_acceptance_projection(
                engines,
                interaction_id=interaction_id,
            )
            checks = {
                "fixture_visible": fixture["active_employee_count"] == 2,
                "playwright_passed": browser["status"] == "PASS",
                "one_agent_result": database["agent_result_count"] == 1,
                "one_result_delivery": database["result_delivery_count"] == 1,
                "delivery_acknowledged": database["acknowledged_delivery_count"] == 1,
                "execution_succeeded": database["execution_state"] == "SUCCEEDED",
                "execution_finalized": database["execution_phase"] == "FINALIZE",
                "one_approval_decision": database["approval_decision_count"] == 1,
                "one_business_operation": database["business_operation_count"] == 1,
                "one_voucher": database["voucher_count"] == 1,
                "balanced_voucher_lines": database["voucher_line_count"] == 2,
            }
            if not all(checks.values()):
                raise P8DemoS11Error("installed Chairman database invariants failed")
            live_state.update(
                interaction_id=interaction_id,
                result_hash=str(runtime["result_projection"]["result"]["result_hash"]),
                business_refs=tuple(runtime["result_projection"]["result"]["business_refs"]),
            )
            return {
                "status": "PASS",
                "actual_postgres": True,
                "actual_remote_generation": True,
                "actual_playwright": True,
                "provider_model_profile": MODEL_PROFILE,
                "provider_model_ref": MODEL_REF,
                "fixture_visibility": fixture,
                "browser": _public_browser_evidence(browser),
                "database": database,
                "checks": checks,
                "secret_included": False,
            }

        def post_restart_hook(**_: Any) -> Mapping[str, Any]:
            interaction_id = str(live_state.get("interaction_id") or "")
            if not interaction_id:
                raise P8DemoS11Error("post-restart acceptance has no interaction lineage")
            recovered = _run_playwright(
                runtime_env,
                requester_password=requester_password,
                approver_password=approver_password,
                recovery_interaction_id=interaction_id,
            )
            runtime = recovered.get("runtime")
            projection = runtime.get("result_projection") if isinstance(runtime, Mapping) else None
            database = _database_acceptance_projection(
                engines,
                interaction_id=interaction_id,
            )
            checks = {
                "browser_recovery_passed": recovered.get("status") == "PASS",
                "result_hash_stable": (
                    isinstance(projection, Mapping)
                    and projection.get("result", {}).get("result_hash")
                    == live_state["result_hash"]
                ),
                "business_refs_stable": (
                    isinstance(projection, Mapping)
                    and tuple(projection.get("result", {}).get("business_refs") or ())
                    == live_state["business_refs"]
                ),
                "one_agent_result_after_restart": database["agent_result_count"] == 1,
                "one_delivery_after_restart": database["result_delivery_count"] == 1,
                "one_business_operation_after_restart": (
                    database["business_operation_count"] == 1
                ),
                "one_voucher_after_restart": database["voucher_count"] == 1,
            }
            return {
                "status": "PASS" if all(checks.values()) else "FAIL",
                "actual_playwright": True,
                "authoritative_recovery": True,
                "browser": _public_browser_evidence(recovered),
                "database": database,
                "checks": checks,
                "secret_included": False,
            }

        installed_result = installed._execute_protected_acceptance(
            runtime_env,
            root=root,
            image_report_path=installed.DEFAULT_IMAGE_REPORT,
            ae_image_report_path=installed.DEFAULT_AE_IMAGE_REPORT,
            additional_services=("nex-mo", "nex-ae-web"),
            live_hook=live_hook,
            restart_services=("nex-ae-api", *installed.DEMO_DOMAIN_PROCESSES),
            post_restart_hook=post_restart_hook,
        )
        result = {
            **installed_result,
            "provider_contacted": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "fixture_visibility": fixture,
        }
        installed._assert_redacted(result, sensitive)
        return result
    finally:
        try:
            try:
                composed._cleanup_dynamic_rows(engines, tenant_id=TENANT_ID)
                _delete_demo_sessions(engines["nex-oa"])
                _assert_zero_journey_residue(engines)
            finally:
                if credential_snapshot:
                    _restore_demo_credentials(
                        engines["nex-oa"], credential_snapshot
                    )
        finally:
            for engine in engines.values():
                engine.dispose()


def _run_playwright(
    env: Mapping[str, str],
    *,
    requester_password: str,
    approver_password: str,
    recovery_interaction_id: str | None = None,
) -> dict[str, Any]:
    child_env = {
        **env,
        "NEX_P8_DEMO_S11_WEB_URL": "https://ae.nex-staging.test:8443",
        "NEX_P8_DEMO_S11_TENANT_ID": TENANT_ID,
        "NEX_P8_DEMO_S11_REQUESTER_EMPLOYEE_ID": REQUESTER_EMPLOYEE_ID,
        "NEX_P8_DEMO_S11_REQUESTER_PASSWORD": requester_password,
        "NEX_P8_DEMO_S11_APPROVER_EMPLOYEE_ID": APPROVER_EMPLOYEE_ID,
        "NEX_P8_DEMO_S11_APPROVER_PASSWORD": approver_password,
        "NEX_P8_DEMO_S11_PROMPT": GOLDEN_PROMPT,
        "NEX_P8_DEMO_S11_TIMEOUT_MS": "300000",
        "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE": env.get(
            "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/usr/bin/google-chrome"
        ),
    }
    arguments = ["node", str(PLAYWRIGHT_RUNNER)]
    if recovery_interaction_id is not None:
        child_env["NEX_P8_DEMO_S11_RECOVERY_INTERACTION_ID"] = recovery_interaction_id
        arguments.append("--recovery")
    completed = subprocess.run(
        arguments,
        cwd=ROOT / "apps/nex-ae-web",
        env=child_env,
        capture_output=True,
        text=True,
        timeout=360,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        evidence = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise P8DemoS11Error("S11 Playwright output is invalid") from exc
    if completed.returncode != 0 or evidence.get("status") != "PASS":
        return dict(evidence)
    return dict(evidence)


def _public_browser_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evidence.items() if key != "runtime"}


def _semantic_calibration_json() -> str:
    policies = [
        {
            "semantic_stage": stage,
            "policy_ref": f"semantic-admission://{stage.lower()}/p8-demo-s11/v1",
            "policy_version": "p8-demo-s11-v1",
            "model_profile": MODEL_PROFILE,
            "model_ref": MODEL_REF,
            "minimum_confidence": 0.5,
            "golden_evidence_ref": f"acceptance://p8-demo-s11/{stage.lower()}/golden",
            "adversarial_evidence_ref": (
                f"acceptance://p8-demo-s11/{stage.lower()}/adversarial"
            ),
        }
        for stage in ("INTENT", "CONTEXT", "PLAN")
    ]
    return json.dumps(policies, separators=(",", ":"), sort_keys=True)


def _rotate_demo_credentials(
    engine: Any, *, passwords: Mapping[str, str]
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    with engine.begin() as connection:
        for employee_id, password in passwords.items():
            row = connection.execute(
                text(
                    "SELECT credential_id, password_hash, password_hash_algorithm, "
                    "status, failed_attempt_count, locked_at, password_changed_at, "
                    "updated_at FROM oa_local_credentials "
                    "WHERE tenant_id=:tenant AND normalized_employee_id=:employee"
                ),
                {"tenant": TENANT_ID, "employee": employee_id.lower()},
            ).mappings().one_or_none()
            if row is None:
                raise P8DemoS11Error("Demo employee credential is missing")
            snapshots.append(dict(row))
            password_hash = hash_password(password)
            connection.execute(
                text(
                    "UPDATE oa_local_credentials SET password_hash=:password_hash, "
                    "password_hash_algorithm=:algorithm, status='ACTIVE', "
                    "failed_attempt_count=0, locked_at=NULL, password_changed_at=now(), "
                    "updated_at=now() WHERE credential_id=:credential_id"
                ),
                {
                    "credential_id": row["credential_id"],
                    "password_hash": password_hash,
                    "algorithm": password_hash_algorithm(password_hash),
                },
            )
    return snapshots


def _restore_demo_credentials(engine: Any, snapshots: list[dict[str, Any]]) -> None:
    with engine.begin() as connection:
        for snapshot in snapshots:
            connection.execute(
                text(
                    "UPDATE oa_local_credentials SET password_hash=:password_hash, "
                    "password_hash_algorithm=:password_hash_algorithm, status=:status, "
                    "failed_attempt_count=:failed_attempt_count, locked_at=:locked_at, "
                    "password_changed_at=:password_changed_at, updated_at=:updated_at "
                    "WHERE credential_id=:credential_id"
                ),
                snapshot,
            )


def _delete_demo_sessions(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM oa_user_sessions WHERE tenant_id=:tenant "
                "AND subject_id IN ('employee-1001', 'employee-2001')"
            ),
            {"tenant": TENANT_ID},
        )


def _fixture_visibility(engines: Mapping[str, Any]) -> dict[str, int]:
    with engines["nex-oa"].connect() as connection:
        employees = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM oa_local_credentials "
                    "WHERE tenant_id=:tenant AND status='ACTIVE'"
                ),
                {"tenant": TENANT_ID},
            ).scalar_one()
        )
    with engines["nex-eos"].connect() as connection:
        row = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM eos_nvt_project WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_project WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_project_member WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_account WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_org_unit WHERE tenant_id=:tenant)"
            ),
            {"tenant": TENANT_ID},
        ).one()
    return {
        "active_employee_count": employees,
        "nvt_project_count": int(row[0]),
        "project_count": int(row[1]),
        "project_membership_count": int(row[2]),
        "account_count": int(row[3]),
        "organization_unit_count": int(row[4]),
    }


def _database_acceptance_projection(
    engines: Mapping[str, Any], *, interaction_id: str
) -> dict[str, Any]:
    with engines["nex-ae-api"].connect() as connection:
        row = connection.execute(
            text(
                "SELECT execution.state, execution.phase, "
                "(SELECT count(*) FROM ae_agent_result result "
                " WHERE result.tenant_id=execution.tenant_id "
                " AND result.agent_execution_id=execution.agent_execution_id), "
                "(SELECT count(*) FROM ae_result_delivery delivery "
                " WHERE delivery.tenant_id=execution.tenant_id "
                " AND delivery.agent_execution_id=execution.agent_execution_id), "
                "(SELECT count(*) FROM ae_result_delivery delivery "
                " WHERE delivery.tenant_id=execution.tenant_id "
                " AND delivery.agent_execution_id=execution.agent_execution_id "
                " AND delivery.state='ACKNOWLEDGED') "
                "FROM ae_agent_execution execution WHERE execution.tenant_id=:tenant "
                "AND execution.legacy_interaction_id=:interaction"
            ),
            {"tenant": TENANT_ID, "interaction": interaction_id},
        ).one()
    with engines["nex-wc"].connect() as connection:
        approval_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM wc_approval_decision "
                    "WHERE tenant_id=:tenant AND decision='APPROVE'"
                ),
                {"tenant": TENANT_ID},
            ).scalar_one()
        )
    with engines["nex-eos"].connect() as connection:
        eos = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM eos_business_operation WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_voucher_draft WHERE tenant_id=:tenant), "
                "(SELECT count(*) FROM eos_voucher_draft_line WHERE tenant_id=:tenant)"
            ),
            {"tenant": TENANT_ID},
        ).one()
    return {
        "execution_state": str(row[0]),
        "execution_phase": str(row[1]),
        "agent_result_count": int(row[2]),
        "result_delivery_count": int(row[3]),
        "acknowledged_delivery_count": int(row[4]),
        "approval_decision_count": approval_count,
        "business_operation_count": int(eos[0]),
        "voucher_count": int(eos[1]),
        "voucher_line_count": int(eos[2]),
    }


def _assert_zero_journey_residue(engines: Mapping[str, Any]) -> None:
    with engines["nex-ae-api"].connect() as connection:
        ae_count = int(
            connection.execute(
                text("SELECT count(*) FROM ae_agent_execution WHERE tenant_id=:tenant"),
                {"tenant": TENANT_ID},
            ).scalar_one()
        )
    with engines["nex-wc"].connect() as connection:
        wc_count = int(
            connection.execute(
                text("SELECT count(*) FROM wc_approval_work_item WHERE tenant_id=:tenant"),
                {"tenant": TENANT_ID},
            ).scalar_one()
        )
    with engines["nex-eos"].connect() as connection:
        eos_count = int(
            connection.execute(
                text("SELECT count(*) FROM eos_business_operation WHERE tenant_id=:tenant"),
                {"tenant": TENANT_ID},
            ).scalar_one()
        )
    if (ae_count or wc_count or eos_count):
        raise P8DemoS11Error("S11 protected journey cleanup left durable residue")


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "p8_demo_s11_chairman_golden_journey="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(evidence.get('executed'))).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_generation'))).lower()} "
        f"playwright={str(bool(evidence.get('actual_playwright'))).lower()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P8-DEMO-S11 protected journey")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    evidence = run_p8_demo_s11_chairman_golden_journey(execute=args.execute)
    installed._write_report(args.report, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
