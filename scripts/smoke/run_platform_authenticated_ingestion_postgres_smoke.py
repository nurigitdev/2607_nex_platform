#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import mkdtemp
from time import monotonic, sleep
from typing import Any, Mapping
from uuid import uuid4

import httpx
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services/_shared", ROOT / "scripts/smoke"):
    sys.path.insert(0, str(path))

from nex_runtime import build_engine, load_env_file  # noqa: E402
import run_platform_oa_backed_trust_postgres_smoke as trust  # noqa: E402


SMOKE_ENV = "NEX_PLATFORM_AUTHENTICATED_INGESTION_POSTGRES_SMOKE"
SCHEMA_VERSION = "platform_authenticated_ingestion_postgres_smoke.v1"
SOURCE_SENTINEL = "S135 private source sentinel"


def run_smoke(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    run_suffix = uuid4().hex[:12]
    run_prefix = f"s135-{run_suffix}"
    work_root = Path(mkdtemp(prefix="nex-s135-", dir="/tmp"))
    processes: list[subprocess.Popen[bytes]] = []
    browser = httpx.Client(timeout=15.0)
    configured: dict[str, str] = {}
    context: dict[str, Any] = {}
    identifiers: dict[str, str] = {}
    engines: dict[str, Any] = {}
    try:
        migrations = trust.run_platform_test_migration_readiness(env)
        configured = trust._runtime_environment(env, work_root=work_root)
        configured.update(
            NEX_AE_UPLOAD_OWNER_RESOLVER_MODE="disabled",
            NEX_CX_UPLOAD_OWNER_RESOLVER_MODE="disabled",
        )
        context = trust._seed_oa_trust(
            configured,
            run_prefix=run_prefix,
            work_root=work_root,
        )
        oa_process = trust._start_service("nex-oa", configured)
        processes.append(oa_process)
        trust._wait_for_database_ready(configured["NEX_OA_BASE_URL"], oa_process)
        tokens = trust._issue_runtime_tokens(
            configured["NEX_OA_BASE_URL"], context, run_prefix
        )
        service_envs = trust._service_environments(configured, tokens)
        mo_process = trust._start_service("nex-mo", service_envs["nex-mo"])
        processes.append(mo_process)
        trust._wait_for_database_ready(configured["NEX_MO_BASE_URL"], mo_process)

        cx_process, ae_process = _start_journey_apis(service_envs, configured)
        processes.extend((cx_process, ae_process))
        login = trust._json_request(
            browser,
            "POST",
            f"{configured['NEX_AE_API_BASE_URL']}/api/v1/auth/session/login",
            headers=trust._trace_headers(f"{run_prefix}-login", uuid4().hex),
            json={
                "tenant_id": context["tenant_id"],
                "employee_id": context["employee_id"],
                "password": context["user_secret"],
                "requested_scopes": ["workspace:use"],
                "ttl_seconds": 1200,
            },
            expected_status=200,
        )
        source = (
            f"# Authenticated ingestion\n\n{SOURCE_SENTINEL} {run_suffix}.\n\n"
            "This document proves durable extraction, chunking, indexing, and restart."
        )
        upload = trust._json_request(
            browser,
            "POST",
            f"{configured['NEX_AE_API_BASE_URL']}/api/v1/uploads",
            headers=trust._trace_headers(f"{run_prefix}-upload", uuid4().hex),
            json={
                "workspace_id": f"workspace-{run_prefix}",
                "filename": f"{run_prefix}.md",
                "content_type": "text/markdown",
                "content_text": source,
            },
            expected_status=202,
        )
        identifiers = _journey_identifiers(upload)
        engines = {
            "ae": build_engine(configured["NEX_AE_DATABASE_URL"]),
            "cx": build_engine(configured["NEX_CX_DATABASE_URL"]),
        }

        worker = _start_worker(service_envs["nex-cx"])
        processes.append(worker)
        progress = _wait_for_index_ready(
            browser,
            configured["NEX_AE_API_BASE_URL"],
            identifiers["upload_handoff_id"],
            worker,
            run_prefix=run_prefix,
        )
        _stop_one(processes, worker)

        database = _observe_database(
            engines,
            identifiers=identifiers,
            tenant_id=context["tenant_id"],
            subject_id=context["subject_id"],
        )
        denial = _owner_denial(
            configured,
            tokens,
            identifiers["document_id"],
            context["tenant_id"],
            run_prefix,
        )
        unauthenticated = httpx.get(
            f"{configured['NEX_AE_API_BASE_URL']}/api/v1/uploads/"
            f"{identifiers['upload_handoff_id']}/progress",
            timeout=10.0,
        )

        _stop_one(processes, ae_process)
        _stop_one(processes, cx_process)
        cx_restart, ae_restart = _start_journey_apis(service_envs, configured)
        processes.extend((cx_restart, ae_restart))
        restored = trust._json_request(
            browser,
            "GET",
            f"{configured['NEX_AE_API_BASE_URL']}/api/v1/uploads/"
            f"{identifiers['upload_handoff_id']}/progress",
            headers=trust._trace_headers(f"{run_prefix}-restart", uuid4().hex),
            expected_status=200,
        )

        evidence = build_evidence(
            migration_service_count=len(migrations.services),
            login=login,
            upload=upload,
            progress=progress,
            restored=restored,
            database=database,
            owner_denial=denial,
            unauthenticated_status=unauthenticated.status_code,
        )
        _assert_redacted(evidence, env, source=source, context=context, tokens=tokens)

        trust._stop_processes(processes)
        cleanup = _cleanup_journey(
            engines,
            identifiers=identifiers,
            tenant_id=context["tenant_id"],
            subject_id=context["subject_id"],
            run_prefix=run_prefix,
        )
        oa_residue = trust._cleanup_oa(configured, context, run_prefix=run_prefix)
        context = {}
        _dispose_engines(engines)
        engines = {}
        shutil.rmtree(work_root)
        evidence["cleanup"] = {
            **cleanup,
            "oa_residue_count": oa_residue,
            "storage_residue_count": int(work_root.exists()),
        }
        evidence["checks"]["cleanup_residue_free"] = all(
            value == 0 for value in evidence["cleanup"].values()
        )
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "authenticated_ingestion_check_failed"
        return evidence
    except Exception as exc:  # pragma: no cover - protected integration diagnostics
        detail = (
            str(exc)
            if isinstance(exc, (RuntimeError, TimeoutError))
            else exc.__class__.__name__
        )
        return _failure("execution_failed", detail)
    finally:
        trust._stop_processes(processes)
        if engines and identifiers and context:
            try:
                _cleanup_journey(
                    engines,
                    identifiers=identifiers,
                    tenant_id=context["tenant_id"],
                    subject_id=context["subject_id"],
                    run_prefix=run_prefix,
                )
            except Exception:
                pass
        _dispose_engines(engines)
        if configured and context:
            try:
                trust._cleanup_oa(configured, context, run_prefix=run_prefix)
            except Exception:
                pass
        browser.close()
        shutil.rmtree(work_root, ignore_errors=True)


def _start_journey_apis(
    service_envs: Mapping[str, Mapping[str, str]],
    configured: Mapping[str, str],
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]]:
    cx_process = trust._start_service("nex-cx", service_envs["nex-cx"])
    try:
        trust._wait_for_database_ready(configured["NEX_CX_BASE_URL"], cx_process)
        ae_process = trust._start_service(
            "nex-ae-api", service_envs["nex-ae-api"]
        )
        trust._wait_for_database_ready(configured["NEX_AE_API_BASE_URL"], ae_process)
    except Exception:
        if cx_process.poll() is None:
            cx_process.terminate()
            cx_process.wait(timeout=10)
        raise
    return cx_process, ae_process


def _start_worker(environ: Mapping[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        (
            sys.executable,
            "scripts/dev/run_background_process.py",
            "nex-cx-ingestion-worker",
            "--profile",
            "test",
            "--poll-interval-seconds",
            "0.1",
        ),
        cwd=ROOT,
        env=dict(environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_index_ready(
    client: httpx.Client,
    ae_url: str,
    upload_handoff_id: str,
    worker: subprocess.Popen[bytes],
    *,
    run_prefix: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    deadline = monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError("ingestion worker exited before completion")
        response = client.get(
            f"{ae_url}/api/v1/uploads/{upload_handoff_id}/progress",
            headers=trust._trace_headers(f"{run_prefix}-progress", uuid4().hex),
        )
        if response.status_code == 200:
            latest = response.json()
            if latest.get("status") == "INDEX_READY":
                return latest
            if latest.get("status") in {"FAILED", "CANCELLED"}:
                failure = latest.get("failure") or {}
                raise RuntimeError(
                    "ingestion terminal status="
                    f"{latest.get('status')} step={failure.get('failed_step')} "
                    f"error_code={failure.get('error_code')}"
                )
        else:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            latest = {
                "status": f"HTTP_{response.status_code}",
                "failure": {"error_code": problem.get("error_code")},
            }
        sleep(0.1)
    failure = latest.get("failure") or {}
    raise TimeoutError(
        "index readiness timed out from status="
        f"{latest.get('status')} error_code={failure.get('error_code')}"
    )


def _journey_identifiers(upload: Mapping[str, Any]) -> dict[str, str]:
    document_ref = upload.get("cx_document_ref")
    if not isinstance(document_ref, Mapping):
        raise RuntimeError("upload response omitted CX document reference")
    result = {
        "upload_handoff_id": str(upload.get("upload_handoff_id") or ""),
        "document_id": str(document_ref.get("document_id") or ""),
        "job_id": str(document_ref.get("ingestion_job_id") or ""),
    }
    if not all(result.values()):
        raise RuntimeError("upload response omitted durable identifiers")
    return result


def _observe_database(
    engines: Mapping[str, Any],
    *,
    identifiers: Mapping[str, str],
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any]:
    params = {**identifiers, "tenant_id": tenant_id, "subject_id": subject_id}
    with engines["ae"].connect() as connection:
        ae = connection.execute(
            text(
                "SELECT count(*) AS row_count, "
                "bool_and(tenant_id = :tenant_id AND owner_user_id = :subject_id) "
                "AS owner_match, "
                "bool_and(record_payload::text NOT LIKE '%content_text%') AS metadata_only "
                "FROM ae_upload_handoffs "
                "WHERE upload_handoff_id = :upload_handoff_id"
            ),
            params,
        ).mappings().one()
    with engines["cx"].connect() as connection:
        cx = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM cx_content_objects WHERE content_object_id = CAST(:document_id AS uuid)) AS content_count, "
                "(SELECT count(*) FROM cx_extraction_artifacts WHERE content_object_id = CAST(:document_id AS uuid)) AS extraction_count, "
                "(SELECT count(*) FROM cx_chunks WHERE content_object_id = CAST(:document_id AS uuid)) AS chunk_count, "
                "(SELECT count(*) FROM cx_ingest_runs WHERE document_id = CAST(:document_id AS uuid) AND status = 'SUCCEEDED') AS succeeded_run_count, "
                "(SELECT count(*) FROM service_jobs WHERE job_id = :job_id AND status = 'SUCCEEDED') AS succeeded_job_count, "
                "(SELECT count(*) FROM cx_vector_indexes WHERE content_object_id = CAST(:document_id AS uuid) AND status = 'READY') AS ready_index_count, "
                "(SELECT count(*) FROM cx_vectors WHERE content_object_id = CAST(:document_id AS uuid)) AS vector_count, "
                "(SELECT count(*) FROM cx_document_summaries WHERE content_object_id = CAST(:document_id AS uuid) AND status = 'READY') AS summary_count, "
                "(SELECT count(*) FROM cx_document_summary_embeddings se JOIN cx_document_summaries ds ON ds.document_summary_id = se.document_summary_id WHERE ds.content_object_id = CAST(:document_id AS uuid) AND se.status = 'READY') AS summary_embedding_count"
            ),
            params,
        ).mappings().one()
    return {
        "ae_handoff_count": int(ae["row_count"]),
        "ae_owner_match": ae["owner_match"] is True,
        "ae_metadata_only": ae["metadata_only"] is True,
        **{key: int(value) for key, value in cx.items()},
    }


def _owner_denial(
    configured: Mapping[str, str],
    tokens: Mapping[str, str],
    document_id: str,
    tenant_id: str,
    run_prefix: str,
) -> dict[str, Any]:
    response = httpx.get(
        f"{configured['NEX_CX_BASE_URL']}/api/v1/documents/"
        f"{document_id}/ingestion-runs",
        headers={
            **trust._trace_headers(f"{run_prefix}-wrong-owner", uuid4().hex),
            "Authorization": f"Bearer {tokens['ae_to_cx']}",
            "X-NEX-Tenant-ID": tenant_id,
            "X-NEX-Subject-ID": f"other-{run_prefix}",
        },
        timeout=10.0,
    )
    payload = response.json()
    return {
        "status_code": response.status_code,
        "run_count": int(payload.get("run_count", -1)),
    }


def build_evidence(
    *,
    migration_service_count: int,
    login: Mapping[str, Any],
    upload: Mapping[str, Any],
    progress: Mapping[str, Any],
    restored: Mapping[str, Any],
    database: Mapping[str, Any],
    owner_denial: Mapping[str, Any],
    unauthenticated_status: int,
) -> dict[str, Any]:
    checks = {
        "five_test_databases_migrated": migration_service_count == 5,
        "oa_login_active": login.get("status") == "ACTIVE",
        "ae_upload_accepted": upload.get("status") == "QUEUED",
        "owner_claim_propagated": database.get("ae_owner_match") is True,
        "ae_handoff_metadata_only": database.get("ae_metadata_only") is True,
        "durable_handoff_present": database.get("ae_handoff_count") == 1,
        "cx_source_extracted": database.get("extraction_count", 0) >= 1,
        "cx_chunks_persisted": database.get("chunk_count", 0) >= 1,
        "job_and_run_succeeded": (
            database.get("succeeded_job_count") == 1
            and database.get("succeeded_run_count") == 1
        ),
        "mock_embedding_vectors_ready": (
            database.get("ready_index_count") == 1
            and database.get("vector_count", 0) >= 1
        ),
        "summary_embedding_metadata_ready": (
            database.get("summary_count") == 1
            and database.get("summary_embedding_count") == 1
        ),
        "progress_index_ready": (
            progress.get("status") == "INDEX_READY"
            and progress.get("vector_index", {}).get("retrieval_usable") is True
        ),
        "restart_restored_progress": restored.get("status") == "INDEX_READY",
        "unauthenticated_denied": unauthenticated_status == 401,
        "cross_owner_hidden": (
            owner_denial.get("status_code") == 200
            and owner_denial.get("run_count") == 0
        ),
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1350",
        "requirement": "S135",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "profile": "test",
        "actual_http": True,
        "actual_postgresql": True,
        "provider_mode": "mock",
        "remote_provider_required": False,
        "restart_generation_count": 2,
        "database_observations": dict(database),
        "security": {
            "unauthenticated_status": unauthenticated_status,
            "cross_owner_status": owner_denial.get("status_code"),
            "cross_owner_run_count": owner_denial.get("run_count"),
        },
        "privacy": {
            "raw_source_included": False,
            "token_material_included": False,
            "credential_material_included": False,
            "database_url_included": False,
            "embedding_vector_included": False,
        },
        "checks": checks,
    }


def _cleanup_journey(
    engines: Mapping[str, Any],
    *,
    identifiers: Mapping[str, str],
    tenant_id: str,
    subject_id: str,
    run_prefix: str,
) -> dict[str, int]:
    params = {
        **identifiers,
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "request_prefix": f"{run_prefix}%",
    }
    with engines["ae"].begin() as connection:
        connection.execute(
            text(
                "DELETE FROM ae_upload_handoffs "
                "WHERE upload_handoff_id = :upload_handoff_id"
            ),
            params,
        )
    with engines["cx"].begin() as connection:
        source_file_id = connection.execute(
            text(
                "SELECT source_file_id FROM cx_content_objects "
                "WHERE content_object_id = CAST(:document_id AS uuid)"
            ),
            params,
        ).scalar_one_or_none()
        connection.execute(
            text(
                "DELETE FROM cx_vectors "
                "WHERE content_object_id = CAST(:document_id AS uuid)"
            ),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM cx_vector_indexes "
                "WHERE content_object_id = CAST(:document_id AS uuid)"
            ),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM cx_content_objects "
                "WHERE content_object_id = CAST(:document_id AS uuid)"
            ),
            params,
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE job_id = :job_id"), params
        )
        connection.execute(
            text(
                "DELETE FROM cx_prompt_render_events "
                "WHERE request_id LIKE :request_prefix"
            ),
            params,
        )
        if source_file_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_source_files WHERE source_file_id = :source_file_id "
                    "AND NOT EXISTS (SELECT 1 FROM cx_content_objects "
                    "WHERE source_file_id = :source_file_id)"
                ),
                {"source_file_id": source_file_id},
            )
    with engines["ae"].connect() as connection:
        ae_count = connection.execute(
            text(
                "SELECT count(*) FROM ae_upload_handoffs "
                "WHERE upload_handoff_id = :upload_handoff_id"
            ),
            params,
        ).scalar_one()
    with engines["cx"].connect() as connection:
        cx_count = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM cx_content_objects WHERE content_object_id = CAST(:document_id AS uuid)) + "
                "(SELECT count(*) FROM cx_ingest_runs WHERE document_id = CAST(:document_id AS uuid)) + "
                "(SELECT count(*) FROM cx_vector_indexes WHERE content_object_id = CAST(:document_id AS uuid)) + "
                "(SELECT count(*) FROM cx_vectors WHERE content_object_id = CAST(:document_id AS uuid)) + "
                "(SELECT count(*) FROM service_jobs WHERE job_id = :job_id) + "
                "(SELECT count(*) FROM cx_prompt_render_events WHERE request_id LIKE :request_prefix)"
            ),
            params,
        ).scalar_one()
        if source_file_id is not None:
            cx_count += connection.execute(
                text(
                    "SELECT count(*) FROM cx_source_files "
                    "WHERE source_file_id = :source_file_id"
                ),
                {"source_file_id": source_file_id},
            ).scalar_one()
    return {
        "ae_residue_count": int(ae_count),
        "cx_residue_count": int(cx_count),
    }


def _stop_one(
    processes: list[subprocess.Popen[bytes]], process: subprocess.Popen[bytes]
) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process in processes:
        processes.remove(process)


def _dispose_engines(engines: Mapping[str, Any]) -> None:
    for engine in engines.values():
        try:
            engine.dispose()
        except Exception:
            pass


def _assert_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
    *,
    source: str,
    context: Mapping[str, Any],
    tokens: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        source,
        SOURCE_SENTINEL,
        str(context.get("user_secret") or ""),
        *tokens.values(),
        *(value for key, value in environ.items() if "DATABASE_URL" in key),
    ]
    if any(value and value in serialized for value in protected):
        raise RuntimeError("protected material leaked into smoke evidence")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1350",
        "requirement": "S135",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(report: Mapping[str, Any]) -> str:
    if report.get("status") == "SKIPPED":
        return f"platform_authenticated_ingestion_postgres=skip reason={SMOKE_ENV}"
    if report.get("status") != "PASS":
        return (
            "platform_authenticated_ingestion_postgres=fail "
            f"code={report.get('failure_code')}"
        )
    database = report.get("database_observations") or {}
    cleanup = report.get("cleanup") or {}
    return (
        "platform_authenticated_ingestion_postgres=pass "
        f"chunks={database.get('chunk_count')} "
        f"vectors={database.get('vector_count')} "
        f"restart={report.get('restart_generation_count')} "
        f"residue={sum(int(value) for value in cleanup.values())} next=1351"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    report = run_smoke()
    print(summary_line(report) if args.summary else json.dumps(report, indent=2))
    return 1 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
