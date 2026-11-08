from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
    OperationalEventEmitter,
    ServiceLogEmitter,
    WorkerHeartbeatEmitter,
)
from nex_wa import (
    ControlledWaEvidenceSourceAdapter,
    WaEvidenceConsumerError,
    WaEvidenceConsumerRuntime,
    WaEvidenceIntakeService,
    WaEvidenceSourceAdapterRegistry,
    WaPersistenceRuntime,
    WaSourceAdapterError,
    build_wa_evidence_consumer_config,
    build_wa_evidence_consumer_runtime,
    inspect_wa_evidence_job,
    normalize_evidence_intake_request,
    normalize_source_envelope,
    package_readiness,
    require_matching_source_envelope,
    run_wa_evidence_consumer_batch,
    run_wa_evidence_consumer_once,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 27, 11, 0, tzinfo=UTC)
WIRE_NOW = "2026-10-27T11:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "agent-execution-9200",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": WIRE_NOW,
        "correlation_id": "corr-p9-s08-001",
    }
    value.update(overrides)
    return value


def _registry(*source_types: str) -> WaEvidenceSourceAdapterRegistry:
    return WaEvidenceSourceAdapterRegistry(
        {
            source_type: ControlledWaEvidenceSourceAdapter(source_type)
            for source_type in source_types
        }
    )


def _full_registry() -> WaEvidenceSourceAdapterRegistry:
    return _registry("AE_AGENT_RESULT", "AE_ARTIFACT")


class _NonCallableAdapter:
    source_type = "AE_AGENT_RESULT"
    fetch = None


def _queued_job(
    queue: InMemoryJobQueue,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    service = WaEvidenceIntakeService(queue, clock=lambda: NOW)
    admission = service.admit(
        payload or _payload(),
        caller_service_id="nex-ae-api",
        request_id="request-p9-s08",
        trace_id="a" * 32,
    )
    job = queue.get_job(admission.job_id)
    assert job is not None
    return job


def _emitters():
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    log_store = InMemoryServiceLogStore()
    heartbeat = WorkerHeartbeatEmitter(
        service_id="nex-wa",
        worker_id="wa-worker-test",
        worker_type="wa.evidence_consumer",
        store=heartbeat_store,
        started_at=WIRE_NOW,
    )
    logger = ServiceLogEmitter(
        service_id="nex-wa",
        logger_name="nex-wa-evidence-consumer",
        store=log_store,
    )
    return heartbeat, heartbeat_store, logger, log_store


def test_registry_readiness_requires_both_external_source_adapters() -> None:
    partial = _registry("AE_AGENT_RESULT")
    complete = _full_registry()

    assert partial.readiness() == {
        "name": "wa_source_adapters",
        "ok": False,
        "registered_source_types": ["AE_AGENT_RESULT"],
        "missing_source_types": ["AE_ARTIFACT"],
    }
    assert complete.readiness()["ok"] is True
    assert package_readiness()["domain_processing_enabled"] is False
    assert package_readiness(complete)["domain_processing_enabled"] is True


@pytest.mark.parametrize(
    "adapters",
    [
        [],
        {"WC_WORK_RESULT": ControlledWaEvidenceSourceAdapter("AE_AGENT_RESULT")},
        {"AE_ARTIFACT": ControlledWaEvidenceSourceAdapter("AE_AGENT_RESULT")},
        {"AE_AGENT_RESULT": object()},
        {"AE_AGENT_RESULT": _NonCallableAdapter()},
    ],
)
def test_registry_rejects_invalid_adapter_configuration(adapters: object) -> None:
    with pytest.raises(WaSourceAdapterError) as caught:
        WaEvidenceSourceAdapterRegistry(adapters)  # type: ignore[arg-type]

    assert caught.value.error_code == "WA_SOURCE_ADAPTER_REGISTRY_INVALID"
    assert caught.value.retryable is False


def test_controlled_adapter_rejects_invalid_configuration() -> None:
    with pytest.raises(WaSourceAdapterError) as unsupported:
        ControlledWaEvidenceSourceAdapter("WC_WORK_RESULT")
    with pytest.raises(WaSourceAdapterError, match="non-empty"):
        ControlledWaEvidenceSourceAdapter("AE_AGENT_RESULT", source_owner="")
    with pytest.raises(WaSourceAdapterError, match="exceeds 128"):
        ControlledWaEvidenceSourceAdapter(
            "AE_AGENT_RESULT",
            source_owner="x" * 129,
        )
    assert unsupported.value.error_code == "WA_SOURCE_ADAPTER_INVALID"


def test_controlled_adapter_and_envelope_are_reference_only() -> None:
    request = normalize_evidence_intake_request(_payload())
    adapter = ControlledWaEvidenceSourceAdapter(
        "AE_AGENT_RESULT",
        source_owner="nex-ae-api",
    )
    envelope = normalize_source_envelope(adapter.fetch(request))

    assert envelope.source_owner == "nex-ae-api"
    require_matching_source_envelope(request, envelope)
    assert set(envelope.to_dict()) == {
        "schema_version",
        "tenant_id",
        "source_owner",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "inspection_status",
    }


def test_source_envelope_positive_and_negative_contract_fixtures() -> None:
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (
            ROOT
            / "contracts/schemas/service/nex_wa/wa_source_normalized_envelope.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    positive = json.loads(
        (
            ROOT
            / "contracts/examples/service/wa_source_normalized_envelope.available.json"
        ).read_text(encoding="utf-8")
    )
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/service/wa_source_normalized_envelope.raw_payload.json"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(positive)
    assert list(validator.iter_errors(negative))


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ({"raw_payload": "forbidden"}, "WA_SOURCE_ENVELOPE_PAYLOAD_FORBIDDEN"),
        ({"source_hash": "bad"}, "WA_SOURCE_ENVELOPE_INVALID"),
        ({"inspection_status": "TRUSTED"}, "WA_SOURCE_ENVELOPE_INVALID"),
        ({"source_type": "WC_WORK_RESULT"}, "WA_SOURCE_ENVELOPE_INVALID"),
        ({"schema_version": "v2"}, "WA_SOURCE_ENVELOPE_INVALID"),
    ],
)
def test_source_envelope_rejects_raw_or_unsupported_values(
    mutation: dict[str, object],
    error_code: str,
) -> None:
    request = normalize_evidence_intake_request(_payload())
    value = ControlledWaEvidenceSourceAdapter("AE_AGENT_RESULT").fetch(request).to_dict()
    value.update(mutation)

    with pytest.raises(WaSourceAdapterError) as caught:
        normalize_source_envelope(value)

    assert caught.value.error_code == error_code


def test_envelope_missing_non_mapping_mismatch_and_adapter_mismatch_fail() -> None:
    request = normalize_evidence_intake_request(_payload())
    envelope = ControlledWaEvidenceSourceAdapter("AE_AGENT_RESULT").fetch(request)
    missing = envelope.to_dict()
    del missing["source_ref"]
    with pytest.raises(WaSourceAdapterError, match="missing fields"):
        normalize_source_envelope(missing)
    with pytest.raises(WaSourceAdapterError, match="must be an object"):
        normalize_source_envelope([])  # type: ignore[arg-type]
    with pytest.raises(WaSourceAdapterError) as mismatch:
        require_matching_source_envelope(
            request,
            replace(envelope, source_hash="sha256:" + "b" * 64),
        )
    assert mismatch.value.error_code == "WA_SOURCE_ENVELOPE_MISMATCH"
    with pytest.raises(WaSourceAdapterError) as adapter_mismatch:
        ControlledWaEvidenceSourceAdapter("AE_ARTIFACT").fetch(request)
    assert adapter_mismatch.value.error_code == "WA_SOURCE_ADAPTER_REQUEST_MISMATCH"


def test_consumer_claims_inspects_completes_and_emits_heartbeat_and_logs() -> None:
    queue = InMemoryJobQueue()
    job = _queued_job(queue)
    heartbeat, heartbeat_store, logger, log_store = _emitters()
    event_store = InMemoryOperationalEventStore()

    result = run_wa_evidence_consumer_once(
        queue=queue,
        registry=_full_registry(),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
        operational_event_emitter=OperationalEventEmitter(
            service_id="nex-wa",
            store=event_store,
        ),
        worker_id="wa-worker-test",
        clock=lambda: WIRE_NOW,
    )

    assert result.status == "SUCCEEDED"
    assert result.handler_result == {
        "source_inspection": "VERIFIED",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "agent-execution-9200",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "a" * 64,
        "source_owner": "controlled-test",
    }
    assert queue.get_job(job["job_id"])["status"] == "SUCCEEDED"
    heartbeat_record = heartbeat_store.get_heartbeat("nex-wa", "wa-worker-test")
    assert heartbeat_record is not None
    assert heartbeat_record["status"] == "IDLE"
    assert len(log_store.entries) == 4
    outcome = next(
        item
        for item in log_store.entries.values()
        if item["message"] == "WA evidence consumer outcome recorded."
    )
    assert outcome["attributes"] == {
        "source_type": "AE_AGENT_RESULT",
        "status": "SUCCEEDED",
    }
    assert event_store.list_events(limit=10)[0]["event_type"] == (
        "wa.evidence.admitted"
    )


class _FailingAdapter:
    source_type = "AE_AGENT_RESULT"

    def fetch(self, request):
        raise WaSourceAdapterError("WA_SOURCE_TEMPORARY_FAILURE", "source unavailable")


def test_handler_failure_retries_and_unknown_adapter_fails_closed() -> None:
    for registry, expected_code in (
        (
            WaEvidenceSourceAdapterRegistry({"AE_AGENT_RESULT": _FailingAdapter()}),
            "WA_SOURCE_TEMPORARY_FAILURE",
        ),
        (_registry("AE_ARTIFACT"), "WA_SOURCE_ADAPTER_UNAVAILABLE"),
    ):
        queue = InMemoryJobQueue()
        job = _queued_job(queue)
        heartbeat, _heartbeat_store, _logger, _log_store = _emitters()

        result = run_wa_evidence_consumer_once(
            queue=queue,
            registry=registry,
            heartbeat_emitter=heartbeat,
            worker_id="wa-worker-test",
            clock=lambda: WIRE_NOW,
        )

        assert result.status == "FAILED"
        assert result.error_code == expected_code
        stored = queue.get_job(job["job_id"])
        assert stored is not None
        assert stored["status"] == "QUEUED"
        assert stored["attempt_count"] == 1


def test_raw_job_payload_is_rejected_without_source_adapter_call() -> None:
    queue = InMemoryJobQueue()
    job = _queued_job(queue)
    queue.jobs[job["job_id"]]["payload"]["document_body"] = "raw"
    heartbeat, _heartbeat_store, _logger, _log_store = _emitters()

    result = run_wa_evidence_consumer_once(
        queue=queue,
        registry=_full_registry(),
        heartbeat_emitter=heartbeat,
        worker_id="wa-worker-test",
        clock=lambda: WIRE_NOW,
    )

    assert result.status == "FAILED"
    assert result.error_code == "WA_CONSUMER_PAYLOAD_INVALID"
    assert queue.get_job(job["job_id"])["status"] == "QUEUED"


def test_batch_stops_on_idle_after_processing_available_jobs() -> None:
    queue = InMemoryJobQueue()
    _queued_job(queue, payload=_payload(source_ref="execution-1"))
    _queued_job(queue, payload=_payload(source_ref="execution-2"))
    heartbeat, _heartbeat_store, logger, _log_store = _emitters()

    result = run_wa_evidence_consumer_batch(
        queue=queue,
        registry=_full_registry(),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
        worker_id="wa-worker-test",
        max_jobs=3,
        clock=lambda: WIRE_NOW,
    )

    assert result.claimed_count == 2
    assert result.succeeded_count == 2
    assert result.idle_count == 1


def test_runtime_readiness_run_and_graceful_stop() -> None:
    queue = InMemoryJobQueue()
    _queued_job(queue)
    heartbeat, heartbeat_store, logger, _log_store = _emitters()
    persistence = SimpleNamespace(
        job_queue=queue,
        migration_readiness=lambda: {"name": "migrations", "ok": True},
        consumer_storage_readiness=lambda: {"name": "storage", "ok": True},
    )
    runtime = WaEvidenceConsumerRuntime(
        persistence=persistence,  # type: ignore[arg-type]
        registry=_full_registry(),
        config=build_wa_evidence_consumer_config(worker_id="wa-worker-test"),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
    )

    assert runtime.readiness()["domain_processing_enabled"] is True
    assert runtime.run_once(clock=lambda: WIRE_NOW).status == "SUCCEEDED"
    stopping, stopped = runtime.stop(observed_at=WIRE_NOW)
    assert stopping["status"] == "STOPPING"
    assert stopped["status"] == "STOPPED"
    assert heartbeat_store.get_heartbeat("nex-wa", "wa-worker-test")["status"] == (
        "STOPPED"
    )


def test_runtime_refuses_start_when_a_dependency_is_not_ready() -> None:
    heartbeat, _heartbeat_store, logger, _log_store = _emitters()
    runtime = WaEvidenceConsumerRuntime(
        persistence=SimpleNamespace(  # type: ignore[arg-type]
            job_queue=InMemoryJobQueue(),
            migration_readiness=lambda: {"name": "migrations", "ok": False},
            consumer_storage_readiness=lambda: {"name": "storage", "ok": True},
        ),
        registry=_full_registry(),
        config=build_wa_evidence_consumer_config(worker_id="wa-worker-test"),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
    )

    with pytest.raises(WaEvidenceConsumerError) as caught:
        runtime.run_once(clock=lambda: WIRE_NOW)
    assert caught.value.error_code == "WA_CONSUMER_NOT_READY"


def test_persistence_consumer_storage_readiness_checks_required_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(bind=engine)
    required = (
        "service_jobs",
        "service_worker_heartbeats",
        "wa_work_evidence",
        "wa_work_asset",
        "wa_work_asset_evidence",
        "service_operational_events",
        "service_log_entries",
    )
    with engine.begin() as connection:
        for table_name in required:
            connection.execute(text(f"CREATE TABLE {table_name} (id INTEGER)"))
    ready = WaPersistenceRuntime.consumer_storage_readiness(
        SimpleNamespace(worker_session_factory=sessions)  # type: ignore[arg-type]
    )
    engine.dispose()
    broken = WaPersistenceRuntime.consumer_storage_readiness(
        SimpleNamespace(worker_session_factory=sessions)  # type: ignore[arg-type]
    )

    assert ready["ok"] is True
    assert ready["required_tables"] == list(required)
    assert broken == {
        "name": "wa_consumer_storage",
        "ok": False,
        "error_code": "WA_CONSUMER_STORAGE_READINESS_FAILED",
    }


def test_runtime_builder_composes_shared_queue_heartbeat_and_log_components() -> None:
    persistence = SimpleNamespace(
        job_queue=InMemoryJobQueue(),
        worker_heartbeat_store=InMemoryWorkerHeartbeatStore(),
    )
    log_store = InMemoryServiceLogStore()

    runtime = build_wa_evidence_consumer_runtime(
        persistence=persistence,  # type: ignore[arg-type]
        registry=_full_registry(),
        worker_id="wa-runtime-builder",
        service_log_store=log_store,
    )

    assert runtime.config.worker_type == "wa.evidence_consumer"
    assert runtime.config.job_type == "WA_EVIDENCE_INGEST"
    assert runtime.heartbeat_emitter.store is persistence.worker_heartbeat_store
    assert runtime.service_log_emitter.store is log_store


def test_inspection_rejects_non_job_and_non_object_payload() -> None:
    with pytest.raises(WaEvidenceConsumerError, match="common Job"):
        inspect_wa_evidence_job({}, registry=_full_registry())
    with pytest.raises(WaEvidenceConsumerError, match="reference-only object"):
        inspect_wa_evidence_job(
            {"job_type": "WA_EVIDENCE_INGEST", "payload": []},
            registry=_full_registry(),
        )
