from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import (
    WA_EVIDENCE_DETAIL_READ_SCOPE,
    WA_EVIDENCE_READ_SCOPE,
    WaEvidenceIntakeService,
    WaFencedJobQueue,
    WorkAssetBindingInput,
    WorkAssetInput,
    WorkEvidenceInput,
    deterministic_work_evidence_id,
)
from nex_wa.app import create_wa_app
from nex_wa.consumer_main import check_consumer_readiness
from nex_wa.persistence import build_wa_persistence_runtime
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S10_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S10_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def _wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def test_actual_postgres_core_foundation_protected_acceptance() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    run_service_migrations("nex-wa", database_url=database_url, profile="test")

    environ = {
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p9-s10",
        "NEX_BUILD_SHA": "p9s10postgres",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        "NEX_WA_DATABASE_URL": database_url,
        "NEX_WA_DB_POOL_SIZE": "4",
        "NEX_WA_DB_MAX_OVERFLOW": "2",
        "NEX_WA_DB_WORKER_POOL_SIZE": "4",
        "NEX_WA_DB_WORKER_MAX_OVERFLOW": "2",
    }
    persistence = build_wa_persistence_runtime(environ=environ)
    suffix = uuid4().hex
    tenant_id = f"P9S10-{suffix}"
    now = datetime.now(UTC)
    now_wire = _wire(now)
    old_wire = _wire(now - timedelta(minutes=10))
    intake = WaEvidenceIntakeService(persistence.job_queue, clock=lambda: now)
    job_ids: list[str] = []

    def payload(source_ref: str):
        return {
            "schema_version": "wa_evidence_intake_request.v1",
            "tenant_id": tenant_id,
            "source_type": "AE_AGENT_RESULT",
            "source_ref": source_ref,
            "source_revision_ref": "result-1",
            "source_hash": "sha256:" + "7" * 64,
            "occurred_at": now_wire,
            "correlation_id": f"corr-{source_ref}",
        }

    try:
        readiness = check_consumer_readiness(
            environ,
            persistence_builder=lambda **_: build_wa_persistence_runtime(
                environ=environ
            ),
        )
        assert readiness["readiness_status"] == "READY"

        admissions = [
            intake.admit(
                payload(f"duplicate-{suffix}"),
                caller_service_id="nex-ae-api",
                request_id=f"request-duplicate-{index}",
                trace_id="a" * 32,
            )
            for index in range(100)
        ]
        assert len({item.job_id for item in admissions}) == 1
        job_ids.append(admissions[0].job_id)

        for index in range(2):
            admitted = intake.admit(
                payload(f"parallel-{index}-{suffix}"),
                caller_service_id="nex-ae-api",
                request_id=f"request-parallel-{index}",
                trace_id="b" * 32,
            )
            job_ids.append(admitted.job_id)

        def claim(worker_id: str):
            fenced = WaFencedJobQueue(
                persistence.job_queue, persistence.job_fence_store
            )
            job = fenced.claim_next_job(worker_id, updated_at=now_wire)
            assert job is not None
            fenced.complete_job(job["job_id"], updated_at=now_wire)
            return job["job_id"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = tuple(executor.map(claim, ("p9-s10-worker-1", "p9-s10-worker-2")))
        assert len(set(claimed)) == 2

        stale_job_id = next(job_id for job_id in job_ids if job_id not in claimed)
        persistence.job_queue.claim_next_job("p9-s10-crashed", updated_at=now_wire)
        with persistence.worker_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE service_jobs SET locked_at=:old "
                    "WHERE job_id=:job_id AND status='RUNNING'"
                ),
                {"old": old_wire, "job_id": stale_job_id},
            )
        recovered = persistence.job_fence_store.recover_stale(
            observed_at=now_wire, stale_after_seconds=60
        )
        assert [item["job_id"] for item in recovered] == [stale_job_id]
        replacement = WaFencedJobQueue(
            persistence.job_queue, persistence.job_fence_store
        )
        assert replacement.claim_next_job(
            "p9-s10-replacement", updated_at=now_wire
        )["job_id"] == stale_job_id
        replacement.complete_job(stale_job_id, updated_at=now_wire)

        evidence_id = deterministic_work_evidence_id(
            tenant_id=tenant_id,
            source_type="AE_AGENT_RESULT",
            source_ref=f"committed-{suffix}",
            source_revision_ref="result-1",
        )
        evidence_input = WorkEvidenceInput(
            tenant_id=tenant_id,
            source_owner="nex-ae-api",
            source_type="AE_AGENT_RESULT",
            source_ref=f"committed-{suffix}",
            source_revision_ref="result-1",
            source_hash="sha256:" + "8" * 64,
            evidence_kind="AGENT_EXECUTION_RESULT",
            actor_type="AGENT",
            actor_ref=f"agent-{suffix}",
            occurred_at=now,
            observed_at=now,
            classification="CONFIDENTIAL",
            agent_type_snapshot="IA",
        )
        asset_input = WorkAssetInput(
            tenant_id=tenant_id,
            asset_type="AGENT_EXECUTION_RESULT",
            agent_execution_id=f"execution-{suffix}",
            actor_type="AGENT",
            actor_ref=f"agent-{suffix}",
            occurred_at=now,
            classification="CONFIDENTIAL",
            agent_type_snapshot="IA",
            bindings=(WorkAssetBindingInput(evidence_id, "PRIMARY"),),
        )
        try:
            first = persistence.evidence_admission_service.admit_normalized_evidence(
                evidence_input, asset_input
            )
            raise RuntimeError("simulated crash after committed local unit of work")
        except RuntimeError:
            pass
        replay = persistence.evidence_admission_service.admit_normalized_evidence(
            evidence_input, asset_input
        )
        assert replay == first

        app = create_wa_app(
            environ=environ,
            persistence_builder=lambda **_: persistence,
        )
        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-wa",
            scopes=(
                DEFAULT_SERVICE_SCOPE,
                WA_EVIDENCE_READ_SCOPE,
                WA_EVIDENCE_DETAIL_READ_SCOPE,
            ),
        ).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "X-NeX-Tenant-Id": tenant_id,
        }
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/ready").json()["readiness_status"] == "READY"
            assert client.get(
                f"/internal/v1/work-evidence/{first.evidence.work_evidence_id}",
                headers=headers,
            ).status_code == 200
            lineage = client.get(
                f"/internal/v1/work-assets/{first.asset.work_asset_id}/evidence",
                headers=headers,
            )
            assert lineage.status_code == 200
            assert len(lineage.json()["items"]) == 1

        with persistence.api_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wa_work_asset_evidence "
                    "WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 1
    finally:
        with persistence.api_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wa_work_asset_evidence WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM wa_work_asset WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM wa_work_evidence WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM service_jobs WHERE job_id = ANY(:job_ids)"),
                {"job_ids": job_ids},
            )
        with persistence.api_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id) + "
                    "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id) + "
                    "(SELECT count(*) FROM wa_work_asset_evidence WHERE tenant_id=:tenant_id)"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 0
            assert connection.execute(
                text("SELECT count(*) FROM service_jobs WHERE job_id = ANY(:job_ids)"),
                {"job_ids": job_ids},
            ).scalar_one() == 0
        persistence.dispose()
