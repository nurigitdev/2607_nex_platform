from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import ceil
from time import perf_counter
from uuid import uuid4

import psycopg
import pytest
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import (
    AeAgentResultSourceAdapter,
    ControlledWaEvidenceSourceAdapter,
    WaEvidenceIntakeService,
    WaEvidenceSourceAdapterRegistry,
    build_wa_evidence_consumer_runtime,
    build_wa_persistence_runtime,
)
from run_migrations import run_service_migrations
from sqlalchemy import event, text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S26_POSTGRES_LOAD") != "1",
    reason="set NEX_WA_P9_S26_POSTGRES_LOAD=1 for actual nex_wa_test load smoke",
)

LOAD_SOURCE_COUNT = 100
CONSUMER_COUNT = 2
INTAKE_P95_BUDGET_MS = 500.0


class PoolTracker:
    def __init__(self, engine) -> None:
        self.current = 0
        self.maximum = 0
        self._lock = threading.Lock()
        event.listen(engine, "checkout", self._checkout)
        event.listen(engine, "checkin", self._checkin)

    def _checkout(self, *_args) -> None:
        with self._lock:
            self.current += 1
            self.maximum = max(self.maximum, self.current)

    def _checkin(self, *_args) -> None:
        with self._lock:
            self.current -= 1


class LoadAgentResultSource:
    def __init__(self, projections: dict[str, dict[str, object]]) -> None:
        self._projections = projections

    def fetch_result(self, *, tenant_id: str, result_id: str):
        projection = self._projections[result_id]
        assert projection["tenant_id"] == tenant_id
        return projection


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[ceil(len(ordered) * 0.95) - 1]


def test_actual_postgres_concurrent_intake_skip_locked_and_zero_residue() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(
            psycopg_database_url(database_url),
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    run_service_migrations("nex-wa", database_url=database_url, profile="test")

    runtime = build_wa_persistence_runtime(
        environ={
            "NEX_WA_TEST_DATABASE_URL": database_url,
            "NEX_WA_DB_POOL_SIZE": "8",
            "NEX_WA_DB_MAX_OVERFLOW": "4",
            "NEX_WA_DB_WORKER_POOL_SIZE": "4",
            "NEX_WA_DB_WORKER_MAX_OVERFLOW": "2",
            "NEX_WA_DB_POOL_TIMEOUT_SECONDS": "10",
            "NEX_WA_DB_WORKER_POOL_TIMEOUT_SECONDS": "10",
        },
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    api_pool = PoolTracker(runtime.api_engine)
    worker_pool = PoolTracker(runtime.worker_engine)
    suffix = uuid4().hex
    tenant_id = f"P9S26-{suffix}"
    trace_prefix = f"p9-s26-{suffix}"
    occurred_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    agent_id = str(uuid4())
    projections: dict[str, dict[str, object]] = {}
    payloads: list[dict[str, str]] = []

    def add_source(index: int) -> dict[str, str]:
        execution_id = str(uuid4())
        result_id = str(uuid4())
        source_hash = _hash(f"{suffix}:{index}")
        projections[result_id] = {
            "tenant_id": tenant_id,
            "result_id": result_id,
            "agent_execution_id": execution_id,
            "agent_id": agent_id,
            "agent_type": "IA",
            "project_id": None,
            "status": "SUCCEEDED",
            "result_hash": source_hash,
            "created_at": occurred_at,
            "agent_execution_state": "SUCCEEDED",
            "required_delivery_target_type": "WORKSPACE_RESULT",
            "required_delivery_state": "ACKNOWLEDGED",
            "source_work_item_ref": None,
            "source_claim_ref": None,
            "source_claim_generation": None,
            "source_assignment_ref": None,
        }
        return {
            "schema_version": "wa_evidence_intake_request.v1",
            "tenant_id": tenant_id,
            "source_type": "AE_AGENT_RESULT",
            "source_ref": execution_id,
            "source_revision_ref": result_id,
            "source_hash": source_hash,
            "occurred_at": occurred_at,
            "correlation_id": f"corr-{suffix}-{index}",
        }

    payloads.extend(add_source(index) for index in range(LOAD_SOURCE_COUNT))
    race_payload = add_source(LOAD_SOURCE_COUNT)
    intake = WaEvidenceIntakeService(runtime.intake_job_queue)
    latencies: list[float] = []
    latency_lock = threading.Lock()

    def admit(index: int, payload: dict[str, str]):
        started = perf_counter()
        result = intake.admit(
            payload,
            caller_service_id="nex-ae-api",
            request_id=f"{trace_prefix}-request-{index}",
            trace_id=f"{trace_prefix}-trace-{index}",
        )
        elapsed = (perf_counter() - started) * 1000.0
        with latency_lock:
            latencies.append(elapsed)
        return result

    consumers = []
    claimed_by_worker: dict[str, list[str]] = {}
    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            admissions = tuple(
                executor.map(
                    lambda item: admit(*item),
                    enumerate(payloads),
                )
            )
        assert len(admissions) == LOAD_SOURCE_COUNT
        assert len({item.job_id for item in admissions}) == LOAD_SOURCE_COUNT
        p95_ms = _p95(latencies)
        assert p95_ms <= INTAKE_P95_BUDGET_MS

        with ThreadPoolExecutor(max_workers=16) as executor:
            raced = tuple(
                executor.map(
                    lambda index: admit(LOAD_SOURCE_COUNT + index, race_payload),
                    range(16),
                )
            )
        assert len({item.job_id for item in raced}) == 1
        assert sum(item.idempotent_reuse for item in raced) == 15

        with runtime.api_engine.connect() as connection:
            queued_before = connection.execute(
                text(
                    "SELECT count(*) FROM service_jobs "
                    "WHERE payload->>'tenant_id'=:tenant_id AND status='QUEUED'"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        assert queued_before == LOAD_SOURCE_COUNT + 1

        registry = WaEvidenceSourceAdapterRegistry(
            {
                "AE_AGENT_RESULT": AeAgentResultSourceAdapter(
                    source=LoadAgentResultSource(projections),
                    admission=runtime.evidence_admission_service,
                ),
                "AE_ARTIFACT": ControlledWaEvidenceSourceAdapter("AE_ARTIFACT"),
            }
        )
        consumers = [
            build_wa_evidence_consumer_runtime(
                persistence=runtime,
                registry=registry,
                worker_id=f"p9-s26-worker-{suffix}-{index}",
            )
            for index in range(CONSUMER_COUNT)
        ]
        barrier = threading.Barrier(CONSUMER_COUNT)

        def consume(consumer):
            barrier.wait()
            claimed = []
            while True:
                result = consumer.run_once()
                if result.status == "IDLE":
                    break
                assert result.status == "SUCCEEDED"
                assert result.job is not None
                claimed.append(str(result.job["job_id"]))
            consumer.stop()
            return consumer.config.worker_id, claimed

        with ThreadPoolExecutor(max_workers=CONSUMER_COUNT) as executor:
            for worker_id, claimed in executor.map(consume, consumers):
                claimed_by_worker[worker_id] = claimed

        all_claimed = [
            job_id
            for claimed in claimed_by_worker.values()
            for job_id in claimed
        ]
        assert all(claimed_by_worker.values())
        assert len(all_claimed) == LOAD_SOURCE_COUNT + 1
        assert len(set(all_claimed)) == len(all_claimed)

        with runtime.api_engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM service_jobs "
                    " WHERE payload->>'tenant_id'=:tenant_id AND status='QUEUED'), "
                    "(SELECT count(*) FROM service_jobs "
                    " WHERE payload->>'tenant_id'=:tenant_id AND status='SUCCEEDED'), "
                    "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset_evidence "
                    " WHERE tenant_id=:tenant_id)"
                ),
                {"tenant_id": tenant_id},
            ).one()
        assert tuple(counts) == (
            0,
            LOAD_SOURCE_COUNT + 1,
            LOAD_SOURCE_COUNT + 1,
            LOAD_SOURCE_COUNT + 1,
            LOAD_SOURCE_COUNT + 1,
        )
        assert 0 < api_pool.maximum <= 12
        assert 0 < worker_pool.maximum <= 6
        assert api_pool.current == worker_pool.current == 0
        print(
            "p9_s26_postgres_load=pass "
            f"intake_requests={LOAD_SOURCE_COUNT} "
            f"semantic_jobs={LOAD_SOURCE_COUNT + 1} "
            f"consumers={len(claimed_by_worker)} "
            f"claims={','.join(str(len(value)) for value in claimed_by_worker.values())} "
            f"p95_ms={p95_ms:.3f} "
            f"api_pool_high_water={api_pool.maximum}/12 "
            f"worker_pool_high_water={worker_pool.maximum}/6"
        )
    finally:
        with runtime.api_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM service_log_entries "
                    "WHERE trace_id LIKE :trace_prefix"
                ),
                {"trace_prefix": f"{trace_prefix}%"},
            )
            connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE trace_id LIKE :trace_prefix"
                ),
                {"trace_prefix": f"{trace_prefix}%"},
            )
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id='nex-wa' AND worker_id LIKE :worker_prefix"
                ),
                {"worker_prefix": f"p9-s26-worker-{suffix}-%"},
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
                text(
                    "DELETE FROM service_jobs "
                    "WHERE payload->>'tenant_id'=:tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        with runtime.api_engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM service_jobs "
                    " WHERE payload->>'tenant_id'=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM service_worker_heartbeats "
                    " WHERE worker_id LIKE :worker_prefix)"
                ),
                {
                    "tenant_id": tenant_id,
                    "worker_prefix": f"p9-s26-worker-{suffix}-%",
                },
            ).one()
        assert tuple(residue) == (0, 0, 0, 0)
        runtime.dispose()
