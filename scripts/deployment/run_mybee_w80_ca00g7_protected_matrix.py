#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for relative in ("services/_shared", "services/nex-ae-api", "scripts/deployment"):
    sys.path.insert(0, str(ROOT / relative))

import run_canonical_platform_installed_acceptance as installed
import run_mybee_w70_cp_m1_product_golden_journey as m1_acceptance
from mybee_m1_product_acceptance_support import (
    W80_CA00G7_BUSINESS_POSITION_TYPES,
    baseline_digest,
    load_acceptance_baseline,
    seed_acceptance_authority,
    seed_w80_ca00g7_approval_matrix,
    wait_for_installed_authority,
)
from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING
from nex_runtime.current_platform_installation import CURRENT_JOURNEY_WORKERS
from nex_runtime.database import sqlalchemy_database_url

EXECUTION_ENV = "NEX_MYBEE_W80_CA00G7_LIVE"
SCHEMA_VERSION = "mybee_w80_ca00g7_protected_matrix_runner.v1"
DEFAULT_REPORT = ROOT / "reports/deployment/mybee-w80-ca00g7-protected-matrix.json"
DEFAULT_BROWSER_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00g7-browser-evidence.json"
)
DEFAULT_RESTART_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00g7-restart-evidence.json"
)
DEFAULT_COMPOSE_DIAGNOSTIC_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00g7-compose-diagnostics.json"
)
DEFAULT_COMPOSE_LOG_DIR = (
    ROOT / "reports/deployment/mybee-w80-ca00g7-compose-log-tail"
)
PLAYWRIGHT_RUNNER = (
    ROOT / "apps/nex-ae-web/scripts/runMyBeeW80Ca00G7ProtectedMatrix.mjs"
)
SCREENSHOT_DIR = ROOT / "reports/deployment/mybee-w80-ca00g7-screens"
PROCESS_TIMEOUT_SECONDS = 5_400
VOUCHER_INITIAL_REVISION_OUTCOMES = frozenset(
    {"ENVELOPE_ONLY", "JOURNAL_SUCCESS", "ACCOUNTING_CORRECTION"}
)
VOUCHER_REVIEW_REVISION_OUTCOMES = frozenset(
    {"JOURNAL_SUCCESS", "ACCOUNTING_CORRECTION"}
)


class ProtectedMatrixError(RuntimeError):
    pass


def run_protected_matrix(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}
    try:
        return {**source, **_execute(env, root=root), "executed": True}
    except Exception as exc:  # noqa: BLE001 - bounded acceptance failure receipt
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "secret_included": False,
            "raw_prompt_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    installed_source = installed._source_admission(root)
    if not PLAYWRIGHT_RUNNER.is_file():
        raise ProtectedMatrixError("W80 CA00G7 Playwright runner is missing")
    package = json.loads((root / "apps/nex-ae-web/package.json").read_text())
    command = "smoke:mybee-w80-ca00g7-protected-matrix"
    if command not in package.get("scripts", {}):
        raise ProtectedMatrixError("W80 CA00G7 Playwright command is not registered")
    source = PLAYWRIGHT_RUNNER.read_text(encoding="utf-8")
    required_markers = (
        "WAITING_VOUCHER_REVIEW",
        "ACCOUNTING_CORRECTION",
        "MIDDLE_REJECTION",
        "FINAL_REJECTION",
        "decision_replay_statuses",
    )
    missing = [marker for marker in required_markers if marker not in source]
    if missing:
        raise ProtectedMatrixError("W80 CA00G7 runner contract markers are missing")
    baseline = load_acceptance_baseline()
    forbidden = {
        str(baseline["tenant"]["tenant_id"]),
        *(str(item["project_code"]) for item in baseline["projects"]),
    }
    residue = sorted(
        str(path.relative_to(root))
        for product_root in (root / "services/nex-ae-api", root / "domains/mybee")
        for path in product_root.rglob("*.py")
        if any(value in path.read_text(encoding="utf-8") for value in forbidden)
    )
    if residue:
        raise ProtectedMatrixError("acceptance identity leaked into product runtime")
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "W80-CA00G.7",
        "source_admitted": True,
        "installed_prerequisite": installed_source["source_admitted"],
        "baseline_digest": baseline_digest(baseline),
        "journey_count": 6,
        "actual_postgres_required": True,
        "actual_openbao_required": True,
        "actual_rustfs_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "restart_replay_required": True,
        "repository_full_gate_required": True,
        "scenario_product_residue": residue,
        "secret_included": False,
        "raw_prompt_included": False,
    }


def _execute(env: Mapping[str, str], *, root: Path) -> dict[str, Any]:
    baseline = load_acceptance_baseline()
    requester_password = secrets.token_urlsafe(28)
    business_password = secrets.token_urlsafe(28)
    accounting_password = secrets.token_urlsafe(28)
    session_id = (
        "mybee-w80-ca00g7-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(4)
    )
    scenarios = _scenario_matrix(baseline)
    runtime_env = {
        **env,
        "NEX_AE_WEB_TENANT_ID": str(baseline["tenant"]["tenant_id"]),
        "NEX_DIAGNOSTIC_EVIDENCE_MODE": "LIVE_JOURNEY",
        "NEX_DIAGNOSTIC_EVIDENCE_SESSION_ID": session_id,
        "NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "true",
        "NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS": "7",
        "NEX_CANONICAL_PLATFORM_SEMANTIC_CALIBRATION_POLICIES_JSON": (
            m1_acceptance._semantic_calibration_json(
                model_ref=CANONICAL_GENERATION_BINDING.model_revision
            )
        ),
    }
    runtime_env, isolation = m1_acceptance._prepare_isolated_database_environment(
        runtime_env
    )
    screenshot_dir = Path(
        env.get("NEX_MYBEE_W80_CA00G7_SCREENSHOT_DIR") or SCREENSHOT_DIR
    )
    screenshot_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state: dict[str, Any] = {}

    def live_hook(**values: Any) -> Mapping[str, Any]:
        urls = dict(values["urls"])
        seed = seed_acceptance_authority(
            urls,
            requester_password=requester_password,
            business_approver_password=business_password,
            accounting_approver_password=accounting_password,
            baseline=baseline,
            business_approver_position_types=W80_CA00G7_BUSINESS_POSITION_TYPES,
        )
        matrix_seed = seed_w80_ca00g7_approval_matrix(urls, baseline=baseline)
        synchronized = wait_for_installed_authority(
            urls,
            tenant_id=str(baseline["tenant"]["tenant_id"]),
            expected_project_count=len(baseline["projects"]),
        )
        browser = _run_browser(
            runtime_env,
            baseline=baseline,
            scenarios=scenarios,
            passwords={
                "requester": requester_password,
                "business_approver": business_password,
                "accounting_approver": accounting_password,
            },
            screenshot_dir=screenshot_dir,
        )
        installed._write_report(DEFAULT_BROWSER_REPORT, browser)
        if browser.get("status") != "PASS":
            raise ProtectedMatrixError(
                "W80 CA00G7 Playwright matrix failed: "
                f"{browser.get('failure_code')}:{browser.get('failure_detail')}"
            )
        database = _database_projection(
            urls, tenant_id=str(baseline["tenant"]["tenant_id"])
        )
        checks = _database_checks(database, browser)
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise ProtectedMatrixError(
                "W80 CA00G7 database invariants failed: " + ",".join(failed)
            )
        state.update(database=database, browser=browser)
        return {
            "status": "PASS",
            "authority_seed": seed,
            "approval_matrix_seed": matrix_seed,
            "authority_synchronization": synchronized,
            "browser": browser,
            "database": database,
            "checks": checks,
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "provider_model_ref": CANONICAL_GENERATION_BINDING.model_name,
            "provider_model_revision": CANONICAL_GENERATION_BINDING.model_revision,
            "provider_deployment_id": CANONICAL_GENERATION_BINDING.deployment_id,
            "secret_included": False,
            "raw_prompt_included": False,
        }

    def post_restart_hook(**values: Any) -> Mapping[str, Any]:
        current = _database_projection(
            dict(values["urls"]), tenant_id=str(baseline["tenant"]["tenant_id"])
        )
        checks = {
            "proposal_count_stable": current["proposal_count"]
            == state["database"]["proposal_count"],
            "voucher_count_stable": current["voucher_count"]
            == state["database"]["voucher_count"],
            "journal_count_stable": current["journal_count"]
            == state["database"]["journal_count"],
            "one_pending_wait_per_authority": current[
                "duplicate_pending_authority_count"
            ]
            == 0,
        }
        if not all(checks.values()):
            raise ProtectedMatrixError("W80 CA00G7 restart invariants failed")
        receipt = {"status": "PASS", "database": current, "checks": checks}
        installed._write_report(DEFAULT_RESTART_REPORT, receipt)
        return receipt

    def finalization_hook(**values: Any) -> Mapping[str, Any]:
        compose_diagnostics = {}
        DEFAULT_COMPOSE_LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        DEFAULT_COMPOSE_LOG_DIR.chmod(0o700)
        for service_id in ("nex-ae-api", "nex-wc", "nex-eos"):
            completed = installed._compose(
                values["runtime_env"],
                root=values["root"],
                arguments=("logs", "--no-color", "--tail", "160", service_id),
                check=False,
            )
            compose_diagnostics[service_id] = installed._structured_process_failure(
                completed.stdout
            )
            log_path = DEFAULT_COMPOSE_LOG_DIR / f"{service_id}.log"
            log_path.write_text(completed.stdout, encoding="utf-8")
            log_path.chmod(0o600)
        installed._write_report(
            DEFAULT_COMPOSE_DIAGNOSTIC_REPORT,
            {
                "schema_version": "mybee_w80_ca00g7_compose_diagnostics.v1",
                "services": compose_diagnostics,
                "secret_included": False,
                "raw_prompt_included": False,
            },
        )
        return m1_acceptance._collect_live_journey_diagnostics(
            values["runtime_env"],
            root=values["root"],
            session_id=session_id,
            forbidden_values={
                requester_password,
                business_password,
                accounting_password,
            },
            screen_source_root=screenshot_dir,
            screen_manifest_names=tuple(
                f"mybee-m1-w80-ca00g7-{item['scenario_id']}-screen-manifest.json"
                for item in scenarios
            ),
            screen_required_state_counts={
                "PROPOSAL_SUBMITTED": 6,
                "BUSINESS_PROPOSAL_APPROVED": 2,
                "BUSINESS_PROPOSAL_REJECTED": 2,
                "VOUCHER_SUBMITTED": 2,
                "VOUCHER_CORRECTION_SUBMITTED": 1,
                "RESULT_RENDERED": 2,
            },
        )

    execution_error: Exception | None = None
    result: dict[str, Any] | None = None
    try:
        result = dict(
            installed.execute_canonical_platform_acceptance(
                runtime_env,
                root=root,
                image_report_path=installed.DEFAULT_IMAGE_REPORT,
                ae_image_report_path=installed.DEFAULT_AE_IMAGE_REPORT,
                additional_services=(
                    "nex-mo",
                    "nex-wa",
                    "nex-wa-evidence-consumer",
                    "nex-ae-web",
                ),
                live_hook=live_hook,
                restart_services=(
                    "nex-ae-api",
                    "nex-wc",
                    "nex-eos",
                    "nex-wa",
                    *CURRENT_JOURNEY_WORKERS,
                    "nex-wa-evidence-consumer",
                ),
                post_restart_hook=post_restart_hook,
                finalization_hook=finalization_hook,
                worker_inventory=CURRENT_JOURNEY_WORKERS,
            )
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must always run
        execution_error = exc
    cleanup = m1_acceptance._drop_isolated_database_schemas(isolation["handles"])
    if execution_error is not None:
        raise ProtectedMatrixError(
            f"{execution_error}; zero_residue={cleanup['zero_residue']}"
        ) from execution_error
    if result is None or not cleanup["zero_residue"]:
        raise ProtectedMatrixError("W80 CA00G7 cleanup did not converge")
    return {
        **result,
        "status": "PASS",
        "database_isolation": {**isolation["evidence"], "cleanup": cleanup},
        "zero_residue": True,
        "provider_contacted": True,
    }


def _scenario_matrix(baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    project = baseline["projects"][0]["project_code"]
    company = baseline["company"]["company_code"]
    date_value = baseline["recognition_date"]
    definitions = (
        ("one-stage-success", "9000000", 1, "ENVELOPE_ONLY"),
        ("two-stage-success", "15000000", 2, "ENVELOPE_ONLY"),
        ("three-stage-success", "17000000", 3, "JOURNAL_SUCCESS"),
        ("middle-stage-rejection", "17000000", 3, "MIDDLE_REJECTION"),
        ("final-stage-rejection", "17000000", 3, "FINAL_REJECTION"),
        ("accounting-correction", "17000000", 3, "ACCOUNTING_CORRECTION"),
    )
    return [
        {
            "scenario_id": scenario_id,
            "expected_business_stages": stages,
            "outcome": outcome,
            "prompt": (
                f"회사 코드 {company} 기준으로 {date_value} 공급사 "
                f"W80-{scenario_id}의 KRW {amount} 외부 용역비를 Project "
                f"{project}의 전표로 처리해줘. 품의 제목은 W80 {scenario_id}이고 "
                "Project 원가 배부는 수행하지 마."
            ),
        }
        for scenario_id, amount, stages, outcome in definitions
    ]


def _run_browser(
    env: Mapping[str, str],
    *,
    baseline: Mapping[str, Any],
    scenarios: Sequence[Mapping[str, Any]],
    passwords: Mapping[str, str],
    screenshot_dir: Path,
) -> dict[str, Any]:
    principals = baseline["principals"]
    child = {
        **env,
        "NEX_MYBEE_W80_CA00G7_WEB_URL": "https://ae.nex-staging.test:8443",
        "NEX_MYBEE_W80_CA00G7_TENANT_ID": str(
            baseline["tenant"]["tenant_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_SCENARIOS_JSON": json.dumps(
            list(scenarios), ensure_ascii=False
        ),
        "NEX_MYBEE_W80_CA00G7_REQUESTER_EMPLOYEE_ID": str(
            principals["requester"]["employee_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_REQUESTER_PASSWORD": passwords["requester"],
        "NEX_MYBEE_W80_CA00G7_REQUESTER_SUBJECT_ID": str(
            principals["requester"]["subject_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_BUSINESS_EMPLOYEE_ID": str(
            principals["business_approver"]["employee_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_BUSINESS_PASSWORD": passwords[
            "business_approver"
        ],
        "NEX_MYBEE_W80_CA00G7_BUSINESS_SUBJECT_ID": str(
            principals["business_approver"]["subject_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_ACCOUNTING_EMPLOYEE_ID": str(
            principals["accounting_approver"]["employee_id"]
        ),
        "NEX_MYBEE_W80_CA00G7_ACCOUNTING_PASSWORD": passwords[
            "accounting_approver"
        ],
        "NEX_MYBEE_W80_CA00G7_SCREENSHOT_DIR": str(screenshot_dir),
        "NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS": "90000",
        "NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS": "180000",
        "NEX_MYBEE_M1_GOLDEN_RESULT_TIMEOUT_MS": "900000",
        "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE": env.get(
            "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/usr/bin/google-chrome"
        ),
    }
    completed = subprocess.run(
        ["node", str(PLAYWRIGHT_RUNNER)],
        cwd=ROOT / "apps/nex-ae-web",
        env=child,
        capture_output=True,
        text=True,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ProtectedMatrixError("W80 CA00G7 Playwright output is invalid") from exc
    if completed.returncode != 0 and result.get("status") == "PASS":
        raise ProtectedMatrixError("W80 CA00G7 Playwright status is inconsistent")
    return dict(result)


def _database_projection(
    urls: Mapping[str, str], *, tenant_id: str
) -> dict[str, int]:
    eos = create_engine(sqlalchemy_database_url(urls["nex-eos"]), poolclass=NullPool)
    ae = create_engine(sqlalchemy_database_url(urls["nex-ae-api"]), poolclass=NullPool)
    try:
        with eos.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_business_proposal WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_business_proposal WHERE tenant_id=:tenant AND state='APPROVED'), "
                    "(SELECT count(*) FROM eos_business_proposal WHERE tenant_id=:tenant AND state='REJECTED'), "
                    "(SELECT count(*) FROM eos_voucher_candidate WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_voucher_candidate_revision WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_journal_header WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant_id},
            ).one()
        with ae.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT agent_execution_id, external_ref, wait_type, count(*) "
                    "FROM ae_wait_registration WHERE tenant_id=:tenant AND state='PENDING' "
                    "GROUP BY agent_execution_id, external_ref, wait_type HAVING count(*) > 1"
                    ") AS duplicate_wait"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
            checkpoints = connection.execute(
                text(
                    "SELECT count(*) FROM ae_product_prep_checkpoint WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
        return {
            "proposal_count": int(row[0]),
            "approved_proposal_count": int(row[1]),
            "rejected_proposal_count": int(row[2]),
            "voucher_count": int(row[3]),
            "voucher_revision_count": int(row[4]),
            "journal_count": int(row[5]),
            "duplicate_pending_authority_count": int(pending),
            "product_checkpoint_count": int(checkpoints),
        }
    finally:
        eos.dispose()
        ae.dispose()


def _database_checks(
    database: Mapping[str, int], browser: Mapping[str, Any]
) -> dict[str, bool]:
    expected_voucher_revisions = _expected_voucher_revision_count(browser)
    return {
        "six_proposals": database["proposal_count"] == 6,
        "four_approved_proposals": database["approved_proposal_count"] == 4,
        "two_rejected_proposals": database["rejected_proposal_count"] == 2,
        "four_voucher_candidates": database["voucher_count"] == 4,
        "append_only_voucher_revisions": expected_voucher_revisions >= 0
        and database["voucher_revision_count"] == expected_voucher_revisions,
        "two_immutable_journals": database["journal_count"] == 2,
        "no_duplicate_pending_authority": database[
            "duplicate_pending_authority_count"
        ]
        == 0,
        "append_only_product_checkpoints": database["product_checkpoint_count"]
        >= 24,
        "playwright_matrix_passed": browser.get("status") == "PASS",
    }


def _expected_voucher_revision_count(browser: Mapping[str, Any]) -> int:
    scenarios = browser.get("scenarios")
    if not isinstance(scenarios, Sequence) or isinstance(scenarios, (str, bytes)):
        return -1

    expected = 0
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            return -1
        outcome = scenario.get("outcome")
        if outcome in VOUCHER_INITIAL_REVISION_OUTCOMES:
            expected += 1
        if outcome in VOUCHER_REVIEW_REVISION_OUTCOMES:
            expected += 1

        correction_cycle = scenario.get("correction_cycle", 0)
        if (
            not isinstance(correction_cycle, int)
            or isinstance(correction_cycle, bool)
            or correction_cycle < 0
        ):
            return -1
        expected += correction_cycle
    return expected


def summary_line(result: Mapping[str, Any]) -> str:
    extended = result.get("extended_acceptance")
    if not isinstance(extended, Mapping):
        extended = {}
    return (
        "mybee_w80_ca00g7_matrix="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"journeys={int(result.get('journey_count', 0))} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        "provider="
        f"{str(bool(result.get('actual_remote_generation', extended.get('actual_remote_generation')))).lower()} "
        "playwright="
        f"{str(bool(result.get('actual_playwright', extended.get('actual_playwright')))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run W80-CA00G.7 protected live acceptance matrix"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_protected_matrix(os.environ, execute=args.execute)
    installed._write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
