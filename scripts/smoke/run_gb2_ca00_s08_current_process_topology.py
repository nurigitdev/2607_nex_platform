#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "scripts/db",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_ca00_s05_ae_agent_runtime_worker as s05
import run_gb2_ca00_s06_wc_event_delivery_worker as s06
import run_gb2_ca00_s07_eos_outbox_publisher as s07
from nex_runtime import psycopg_database_url, redact_database_url
from nex_runtime.current_topology_closure import build_current_topology_closure
from nex_runtime.deployment_entrypoints import build_current_packaged_runtime_manifest
from nex_runtime.env import read_env_file
from nex_runtime.postgres_targets import (
    CURRENT_POSTGRES_TEST_TARGETS,
    ResolvedPostgresTestTarget,
    resolve_postgres_test_targets,
)
from nex_runtime.process_manifest import CURRENT_BACKGROUND_PROCESS_IDS
from nex_runtime.runtime_process_adapters import build_runtime_process_environment
from nex_runtime.runtime_profiles import (
    CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
    CURRENT_SIGNED_TRUST_ENV_NAMES,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import run_service_migrations

SCHEMA_VERSION = "gb2_ca00_s08_current_topology_acceptance.v1"
SMOKE_ENV = "NEX_GB2_S08_CURRENT_TOPOLOGY_SMOKE"
DATABASE_ENV_FILE_ENV = "NEX_GB2_S08_DATABASE_ENV_FILE"
PYTHON_BIN = ROOT / ".venv/bin/python"
API_IMPORT_MODULES = (
    "nex_oa.main",
    "nex_mo.main",
    "nex_cx.main",
    "nex_ae_api.main",
    "nex_ag.main",
    "nex_wc.main",
    "nex_eos.main",
    "nex_wa.main",
)
SERVICE_SOURCE_ROOTS = tuple(
    ROOT / "services" / service
    for service in (
        "nex-oa",
        "nex-mo",
        "nex-cx",
        "nex-ae-api",
        "nex-ag",
        "nex-wc",
        "nex-eos",
        "nex-wa",
    )
)


def run_gb2_ca00_s08_current_process_topology(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S08",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    try:
        service_ids = tuple(
            target.service_id for target in CURRENT_POSTGRES_TEST_TARGETS
        )
        targets = resolve_postgres_test_targets(env, service_ids=service_ids)
        evidence = _execute_protected_topology(env, targets)
        evidence.update(
            {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice": "GB2-CA00-S08",
                "evidence_classification": "PROTECTED_TOPOLOGY",
                "profile": "test",
                "actual_postgres": True,
                "remote_provider_required": False,
                "database_targets": [
                    {
                        "service_id": item.target.service_id,
                        "database_environment": item.target.test_database_env,
                        "database_url": redact_database_url(item.database_url),
                    }
                    for item in targets
                ],
                "secret_included": False,
                "content_included": False,
            }
        )
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "gb2_s08_topology_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected boundary.
        return _failure("execution_failed", _redact_detail(str(exc), env))


def _execute_protected_topology(
    environ: Mapping[str, str],
    targets: Sequence[ResolvedPostgresTestTarget],
) -> dict[str, Any]:
    migrations: dict[str, dict[str, Any]] = {}
    identities: dict[str, dict[str, Any]] = {}
    for item in targets:
        migration = run_service_migrations(
            item.target.service_id,
            database_url=item.database_url,
            profile="test",
        )
        identity = _database_identity_and_migrations(item)
        migrations[item.target.service_id] = {
            "planned_count": len(migration.planned),
            "applied_count": len(migration.applied),
            "skipped_count": len(migration.skipped),
            "latest_version": migration.planned[-1] if migration.planned else None,
            "current": set(identity["migration_versions"]) == set(migration.planned),
        }
        identities[item.target.service_id] = {
            "database": identity["database"],
            "role": identity["role"],
            "identity_valid": identity["database"] == item.target.expected_database_name
            and identity["role"] == item.target.expected_role_name,
        }

    configured = _protected_environment(environ, targets)
    closure = build_current_topology_closure(
        ROOT,
        protected_environment=configured,
        python_executable=str(PYTHON_BIN),
    )
    manifest = build_current_packaged_runtime_manifest(
        "test",
        environ=configured,
        python_executable=str(PYTHON_BIN),
    )
    runtime_environment = build_runtime_process_environment(
        manifest,
        environ=configured,
    )
    background_checks = _run_background_checks(manifest, runtime_environment)
    api_imports = _run_api_import_checks(runtime_environment)
    component_evidence = _run_promoted_component_smokes(environ)
    cleanup_remaining = sum(
        int(value)
        for component in component_evidence.values()
        for name, value in (component.get("cleanup_counts") or {}).items()
        if name.endswith("_remaining")
    )
    checks = {
        "all_database_identities_valid": all(
            item["identity_valid"] for item in identities.values()
        ),
        "all_migrations_current": all(item["current"] for item in migrations.values()),
        "closure_passed": closure["status"] == "PASS",
        "nine_artifacts": closure["artifact_count"] == 9,
        "twenty_processes": closure["process_count"] == 20,
        "eleven_background_checks_passed": len(background_checks) == 11
        and all(item["passed"] for item in background_checks.values()),
        "eight_api_imports_passed": len(api_imports) == 8 and all(api_imports.values()),
        "three_promoted_work_loops_passed": all(
            item.get("status") == "PASS" for item in component_evidence.values()
        ),
        "promoted_work_loop_readiness_truthful": all(
            (item.get("checks") or {}).get("readiness_truthful") is True
            for item in component_evidence.values()
        ),
        "promoted_work_loop_zero_residue": cleanup_remaining == 0,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifact_count": closure["artifact_count"],
        "process_count": closure["process_count"],
        "background_process_count": len(background_checks),
        "api_import_count": len(api_imports),
        "database_count": len(identities),
        "database_identities": identities,
        "migrations": migrations,
        "background_checks": background_checks,
        "api_imports": api_imports,
        "promoted_components": {
            name: {
                "status": item.get("status"),
                "evidence_classification": item.get("evidence_classification"),
                "check_count": len(item.get("checks") or {}),
            }
            for name, item in component_evidence.items()
        },
        "cleanup_remaining": cleanup_remaining,
        "topology_digest": semantic_sha256_hash_ref(
            {
                "domain": "nex.gb2.current-process-topology",
                "process_ids": [item.process_id for item in manifest.processes],
                "artifact_count": closure["artifact_count"],
                "database_services": sorted(identities),
            }
        ),
    }


def _database_identity_and_migrations(
    target: ResolvedPostgresTestTarget,
) -> dict[str, Any]:
    with (
        psycopg.connect(psycopg_database_url(target.database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        database, role = cursor.fetchone()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = tuple(row[0] for row in cursor.fetchall())
    return {"database": database, "role": role, "migration_versions": versions}


def _protected_environment(
    environ: Mapping[str, str],
    targets: Sequence[ResolvedPostgresTestTarget],
) -> dict[str, str]:
    result = dict(environ)
    result["NEX_PROFILE"] = "test"
    for index, name in enumerate(CURRENT_SERVICE_ENDPOINT_ENV_NAMES, start=1):
        result.setdefault(name, f"http://127.0.0.1:{19000 + index}")
    for index, name in enumerate(CURRENT_SIGNED_TRUST_ENV_NAMES, start=1):
        result.setdefault(name, f"gb2-s08-bounded-fixture-{index}")
    for item in targets:
        result[item.target.test_database_env] = item.database_url
        result[item.target.runtime_database_env] = item.database_url
    return result


def _run_background_checks(manifest, environment: Mapping[str, str]) -> dict[str, Any]:
    process_by_id = {item.process_id: item for item in manifest.processes}
    results = {}
    for process_id in CURRENT_BACKGROUND_PROCESS_IDS:
        command = (*process_by_id[process_id].command, "--check")
        payload = _run_json_command(command, environment)
        if process_id == "nex-wa-evidence-consumer":
            passed = payload.get("readiness_status") == "READY"
        elif process_id in {
            "nex-ae-agent-runtime-worker",
            "nex-wc-event-delivery-worker",
            "nex-eos-outbox-publisher",
        }:
            passed = (
                payload.get("status") == "PASS"
                and payload.get("readiness_status") == "READY"
            )
        else:
            passed = payload.get("lifecycle_ready") is True
        results[process_id] = {
            "passed": passed,
            "work_capability": payload.get("work_capability"),
            "readiness_status": payload.get("readiness_status"),
            "lifecycle_ready": payload.get("lifecycle_ready"),
        }
    return results


def _run_api_import_checks(environment: Mapping[str, str]) -> dict[str, bool]:
    code = (
        "import importlib,sys; importlib.import_module(sys.argv[1]); print('IMPORTED')"
    )
    return {
        module: _run_checked((str(PYTHON_BIN), "-c", code, module), environment)
        == "IMPORTED"
        for module in API_IMPORT_MODULES
    }


def _run_json_command(
    command: Sequence[str], environment: Mapping[str, str]
) -> dict[str, Any]:
    output = _run_checked(command, environment)
    try:
        return json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("background check returned invalid JSON") from exc


def _run_checked(command: Sequence[str], environment: Mapping[str, str]) -> str:
    child_environment = dict(environment)
    child_environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "services/_shared"), *(str(path) for path in SERVICE_SOURCE_ROOTS))
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=90.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"process check failed: {Path(command[0]).name} rc={completed.returncode}"
        )
    return completed.stdout.strip()


def _run_promoted_component_smokes(
    environ: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    return {
        "ae_agent_runtime_worker": s05.run_gb2_ca00_s05_ae_agent_runtime_worker(
            {**environ, s05.SMOKE_ENV: "1"}
        ),
        "wc_event_delivery_worker": s06.run_gb2_ca00_s06_wc_event_delivery_worker(
            {**environ, s06.SMOKE_ENV: "1"}
        ),
        "eos_outbox_publisher": s07.run_gb2_ca00_s07_eos_outbox_publisher(
            {**environ, s07.SMOKE_ENV: "1"}
        ),
    }


def _redact_detail(detail: str, environ: Mapping[str, str]) -> str:
    redacted = detail
    for target in CURRENT_POSTGRES_TEST_TARGETS:
        value = str(environ.get(target.test_database_env) or "")
        if value:
            redacted = redacted.replace(value, redact_database_url(value))
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S08",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "secret_included": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "gb2_ca00_s08_topology="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"classification={evidence.get('evidence_classification', 'none')} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"artifacts={evidence.get('artifact_count', 0)} "
        f"processes={evidence.get('process_count', 0)} "
        f"databases={evidence.get('database_count', 0)} "
        f"remaining={evidence.get('cleanup_remaining', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-S08 protected current process topology acceptance"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.update(read_env_file(ROOT / args.env_file))
    evidence = run_gb2_ca00_s08_current_process_topology(env)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
