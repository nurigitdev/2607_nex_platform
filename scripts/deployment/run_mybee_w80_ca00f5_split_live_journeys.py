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
for relative in (
    "services/_shared",
    "services/nex-ae-api",
    "scripts/deployment",
):
    sys.path.insert(0, str(ROOT / relative))

import run_canonical_platform_installed_acceptance as installed
import run_mybee_w70_cp_m1_product_golden_journey as m1_acceptance
from mybee_m1_product_acceptance_support import (
    baseline_digest,
    build_accounting_allocation_prompt,
    build_journal_prompt,
    load_acceptance_baseline,
    seed_acceptance_authority,
    wait_for_installed_authority,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING
from nex_runtime.current_platform_installation import CURRENT_JOURNEY_WORKERS
from nex_runtime.database import sqlalchemy_database_url

EXECUTION_ENV = "NEX_MYBEE_W80_CA00F5_LIVE"
SCHEMA_VERSION = "mybee_w80_ca00f5_split_live_journeys.v1"
DEFAULT_REPORT = ROOT / "reports/deployment/mybee-w80-ca00f5-split-live-journeys.json"
DEFAULT_BROWSER_REPORT = ROOT / "reports/deployment/mybee-w80-ca00f5-browser-evidence.json"
DEFAULT_RECOVERY_REPORT = ROOT / "reports/deployment/mybee-w80-ca00f5-browser-recovery-evidence.json"
PLAYWRIGHT_RUNNER = ROOT / "apps/nex-ae-web/scripts/runMyBeeW80Ca00F5SplitJourney.mjs"
SCREENSHOT_DIR = ROOT / "reports/deployment/mybee-w80-ca00f5-split-screens"
REGISTRY_PATH = ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v5.json"
PROCESS_TIMEOUT_SECONDS = 1_260


class SplitLiveJourneyError(RuntimeError):
    pass


def run_split_live_journeys(
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
    except Exception as exc:  # noqa: BLE001 - acceptance records bounded failure
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "secret_included": False,
            "token_value_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    installed_source = installed._source_admission(root)
    if not PLAYWRIGHT_RUNNER.is_file():
        raise SplitLiveJourneyError("W80 split Playwright runner is missing")
    package = json.loads((root / "apps/nex-ae-web/package.json").read_text())
    if "smoke:mybee-w80-ca00f5-split-journey" not in package.get("scripts", {}):
        raise SplitLiveJourneyError("W80 split Playwright command is not registered")
    registry = load_product_capability_registry(
        {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(REGISTRY_PATH)}
    )
    required = {
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "FINANCE.COST_ALLOCATION.RUN",
    }
    active = {
        registration.capability_id
        for registration in registry.registrations
        if registration.capability.get("status") == "ACTIVE"
    }
    if not required.issubset(active):
        raise SplitLiveJourneyError("split journey capabilities are not ACTIVE")
    baseline = load_acceptance_baseline()
    product_roots = (root / "services/nex-ae-api", root / "domains/mybee")
    forbidden = {
        str(baseline["tenant"]["tenant_id"]),
        *(str(item["project_code"]) for item in baseline["projects"]),
    }
    residue = sorted(
        str(path.relative_to(root))
        for product_root in product_roots
        for path in product_root.rglob("*.py")
        if any(value in path.read_text(encoding="utf-8") for value in forbidden)
    )
    if residue:
        raise SplitLiveJourneyError("scenario identity leaked into product runtime")
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "W80-CA00F.5",
        "source_admitted": True,
        "installed_prerequisite": installed_source["source_admitted"],
        "baseline_digest": baseline_digest(baseline),
        "active_capabilities": sorted(required),
        "journal_and_allocation_are_independent": True,
        "actual_postgres_required": True,
        "actual_openbao_required": True,
        "actual_rustfs_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "restart_recovery_required": True,
        "scenario_product_residue": residue,
        "secret_included": False,
        "token_value_included": False,
    }


def _execute(env: Mapping[str, str], *, root: Path) -> dict[str, Any]:
    baseline = load_acceptance_baseline()
    requester_password = secrets.token_urlsafe(28)
    business_password = secrets.token_urlsafe(28)
    accounting_password = secrets.token_urlsafe(28)
    journal_prompt = build_journal_prompt(baseline, transaction_index=0)
    session_id = (
        "mybee-w80-ca00f5-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(4)
    )
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
    live_state: dict[str, Any] = {}
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

    def live_hook(**values: Any) -> Mapping[str, Any]:
        urls = dict(values["urls"])
        seed = seed_acceptance_authority(
            urls,
            requester_password=requester_password,
            business_approver_password=business_password,
            accounting_approver_password=accounting_password,
            baseline=baseline,
        )
        synchronized = wait_for_installed_authority(
            urls,
            tenant_id=str(baseline["tenant"]["tenant_id"]),
            expected_project_count=len(baseline["projects"]),
        )
        journal = _run_browser(
            runtime_env,
            mode="journal",
            prompt=journal_prompt,
            baseline=baseline,
            submitter_role="requester",
            passwords={
                "requester": requester_password,
                "business_approver": business_password,
                "accounting_approver": accounting_password,
            },
        )
        if journal.get("status") != "PASS":
            raise SplitLiveJourneyError(
                f"Journal Playwright journey failed: {journal.get('failure_code')}"
            )
        journal_identity = _wait_for_journal_identity(
            urls["nex-eos"], tenant_id=str(baseline["tenant"]["tenant_id"])
        )
        before_allocation = _eos_counts(
            urls["nex-eos"], tenant_id=str(baseline["tenant"]["tenant_id"])
        )
        if before_allocation["allocation_batch_count"] != 0 or before_allocation[
            "pnl_projection_count"
        ] != 0:
            raise SplitLiveJourneyError(
                "Journal journey invoked allocation or P&L projection"
            )
        allocation_prompt = build_accounting_allocation_prompt(
            baseline,
            company_id=journal_identity["company_id"],
            journal_id=journal_identity["journal_id"],
            source_record_line_ref=journal_identity["source_record_line_ref"],
        )
        allocation = _run_browser(
            runtime_env,
            mode="allocation",
            prompt=allocation_prompt,
            baseline=baseline,
            submitter_role="business_approver",
            passwords={
                "requester": requester_password,
                "business_approver": business_password,
                "accounting_approver": accounting_password,
            },
        )
        if allocation.get("status") != "PASS":
            raise SplitLiveJourneyError(
                f"Allocation Playwright journey failed: {allocation.get('failure_code')}"
            )
        browser = {"journal": journal, "allocation": allocation}
        installed._write_report(DEFAULT_BROWSER_REPORT, _public_browser(browser))
        interaction_ids = (
            str(journal["runtime"]["interaction_id"]),
            str(allocation["runtime"]["interaction_id"]),
        )
        database = m1_acceptance._database_projection(
            urls,
            tenant_id=str(baseline["tenant"]["tenant_id"]),
            interaction_ids=interaction_ids,
        )
        checks = _live_checks(
            database=database,
            before_allocation=before_allocation,
            baseline=baseline,
        )
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise SplitLiveJourneyError(
                "split live database invariants failed: " + ",".join(failed)
            )
        live_state.update(
            interaction_ids=interaction_ids,
            journal_result_hash=journal["runtime"]["result_projection"]["result"][
                "result_hash"
            ],
            allocation_result_hash=allocation["runtime"]["result_projection"][
                "result"
            ]["result_hash"],
            database=database,
        )
        return {
            "status": "PASS",
            "authority_seed": seed,
            "authority_synchronization": synchronized,
            "journal_identity": journal_identity,
            "browser": _public_browser(browser),
            "database": database,
            "checks": checks,
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "provider_model_ref": CANONICAL_GENERATION_BINDING.model_name,
            "provider_model_revision": CANONICAL_GENERATION_BINDING.model_revision,
            "provider_deployment_id": CANONICAL_GENERATION_BINDING.deployment_id,
            "secret_included": False,
        }

    def post_restart_hook(**values: Any) -> Mapping[str, Any]:
        urls = dict(values["urls"])
        recovered = {
            "journal": _run_browser_recovery(
                runtime_env,
                mode="journal",
                interaction_id=live_state["interaction_ids"][0],
                baseline=baseline,
                submitter_role="requester",
                passwords={
                    "requester": requester_password,
                    "business_approver": business_password,
                    "accounting_approver": accounting_password,
                },
            ),
            "allocation": _run_browser_recovery(
                runtime_env,
                mode="allocation",
                interaction_id=live_state["interaction_ids"][1],
                baseline=baseline,
                submitter_role="business_approver",
                passwords={
                    "requester": requester_password,
                    "business_approver": business_password,
                    "accounting_approver": accounting_password,
                },
            ),
        }
        database = m1_acceptance._database_projection(
            urls,
            tenant_id=str(baseline["tenant"]["tenant_id"]),
            interaction_ids=live_state["interaction_ids"],
        )
        checks = {
            "both_results_recovered": all(
                item.get("status") == "PASS" for item in recovered.values()
            ),
            "journal_result_hash_stable": recovered["journal"]["runtime"][
                "result_projection"
            ]["result"]["result_hash"]
            == live_state["journal_result_hash"],
            "allocation_result_hash_stable": recovered["allocation"]["runtime"][
                "result_projection"
            ]["result"]["result_hash"]
            == live_state["allocation_result_hash"],
            "journal_not_duplicated": database["journal_count"] == 1,
            "allocation_not_duplicated": database["allocation_batch_count"] == 1,
            "agent_results_not_duplicated": database["agent_result_count"] == 2,
        }
        if not all(checks.values()):
            raise SplitLiveJourneyError("split restart/replay invariants failed")
        installed._write_report(DEFAULT_RECOVERY_REPORT, _public_browser(recovered))
        return {
            "status": "PASS",
            "browser": _public_browser(recovered),
            "database": database,
            "checks": checks,
        }

    def finalization_hook(**values: Any) -> Mapping[str, Any]:
        return m1_acceptance._collect_live_journey_diagnostics(
            values["runtime_env"],
            root=values["root"],
            session_id=session_id,
            forbidden_values={requester_password, business_password, accounting_password},
            screen_manifest_names=(
                "mybee-m1-w80-journal-screen-manifest.json",
                "mybee-m1-w80-allocation-screen-manifest.json",
                "mybee-m1-w80-journal-recovery-screen-manifest.json",
                "mybee-m1-w80-allocation-recovery-screen-manifest.json",
            ),
            screen_required_state_counts={
                "SUBMITTER_WORKSPACE_READY": 2,
                "REQUEST_ADMITTED": 2,
                "APPROVAL_RECORDED": 3,
                "RESULT_RENDERED": 2,
                "RESULT_RECOVERED": 2,
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
        raise SplitLiveJourneyError(
            f"{execution_error}; zero_residue={cleanup['zero_residue']}"
        ) from execution_error
    if result is None or not cleanup["zero_residue"]:
        raise SplitLiveJourneyError("split live journey cleanup did not converge")
    return {
        **result,
        "status": "PASS",
        "database_isolation": {**isolation["evidence"], "cleanup": cleanup},
        "zero_residue": True,
        "provider_contacted": True,
        "actual_remote_generation": True,
        "actual_playwright": True,
    }


def _run_browser(
    env: Mapping[str, str],
    *,
    mode: str,
    prompt: str,
    baseline: Mapping[str, Any],
    submitter_role: str,
    passwords: Mapping[str, str],
) -> dict[str, Any]:
    child = _browser_env(
        env,
        mode=mode,
        baseline=baseline,
        submitter_role=submitter_role,
        passwords=passwords,
    )
    child["NEX_MYBEE_W80_SPLIT_PROMPT"] = prompt
    return _invoke_playwright(child, [])


def _run_browser_recovery(
    env: Mapping[str, str],
    *,
    mode: str,
    interaction_id: str,
    baseline: Mapping[str, Any],
    submitter_role: str,
    passwords: Mapping[str, str],
) -> dict[str, Any]:
    child = _browser_env(
        env,
        mode=mode,
        baseline=baseline,
        submitter_role=submitter_role,
        passwords=passwords,
    )
    child["NEX_MYBEE_W80_SPLIT_RECOVERY_INTERACTION_ID"] = interaction_id
    return _invoke_playwright(child, ["--recovery"])


def _browser_env(
    env: Mapping[str, str],
    *,
    mode: str,
    baseline: Mapping[str, Any],
    submitter_role: str,
    passwords: Mapping[str, str],
) -> dict[str, str]:
    principals = baseline["principals"]
    return {
        **env,
        "NEX_MYBEE_W80_SPLIT_WEB_URL": "https://ae.nex-staging.test:8443",
        "NEX_MYBEE_W80_SPLIT_TENANT_ID": str(baseline["tenant"]["tenant_id"]),
        "NEX_MYBEE_W80_SPLIT_MODE": mode,
        "NEX_MYBEE_W80_SPLIT_SUBMITTER_EMPLOYEE_ID": str(
            principals[submitter_role]["employee_id"]
        ),
        "NEX_MYBEE_W80_SPLIT_SUBMITTER_PASSWORD": passwords[submitter_role],
        "NEX_MYBEE_W80_SPLIT_BUSINESS_APPROVER_EMPLOYEE_ID": str(
            principals["business_approver"]["employee_id"]
        ),
        "NEX_MYBEE_W80_SPLIT_BUSINESS_APPROVER_PASSWORD": passwords[
            "business_approver"
        ],
        "NEX_MYBEE_W80_SPLIT_ACCOUNTING_APPROVER_EMPLOYEE_ID": str(
            principals["accounting_approver"]["employee_id"]
        ),
        "NEX_MYBEE_W80_SPLIT_ACCOUNTING_APPROVER_PASSWORD": passwords[
            "accounting_approver"
        ],
        "NEX_MYBEE_W80_SPLIT_SCREENSHOT_DIR": str(SCREENSHOT_DIR),
        "NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS": "60000",
        "NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS": "180000",
        "NEX_MYBEE_M1_GOLDEN_RESULT_TIMEOUT_MS": "900000",
        "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE": env.get(
            "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/usr/bin/google-chrome"
        ),
    }


def _invoke_playwright(env: Mapping[str, str], arguments: Sequence[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", str(PLAYWRIGHT_RUNNER), *arguments],
        cwd=ROOT / "apps/nex-ae-web",
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise SplitLiveJourneyError("split Playwright output is invalid") from exc
    if completed.returncode != 0 and result.get("status") == "PASS":
        raise SplitLiveJourneyError("split Playwright returned inconsistent status")
    return dict(result)


def _wait_for_journal_identity(database_url: str, *, tenant_id: str) -> dict[str, str]:
    engine = create_engine(sqlalchemy_database_url(database_url), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT header.company_id, header.journal_id, line.source_record_line_ref "
                    "FROM eos_journal_header AS header JOIN eos_journal_line AS line "
                    "ON line.tenant_id=header.tenant_id AND line.company_id=header.company_id "
                    "AND line.journal_id=header.journal_id "
                    "WHERE header.tenant_id=:tenant AND line.line_no=1 "
                    "ORDER BY header.posted_at DESC LIMIT 1"
                ),
                {"tenant": tenant_id},
            ).one_or_none()
            if row is None:
                raise SplitLiveJourneyError("Journal identity was not materialized")
            return {
                "company_id": str(row[0]),
                "journal_id": str(row[1]),
                "source_record_line_ref": str(row[2]),
            }
    finally:
        engine.dispose()


def _eos_counts(database_url: str, *, tenant_id: str) -> dict[str, int]:
    engine = create_engine(sqlalchemy_database_url(database_url), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_journal_header WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_cost_allocation_batch WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_project_pnl_projection WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant_id},
            ).one()
            return {
                "journal_count": int(row[0]),
                "allocation_batch_count": int(row[1]),
                "pnl_projection_count": int(row[2]),
            }
    finally:
        engine.dispose()


def _live_checks(
    *,
    database: Mapping[str, Any],
    before_allocation: Mapping[str, int],
    baseline: Mapping[str, Any],
) -> dict[str, bool]:
    expected = baseline["expected_first_result"]
    return {
        "journal_stopped_before_allocation": before_allocation["journal_count"] == 1
        and before_allocation["allocation_batch_count"] == 0
        and before_allocation["pnl_projection_count"] == 0,
        "two_independent_executions": database["execution_count"] == 2,
        "two_independent_agent_results": database["agent_result_count"] == 2,
        "two_workspace_results_acknowledged": database[
            "acknowledged_delivery_count"
        ]
        == 2,
        "three_sequential_journal_approval_decisions": database[
            "approval_decision_count"
        ]
        == 3,
        "one_voucher_candidate": database["voucher_candidate_count"] == 1,
        "one_immutable_journal": database["journal_count"] == 1,
        "one_allocation_batch": database["allocation_batch_count"] == 1,
        "two_allocation_lines": database["allocation_line_count"] == 2,
        "affected_project_projections_present": database["pnl_projection_count"]
        == 2,
        "allocation_conserves_source": database["first_batch_allocated_total"]
        == expected["allocated_amount"]
        and database["first_batch_unallocated_total"]
        == expected["unallocated_amount"],
        "allocation_ratios_match_authority": database["first_batch_project_amounts"]
        == expected["project_amounts"],
    }


def _public_browser(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: {name: item for name, item in child.items() if name != "runtime"}
        for key, child in value.items()
        if isinstance(child, Mapping)
    }


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "mybee_w80_ca00f5_split="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        f"provider={str(bool(result.get('actual_remote_generation'))).lower()} "
        f"playwright={str(bool(result.get('actual_playwright'))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run W80 split installed live journeys")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_split_live_journeys(os.environ, execute=args.execute)
    installed._write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
