#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ae-api",
    "services/nex-eos",
    "scripts/deployment",
    "scripts/db",
):
    sys.path.insert(0, str(ROOT / relative))

import run_canonical_platform_installed_acceptance as installed
from mybee_m1_product_acceptance_support import (
    baseline_digest,
    build_transaction_prompt,
    load_acceptance_baseline,
    seed_acceptance_authority,
    wait_for_installed_authority,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_runtime.current_platform_installation import CURRENT_JOURNEY_WORKERS
from nex_runtime.database import psycopg_database_url
from nex_runtime.demo_database import resolve_current_platform_database_targets
from run_migrations import run_service_migrations

EXECUTION_ENV = "NEX_MYBEE_M1_PRODUCT_GOLDEN_LIVE"
SCHEMA_VERSION = "mybee_w70_cp_m1_product_golden_journey.v1"
DEFAULT_REPORT = (
    ROOT / "reports/deployment/mybee-w70-cp-m1-product-golden-journey.json"
)
DEFAULT_BROWSER_REPORT = (
    ROOT / "reports/deployment/mybee-w70-cp-m1-product-browser-evidence.json"
)
PLAYWRIGHT_RUNNER = (
    ROOT
    / "apps/nex-ae-web/scripts/runMyBeeW70CpM1ProductGoldenJourney.mjs"
)
SCREENSHOT_DIR = (
    ROOT / "reports/deployment/mybee-w70-cp-m1-product-golden-screens"
)
MODEL_PROFILE = "general-llm-default"
MODEL_REF_ENV = "NEX_MO_VLLM_MODEL"
MODEL_REVISION_ENV = "NEX_MO_VLLM_MODEL_REVISION"
MODEL_DEPLOYMENT_ENV = "NEX_MO_VLLM_DEPLOYMENT_ID"
DEFAULT_MODEL_REF = "Qwen3.5-9B"
GOLDEN_JOURNEY_EVIDENCE_CONTRACT = {
    "platform_integrated": True,
    "runtime_transition_fixture": False,
    "manual_domain_transition": False,
    "installed_process_continuity": True,
}


class M1ProductGoldenJourneyError(RuntimeError):
    pass


def run_m1_product_golden_journey(
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
        runner = protected_runner or execute_m1_product_golden_journey
        protected = dict(runner(env, root=root))
        return {**source, **protected, "executed": True}
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
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
        raise M1ProductGoldenJourneyError("M1 product Playwright runner is missing")
    package = json.loads(
        (root / "apps/nex-ae-web/package.json").read_text(encoding="utf-8")
    )
    if "smoke:mybee-m1-product-golden-journey" not in package.get("scripts", {}):
        raise M1ProductGoldenJourneyError(
            "M1 product Playwright command is not registered"
        )
    registry = load_product_capability_registry(
        {
            PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(
                root
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )
    product = registry.resolve("FINANCE.VOUCHER.APPROVE_AND_POST", required=True)
    if product is None or product.capability.get("status") != "ACTIVE":
        raise M1ProductGoldenJourneyError(
            "M1 product capability is not ACTIVE in the installed registry"
        )
    baseline = load_acceptance_baseline()
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "CP-M1-E2E-FX-01B.7",
        **GOLDEN_JOURNEY_EVIDENCE_CONTRACT,
        "source_admitted": True,
        "installed_prerequisite": installed_source["source_admitted"],
        "baseline_digest": baseline_digest(baseline),
        "product_capability_id": product.capability_id,
        "product_capability_version": product.capability_version,
        "actual_postgres_required": True,
        "actual_openbao_required": True,
        "actual_rustfs_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "non_identical_positive_request_count": 2,
        "post_request_direct_transition_allowed": False,
        "isolated_eight_database_schema_required": True,
        "secret_included": False,
        "token_value_included": False,
    }


def execute_m1_product_golden_journey(
    env: Mapping[str, str], *, root: Path
) -> dict[str, Any]:
    model_ref = str(env.get(MODEL_REF_ENV) or DEFAULT_MODEL_REF).strip()
    model_revision = str(env.get(MODEL_REVISION_ENV) or "").strip()
    model_deployment = str(env.get(MODEL_DEPLOYMENT_ENV) or "").strip()
    if not model_ref or not model_revision or not model_deployment:
        raise M1ProductGoldenJourneyError(
            "generation model, immutable revision, and deployment identity are required"
        )
    baseline = load_acceptance_baseline()
    prompts = [
        build_transaction_prompt(baseline, transaction_index=index)
        for index in range(2)
    ]
    requester_password = secrets.token_urlsafe(28)
    approver_password = secrets.token_urlsafe(28)
    sensitive = {requester_password, approver_password, *prompts}
    live_state: dict[str, Any] = {}
    _prepare_screenshot_directory(SCREENSHOT_DIR)

    runtime_env = {
        **env,
        "NEX_AE_WEB_TENANT_ID": str(baseline["tenant"]["tenant_id"]),
        "NEX_CANONICAL_PLATFORM_SEMANTIC_CALIBRATION_POLICIES_JSON": (
            _semantic_calibration_json(model_ref=model_revision)
        ),
    }
    runtime_env, database_isolation = _prepare_isolated_database_environment(
        runtime_env
    )

    def live_hook(**values: Any) -> Mapping[str, Any]:
        urls = dict(values["urls"])
        seeded = seed_acceptance_authority(
            urls,
            requester_password=requester_password,
            approver_password=approver_password,
            baseline=baseline,
        )
        synchronized = wait_for_installed_authority(
            urls,
            tenant_id=baseline["tenant"]["tenant_id"],
            expected_project_count=len(baseline["projects"]),
        )
        browser = _run_playwright(
            runtime_env,
            baseline=baseline,
            prompts=prompts,
            requester_password=requester_password,
            approver_password=approver_password,
        )
        installed._write_report(
            DEFAULT_BROWSER_REPORT, _public_browser_evidence(browser)
        )
        runtime = browser.get("runtime")
        transactions = (
            runtime.get("transactions") if isinstance(runtime, Mapping) else None
        )
        if browser.get("status") != "PASS" or not isinstance(transactions, list):
            log_output, diagnostic_returncode = _collect_ae_runtime_logs(
                runtime_env, root=root
            )
            runtime_failure = _semantic_runtime_failure_summary(
                log_output,
                returncode=diagnostic_returncode,
            )
            raise M1ProductGoldenJourneyError(
                "M1 product browser journey failed: "
                + _browser_failure_summary(browser)
                + f" runtime_exception={runtime_failure}"
            )
        interaction_ids = tuple(
            str(item.get("interaction_id") or "") for item in transactions
        )
        if len(interaction_ids) != 2 or not all(interaction_ids):
            raise M1ProductGoldenJourneyError(
                "M1 product browser journey omitted interaction lineage"
            )
        database = _database_projection(
            urls,
            tenant_id=baseline["tenant"]["tenant_id"],
            interaction_ids=interaction_ids,
        )
        checks = _live_checks(
            browser=browser,
            database=database,
            baseline=baseline,
        )
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise M1ProductGoldenJourneyError(
                f"M1 product database invariants failed: {','.join(failed)}"
            )
        first_result = transactions[0]["result_projection"]["result"]
        live_state.update(
            interaction_id=interaction_ids[0],
            result_hash=str(first_result["result_hash"]),
            business_refs=tuple(first_result.get("business_refs") or ()),
            interaction_ids=interaction_ids,
        )
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "provider_model_profile": MODEL_PROFILE,
            "provider_model_ref": model_ref,
            "provider_model_revision": model_revision,
            "provider_deployment_id": model_deployment,
            "authority_seed": seeded,
            "authority_synchronization": synchronized,
            "browser": _public_browser_evidence(browser),
            "database": database,
            "checks": checks,
            "secret_included": False,
        }

    def post_restart_hook(**values: Any) -> Mapping[str, Any]:
        urls = dict(values["urls"])
        recovered = _run_playwright(
            runtime_env,
            baseline=baseline,
            prompts=prompts,
            requester_password=requester_password,
            approver_password=approver_password,
            recovery_interaction_id=str(live_state["interaction_id"]),
        )
        runtime = recovered.get("runtime")
        projection = (
            runtime.get("result_projection")
            if isinstance(runtime, Mapping)
            else None
        )
        database = _database_projection(
            urls,
            tenant_id=baseline["tenant"]["tenant_id"],
            interaction_ids=tuple(live_state["interaction_ids"]),
        )
        checks = {
            "browser_recovery_passed": recovered.get("status") == "PASS",
            "result_hash_stable": isinstance(projection, Mapping)
            and projection.get("result", {}).get("result_hash")
            == live_state["result_hash"],
            "business_refs_stable": isinstance(projection, Mapping)
            and tuple(projection.get("result", {}).get("business_refs") or ())
            == live_state["business_refs"],
            "two_journals_after_restart": database["journal_count"] == 2,
            "two_allocation_batches_after_restart": database[
                "allocation_batch_count"
            ]
            == 2,
            "two_agent_results_after_restart": database["agent_result_count"] == 2,
        }
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise M1ProductGoldenJourneyError(
                f"M1 product restart invariants failed: {','.join(failed)}"
            )
        return {
            "status": "PASS",
            "actual_playwright": True,
            "authoritative_recovery": True,
            "browser": _public_browser_evidence(recovered),
            "database": database,
            "checks": checks,
            "secret_included": False,
        }

    try:
        installed_result = installed.execute_canonical_platform_acceptance(
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
            worker_inventory=CURRENT_JOURNEY_WORKERS,
        )
        result = {
            **installed_result,
            "provider_contacted": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "two_non_identical_positive_requests": True,
            "database_isolation": database_isolation["evidence"],
        }
        installed._assert_redacted(result, sensitive)
    finally:
        isolation_cleanup = _drop_isolated_database_schemas(
            database_isolation["handles"]
        )
    if not isolation_cleanup["zero_residue"]:
        raise M1ProductGoldenJourneyError(
            "isolated database schema cleanup left acceptance residue"
        )
    result["database_isolation"]["cleanup"] = isolation_cleanup
    result["zero_residue"] = True
    return result


def _prepare_isolated_database_environment(
    env: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    runtime_env = dict(env)
    targets = resolve_current_platform_database_targets(runtime_env)
    suffix = secrets.token_hex(6)
    handles: list[dict[str, str]] = []
    migrations: list[dict[str, Any]] = []
    try:
        for target in targets:
            service_id = target.target.service_id
            schema_name = (
                f"m1_01b7_{service_id.replace('-', '_')}_{suffix}"
            )
            with psycopg.connect(
                psycopg_database_url(target.database_url), autocommit=True
            ) as connection:
                identity = connection.execute(
                    "SELECT current_database(), current_user"
                ).fetchone()
                expected = (
                    target.target.expected_database_name,
                    target.target.expected_role_name,
                )
                if identity != expected:
                    raise M1ProductGoldenJourneyError(
                        f"{service_id} isolated database identity drifted"
                    )
                connection.execute(
                    sql.SQL("CREATE SCHEMA {}").format(
                        sql.Identifier(schema_name)
                    )
                )
                connection.execute(
                    sql.SQL(
                        "CREATE TABLE {}.schema_migrations ("
                        "version TEXT PRIMARY KEY, "
                        "description TEXT NOT NULL, "
                        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                    ).format(sql.Identifier(schema_name))
                )
            scoped_url = (
                make_url(target.database_url)
                .update_query_dict(
                    {"options": f"-csearch_path={schema_name},public"}
                )
                .render_as_string(hide_password=False)
            )
            handles.append(
                {
                    "service_id": service_id,
                    "database_url": target.database_url,
                    "schema_name": schema_name,
                }
            )
            migration = run_service_migrations(
                service_id,
                database_url=scoped_url,
                profile="dev",
            )
            if migration.skipped or migration.applied != migration.planned:
                raise M1ProductGoldenJourneyError(
                    f"{service_id} isolated migration inventory was not fresh"
                )
            runtime_env[target.target.database_env] = scoped_url
            migrations.append(
                {
                    "service_id": service_id,
                    "migration_count": len(migration.applied),
                }
            )
    except Exception:
        _drop_isolated_database_schemas(handles)
        raise
    return runtime_env, {
        "handles": tuple(handles),
        "evidence": {
            "schema_version": "mybee_m1_isolated_database_set.v1",
            "state": "CURRENT",
            "database_count": len(handles),
            "migration_count": sum(item["migration_count"] for item in migrations),
            "migrations": migrations,
            "immutable_protection_bypassed": False,
            "secret_included": False,
        },
    }


def _drop_isolated_database_schemas(
    handles: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    dropped: list[str] = []
    residue: list[str] = []
    for handle in reversed(tuple(handles)):
        schema_name = handle["schema_name"]
        with psycopg.connect(
            psycopg_database_url(handle["database_url"]), autocommit=True
        ) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            remaining = connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone()
            if remaining != (None,):
                residue.append(handle["service_id"])
            else:
                dropped.append(handle["service_id"])
    return {
        "schema_version": "mybee_m1_isolated_database_cleanup.v1",
        "dropped_database_count": len(dropped),
        "residue_service_ids": sorted(residue),
        "zero_residue": not residue and len(dropped) == len(handles),
    }


def _semantic_runtime_failure(log_output: str) -> str:
    match = re.search(
        r"exception_type(?:=|[\"']?\s*:\s*[\"']?)"
        r"([A-Za-z][A-Za-z0-9_]{0,95})",
        log_output,
    )
    if match:
        exception_type = match.group(1)
        error_code = re.search(
            r"error_code(?:=|[\"']?\s*:\s*[\"']?)"
            r"([A-Za-z][A-Za-z0-9_.-]{0,95})",
            log_output[match.start() : match.start() + 512],
        )
        return (
            f"{exception_type}:{error_code.group(1)}"
            if error_code
            else exception_type
        )
    traceback_types = re.findall(
        r"(?m)^.*\|\s*(?:[A-Za-z_][A-Za-z0-9_.]*\.)?"
        r"([A-Za-z][A-Za-z0-9_]{0,87}(?:Error|Exception)):\s",
        log_output,
    )
    return traceback_types[-1] if traceback_types else "not_observed"


def _semantic_runtime_failure_summary(
    log_output: str, *, returncode: int
) -> str:
    failure = _semantic_runtime_failure(log_output)
    if failure != "not_observed":
        return failure
    line_count = sum(1 for line in log_output.splitlines() if line.strip())
    return f"not_observed(rc={returncode},lines={line_count})"


def _collect_ae_runtime_logs(
    env: Mapping[str, str], *, root: Path
) -> tuple[str, int]:
    lookup = subprocess.run(
        (
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={installed.PROJECT_NAME}",
            "--filter",
            "label=com.docker.compose.service=nex-ae-api",
            "--format",
            "{{.ID}}",
        ),
        cwd=root,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    container_ids = [
        line.strip()
        for line in lookup.stdout.splitlines()
        if re.fullmatch(r"[a-f0-9]{12,64}", line.strip())
    ]
    if not container_ids:
        return lookup.stdout, lookup.returncode
    completed = subprocess.run(
        ("docker", "logs", "--tail", "2000", container_ids[0]),
        cwd=root,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=60,
    )
    return completed.stdout, completed.returncode


def _run_playwright(
    env: Mapping[str, str],
    *,
    baseline: Mapping[str, Any],
    prompts: Sequence[str],
    requester_password: str,
    approver_password: str,
    recovery_interaction_id: str | None = None,
) -> dict[str, Any]:
    child_env = {
        **env,
        "NEX_MYBEE_M1_GOLDEN_WEB_URL": "https://ae.nex-staging.test:8443",
        "NEX_MYBEE_M1_GOLDEN_TENANT_ID": baseline["tenant"]["tenant_id"],
        "NEX_MYBEE_M1_GOLDEN_REQUESTER_EMPLOYEE_ID": baseline["principals"]
        ["requester"]["employee_id"],
        "NEX_MYBEE_M1_GOLDEN_REQUESTER_PASSWORD": requester_password,
        "NEX_MYBEE_M1_GOLDEN_APPROVER_EMPLOYEE_ID": baseline["principals"]
        ["approver"]["employee_id"],
        "NEX_MYBEE_M1_GOLDEN_APPROVER_PASSWORD": approver_password,
        "NEX_MYBEE_M1_GOLDEN_PROMPTS_JSON": json.dumps(
            list(prompts), ensure_ascii=False
        ),
        "NEX_MYBEE_M1_GOLDEN_SCREENSHOT_DIR": str(SCREENSHOT_DIR),
        "NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS": "900000",
        "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE": env.get(
            "NEX_PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/usr/bin/google-chrome"
        ),
    }
    arguments = ["node", str(PLAYWRIGHT_RUNNER)]
    if recovery_interaction_id is not None:
        child_env["NEX_MYBEE_M1_GOLDEN_RECOVERY_INTERACTION_ID"] = (
            recovery_interaction_id
        )
        arguments.append("--recovery")
    completed = subprocess.run(
        arguments,
        cwd=ROOT / "apps/nex-ae-web",
        env=child_env,
        capture_output=True,
        text=True,
        timeout=960,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        evidence = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise M1ProductGoldenJourneyError(
            "M1 product Playwright output is invalid"
        ) from exc
    if completed.returncode != 0 and evidence.get("status") == "PASS":
        raise M1ProductGoldenJourneyError(
            "M1 product Playwright process failed after reporting PASS"
        )
    return dict(evidence)


def _database_projection(
    urls: Mapping[str, str],
    *,
    tenant_id: str,
    interaction_ids: Sequence[str],
) -> dict[str, Any]:
    engines = {
        service: create_engine(urls[service], poolclass=NullPool)
        for service in ("nex-ae-api", "nex-wc", "nex-eos", "nex-wa")
    }
    try:
        with engines["nex-ae-api"].connect() as connection:
            ae = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM ae_agent_execution WHERE tenant_id=:tenant "
                    " AND CAST(legacy_interaction_id AS text)=ANY(:interactions)), "
                    "(SELECT count(*) FROM ae_agent_result WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM ae_result_delivery WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM ae_result_delivery WHERE tenant_id=:tenant "
                    " AND state='ACKNOWLEDGED')"
                ),
                {"tenant": tenant_id, "interactions": list(interaction_ids)},
            ).one()
        with engines["nex-wc"].connect() as connection:
            wc_decisions = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM wc_approval_decision "
                        "WHERE tenant_id=:tenant AND decision='APPROVE'"
                    ),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
        with engines["nex-eos"].connect() as connection:
            eos = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_voucher_candidate WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_journal_header WHERE tenant_id=:tenant), "
                    "(SELECT count(DISTINCT journal_id) FROM eos_journal_header WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_cost_allocation_batch WHERE tenant_id=:tenant), "
                    "(SELECT count(DISTINCT batch_id) FROM eos_cost_allocation_batch WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_cost_allocation_line WHERE tenant_id=:tenant), "
                    "(SELECT count(*) FROM eos_project_pnl_projection WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant_id},
            ).one()
            first_batch = connection.execute(
                text(
                    "SELECT allocated_total, unallocated_total FROM eos_cost_allocation_batch "
                    "WHERE tenant_id=:tenant ORDER BY created_at, batch_id LIMIT 1"
                ),
                {"tenant": tenant_id},
            ).one()
            first_lines = connection.execute(
                text(
                    "SELECT allocated_amount_functional FROM eos_cost_allocation_line "
                    "WHERE tenant_id=:tenant AND batch_id=(SELECT batch_id FROM "
                    "eos_cost_allocation_batch WHERE tenant_id=:tenant "
                    "ORDER BY created_at, batch_id LIMIT 1) ORDER BY line_no"
                ),
                {"tenant": tenant_id},
            ).scalars().all()
        with engines["nex-wa"].connect() as connection:
            wa_assets = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant"
                    ),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
        return {
            "execution_count": int(ae[0]),
            "agent_result_count": int(ae[1]),
            "result_delivery_count": int(ae[2]),
            "acknowledged_delivery_count": int(ae[3]),
            "approval_decision_count": wc_decisions,
            "voucher_candidate_count": int(eos[0]),
            "journal_count": int(eos[1]),
            "distinct_journal_count": int(eos[2]),
            "allocation_batch_count": int(eos[3]),
            "distinct_allocation_batch_count": int(eos[4]),
            "allocation_line_count": int(eos[5]),
            "pnl_projection_count": int(eos[6]),
            "first_batch_allocated_total": format(first_batch[0], "f"),
            "first_batch_unallocated_total": format(first_batch[1], "f"),
            "first_batch_project_amounts": [format(value, "f") for value in first_lines],
            "wa_work_asset_count": wa_assets,
        }
    finally:
        for engine in engines.values():
            engine.dispose()


def _live_checks(
    *,
    browser: Mapping[str, Any],
    database: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, bool]:
    expected = baseline["expected_first_result"]
    return {
        "playwright_passed": browser.get("status") == "PASS",
        "two_ia_executions": database["execution_count"] == 2,
        "two_agent_results": database["agent_result_count"] == 2,
        "two_result_deliveries": database["result_delivery_count"] == 2,
        "all_deliveries_acknowledged": database["acknowledged_delivery_count"] == 2,
        "approval_chain_present": database["approval_decision_count"] >= 6,
        "two_voucher_candidates": database["voucher_candidate_count"] == 2,
        "two_immutable_journals": database["journal_count"] == 2,
        "journal_duplicates_absent": database["distinct_journal_count"] == 2,
        "two_allocation_batches": database["allocation_batch_count"] == 2,
        "allocation_duplicates_absent": database[
            "distinct_allocation_batch_count"
        ]
        == 2,
        "four_allocation_lines": database["allocation_line_count"] == 4,
        "pnl_projection_present": database["pnl_projection_count"] >= 2,
        "wa_evidence_present": database["wa_work_asset_count"] >= 2,
        "first_allocation_total_exact": database["first_batch_allocated_total"]
        == expected["allocated_amount"],
        "first_allocation_residual_zero": database[
            "first_batch_unallocated_total"
        ]
        == expected["unallocated_amount"],
        "first_project_amounts_exact": database["first_batch_project_amounts"]
        == expected["project_amounts"],
    }


def _semantic_calibration_json(*, model_ref: str) -> str:
    policies = [
        {
            "semantic_stage": stage,
            "policy_ref": f"semantic-admission://{stage.lower()}/mybee-m1-product/v1",
            "policy_version": "mybee-m1-product-v1",
            "model_profile": MODEL_PROFILE,
            "model_ref": model_ref,
            "minimum_confidence": 0.5,
            "golden_evidence_ref": f"acceptance://mybee-m1/{stage.lower()}/golden",
            "adversarial_evidence_ref": (
                f"acceptance://mybee-m1/{stage.lower()}/adversarial"
            ),
        }
        for stage in ("INTENT", "CONTEXT", "PLAN")
    ]
    return json.dumps(policies, separators=(",", ":"), sort_keys=True)


def _prepare_screenshot_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for screenshot in directory.glob("mybee-m1-*.png"):
        screenshot.unlink()


def _public_browser_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evidence.items() if key != "runtime"}


def _browser_failure_summary(evidence: Mapping[str, Any]) -> str:
    observations = evidence.get("observations")
    safe_observations = observations if isinstance(observations, Mapping) else {}
    stage = str(safe_observations.get("stage") or "unknown")
    recent = safe_observations.get("recent_api_responses")
    statuses = []
    if isinstance(recent, list):
        for item in recent[-8:]:
            if not isinstance(item, Mapping):
                continue
            route = item.get("route") or item.get("route_class") or "other"
            statuses.append(
                f"{route}:{item.get('status', 'unknown')}"
            )
    return (
        f"{evidence.get('failure_code', 'unknown')} "
        f"stage={stage} responses={','.join(statuses) or 'none'}"
    )


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "mybee_m1_product_golden="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        f"provider={str(bool(result.get('actual_remote_generation'))).lower()} "
        f"playwright={str(bool(result.get('actual_playwright'))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the MyBee W70 M1 installed product golden journey"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_m1_product_golden_journey(os.environ, execute=args.execute)
    installed._write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
