from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_ae_api.runtime_resume import (
    ResumeRoute,
    ResumeTargetHandlerRegistry,
    RuntimeEventMatcher,
    RuntimeResumeError,
    SqlAlchemyProductPreparationResumeService,
    SqlAlchemyResumeRouteSource,
    deterministic_product_resume_job_id,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-6b1a3"
EXECUTION_ID = "11111111-1111-4111-8111-111111116b13"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222226b13"
CHECKPOINT_ID = "33333333-3333-4333-8333-333333336b13"
WAIT_ID = "44444444-4444-4444-8444-444444446b13"
EVENT_ID = "event-6b1a3"
NOW = "2026-11-17T08:00:00Z"
NOW_DT = datetime(2026, 11, 17, 8, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"


@pytest.fixture
def runtime_store():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _SCHEMA:
            connection.execute(text(statement))
        _seed_product_context(connection)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, sessions
    engine.dispose()


def _queue(sessions):
    return SqlAlchemyRuntimeJobQueue(sessions)


def test_product_event_match_is_atomic_step_less_and_exactly_replayable(
    runtime_store,
) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )

    first = service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    replay = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=_queue(sessions),
        clock=lambda: datetime(2026, 11, 17, 9, tzinfo=UTC),
    ).reconcile(tenant_id=TENANT, event_id=EVENT_ID)

    assert replay == first
    assert first["event_state"] == "MATCHED"
    assert first["wait_state"] == "RESUME_QUEUED"
    assert first["resume_target_kind"] == "PRODUCT_COORDINATOR"
    expected_job_id = deterministic_product_resume_job_id(
        tenant_id=TENANT, wait_id=WAIT_ID, event_id=EVENT_ID
    )
    assert first["resume_runtime_job_id"] == expected_job_id
    with engine.connect() as connection:
        job = (
            connection.execute(
                text(
                    "SELECT executable_step_id, wait_id, payload_json "
                    "FROM ae_runtime_job WHERE runtime_job_id = :job_id"
                ),
                {"job_id": expected_job_id},
            )
            .mappings()
            .one()
        )
        counts = (
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM ae_runtime_job) AS jobs, "
                    "(SELECT count(*) FROM ae_wait_registration "
                    "WHERE state = 'RESUME_QUEUED') AS waits, "
                    "(SELECT count(*) FROM ae_external_event_inbox "
                    "WHERE state = 'MATCHED') AS events"
                )
            )
            .mappings()
            .one()
        )
    assert job["executable_step_id"] is None
    assert job["wait_id"] == WAIT_ID
    assert "business_context" not in job["payload_json"]
    assert dict(counts) == {"jobs": 1, "waits": 1, "events": 1}


def test_product_lineage_drift_fails_closed_without_second_job(runtime_store) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_product_prep_event_binding "
                "SET coordinator_registration_hash = :hash "
                "WHERE tenant_id = :tenant AND event_id = :event"
            ),
            {"hash": HASH_B, "tenant": TENANT, "event": EVENT_ID},
        )

    with pytest.raises(RuntimeResumeError, match="lineage differs"):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)

    with engine.connect() as connection:
        job_count = connection.execute(
            text("SELECT count(*) FROM ae_runtime_job")
        ).scalar_one()
        states = (
            connection.execute(
                text(
                    "SELECT (SELECT state FROM ae_wait_registration) AS wait_state, "
                    "(SELECT state FROM ae_external_event_inbox) AS event_state"
                )
            )
            .mappings()
            .one()
        )
    assert job_count == 0
    assert dict(states) == {"wait_state": "PENDING", "event_state": "RECEIVED"}


def test_persisted_route_is_authoritative_and_handler_registry_is_targeted(
    runtime_store,
) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )
    result = service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    source = SqlAlchemyResumeRouteSource(sessions)

    route = source.resolve(
        tenant_id=TENANT, runtime_job_id=result["resume_runtime_job_id"]
    )
    assert route.resume_target_kind == "PRODUCT_COORDINATOR"
    assert route.executable_step_id is None
    assert route.product_context == {
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_hash": HASH_A,
        "coordinator_id": COORDINATOR_ID,
        "coordinator_version": "1.0.0",
        "coordinator_registration_hash": HASH_A,
        "work_intent_id": WORK_INTENT_ID,
    }

    observed = []
    registry = ResumeTargetHandlerRegistry(
        {
            "EXECUTABLE_STEP": lambda value: observed.append(("STEP", value.wait_id)),
            "PRODUCT_COORDINATOR": lambda value: observed.append(
                ("PRODUCT", value.wait_id)
            ),
        }
    )
    registry.dispatch(route)
    registry.dispatch(
        ResumeRoute(
            tenant_id=TENANT,
            runtime_job_id="step-job",
            execution_id=EXECUTION_ID,
            wait_id="step-wait",
            event_id="step-event",
            resume_target_kind="EXECUTABLE_STEP",
            executable_step_id="step-id",
            payload={"wait_id": "step-wait", "event_id": "step-event"},
        )
    )
    assert observed == [("PRODUCT", WAIT_ID), ("STEP", "step-wait")]

    with pytest.raises(RuntimeResumeError) as unavailable:
        ResumeTargetHandlerRegistry({"EXECUTABLE_STEP": lambda _route: None}).dispatch(
            route
        )
    assert unavailable.value.error_code == "ae.runtime_resume_handler_unavailable"

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_runtime_job SET payload_json = :payload "
                "WHERE runtime_job_id = :job_id"
            ),
            {
                "payload": '{"wait_id":"other","event_id":"event-6b1a3"}',
                "job_id": result["resume_runtime_job_id"],
            },
        )
    with pytest.raises(RuntimeResumeError, match="payload references differ"):
        source.resolve(tenant_id=TENANT, runtime_job_id=result["resume_runtime_job_id"])


def test_runtime_queue_enforces_target_specific_step_shape(runtime_store) -> None:
    _engine, sessions = runtime_store
    queue = _queue(sessions)
    common = {
        "tenant_id": TENANT,
        "runtime_job_id": "55555555-5555-4555-8555-555555556b13",
        "job_type": "RESUME_EXECUTION",
        "execution_id": EXECUTION_ID,
        "wait_id": WAIT_ID,
        "dedup_key": "shape-test",
        "run_after": NOW,
        "correlation_id": "correlation-6b1a3",
        "now": NOW,
        "payload": {"wait_id": WAIT_ID, "event_id": EVENT_ID},
    }
    with pytest.raises(RuntimeJobError, match="require executable_step_id"):
        queue.enqueue_unique(**common)
    with pytest.raises(RuntimeJobError, match="cannot reference executable_step_id"):
        queue.enqueue_unique(
            **common,
            executable_step_id="step-id",
            resume_target_kind="PRODUCT_COORDINATOR",
        )


def test_matcher_rejects_missing_stale_and_drifted_context(runtime_store) -> None:
    engine, sessions = runtime_store
    matcher = RuntimeEventMatcher(_queue(sessions))
    values = {
        "tenant_id": TENANT,
        "wait_id": WAIT_ID,
        "event_id": EVENT_ID,
        "execution_id": EXECUTION_ID,
        "executable_step_id": None,
        "resume_target_kind": "PRODUCT_COORDINATOR",
        "runtime_job_id": "55555555-5555-4555-8555-555555556b13",
        "dedup_key": "direct-matcher",
        "run_after": NOW,
        "correlation_id": "correlation-6b1a3",
        "now": NOW,
        "payload": {"wait_id": WAIT_ID, "event_id": EVENT_ID},
        "causation_id": EVENT_ID,
    }
    with sessions() as session:
        with pytest.raises(RuntimeResumeError, match="execution lineage"):
            matcher.match_in_session(
                session, **{**values, "execution_id": "different-execution"}
            )
        with pytest.raises(RuntimeResumeError, match="existing wait and event"):
            matcher.match_in_session(session, **{**values, "wait_id": "missing-wait"})
    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_wait_registration SET state = 'CANCELLED'"))
    with (
        sessions() as session,
        pytest.raises(RuntimeResumeError, match="not available"),
    ):
        matcher.match_in_session(session, **values)


@pytest.mark.parametrize(
    ("sql", "detail"),
    [
        (
            "UPDATE ae_wait_registration SET resume_target_kind = 'EXECUTABLE_STEP'",
            "resume target differs",
        ),
        (
            """UPDATE ae_external_event_inbox
            SET event_payload = '{"notification_ref":"changed"}'""",
            "notification lineage differs",
        ),
    ],
)
def test_product_target_and_notification_drift_fail_closed(
    runtime_store, sql, detail
) -> None:
    engine, sessions = runtime_store
    with engine.begin() as connection:
        connection.execute(text(sql))
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )

    with pytest.raises(RuntimeResumeError, match=detail):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM ae_runtime_job")).scalar_one()
            == 0
        )


def test_resume_public_boundaries_reject_invalid_inputs_and_missing_routes(
    runtime_store,
) -> None:
    _engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=_queue(sessions),
        clock=lambda: NOW_DT.replace(tzinfo=None),
    )
    with pytest.raises(RuntimeResumeError, match="timezone-aware"):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    with pytest.raises(RuntimeResumeError, match="was not found"):
        SqlAlchemyProductPreparationResumeService(
            sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
        ).reconcile(tenant_id=TENANT, event_id="missing-event")
    with pytest.raises(RuntimeResumeError) as missing_route:
        SqlAlchemyResumeRouteSource(sessions).resolve(
            tenant_id=TENANT, runtime_job_id="missing-job"
        )
    assert missing_route.value.error_code == "ae.runtime_resume_route_not_found"

    with pytest.raises(RuntimeResumeError, match="target kind"):
        ResumeTargetHandlerRegistry({"UNKNOWN": lambda _route: None})
    with pytest.raises(RuntimeResumeError, match="registration"):
        ResumeTargetHandlerRegistry(
            {"EXECUTABLE_STEP": None}  # type: ignore[dict-item]
        )
    with pytest.raises(RuntimeResumeError, match="route is invalid"):
        ResumeTargetHandlerRegistry({}).dispatch({})  # type: ignore[arg-type]


def test_exact_replay_lineage_drift_and_malformed_job_payload_are_denied(
    runtime_store,
) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )
    result = service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_wait_registration SET matched_event_id = 'other-event'")
        )
    with pytest.raises(RuntimeResumeError, match="resume lineage differs"):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_wait_registration SET matched_event_id = :event"),
            {"event": EVENT_ID},
        )
        connection.execute(
            text(
                "UPDATE ae_runtime_job SET payload_json = '{invalid' "
                "WHERE runtime_job_id = :job"
            ),
            {"job": result["resume_runtime_job_id"]},
        )
    with pytest.raises(RuntimeResumeError, match="valid JSON"):
        SqlAlchemyResumeRouteSource(sessions).resolve(
            tenant_id=TENANT, runtime_job_id=result["resume_runtime_job_id"]
        )


@pytest.mark.parametrize("race_target", ["wait", "event"])
def test_match_races_roll_back_job_and_state(runtime_store, race_target) -> None:
    engine, sessions = runtime_store

    class RaceQueue:
        def enqueue_resume_in_session(self, session, **values):
            table = (
                "ae_wait_registration"
                if race_target == "wait"
                else "ae_external_event_inbox"
            )
            session.execute(text(f"UPDATE {table} SET state = 'CANCELLED'"))
            return {"runtime_job_id": values["runtime_job_id"]}

    service = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=RaceQueue(),  # type: ignore[arg-type]
        clock=lambda: NOW_DT,
    )
    expected = "WaitRegistration" if race_target == "wait" else "External event"
    with pytest.raises(RuntimeResumeError, match=expected):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)

    with engine.connect() as connection:
        states = (
            connection.execute(
                text(
                    "SELECT (SELECT state FROM ae_wait_registration) AS wait_state, "
                    "(SELECT state FROM ae_external_event_inbox) AS event_state"
                )
            )
            .mappings()
            .one()
        )
    assert dict(states) == {"wait_state": "PENDING", "event_state": "RECEIVED"}


def test_queue_and_storage_failures_are_typed(runtime_store) -> None:
    _engine, sessions = runtime_store

    class FailingQueue:
        def enqueue_resume_in_session(self, *_args, **_kwargs):
            raise RuntimeJobError("queue.failed", "queue failed", True)

    service = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=FailingQueue(),  # type: ignore[arg-type]
        clock=lambda: NOW_DT,
    )
    with pytest.raises(RuntimeResumeError) as queue_error:
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    assert queue_error.value.error_code == "queue.failed"
    assert queue_error.value.retryable is True

    missing_engine = create_engine("sqlite+pysqlite:///:memory:")
    missing_sessions = sessionmaker(bind=missing_engine)
    with pytest.raises(RuntimeResumeError) as service_error:
        SqlAlchemyProductPreparationResumeService(
            missing_sessions,
            runtime_jobs=_queue(missing_sessions),
            clock=lambda: NOW_DT,
        ).reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    assert service_error.value.error_code == "ae.runtime_resume_unavailable"
    with pytest.raises(RuntimeResumeError) as route_error:
        SqlAlchemyResumeRouteSource(missing_sessions).resolve(
            tenant_id=TENANT, runtime_job_id="job"
        )
    assert route_error.value.error_code == "ae.runtime_resume_unavailable"
    missing_engine.dispose()


def test_exact_replay_requires_its_original_job(runtime_store) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )
    service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_runtime_job"))

    with pytest.raises(RuntimeResumeError, match="resume job is missing"):
        service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)


def test_target_shape_and_scalar_guards_are_fail_closed(runtime_store) -> None:
    _engine, sessions = runtime_store
    matcher = RuntimeEventMatcher(_queue(sessions))
    base = {
        "tenant_id": TENANT,
        "wait_id": WAIT_ID,
        "event_id": EVENT_ID,
        "execution_id": EXECUTION_ID,
        "runtime_job_id": "55555555-5555-4555-8555-555555556b13",
        "dedup_key": "target-guard",
        "run_after": NOW,
        "correlation_id": "correlation-6b1a3",
        "now": NOW,
        "payload": {"wait_id": WAIT_ID, "event_id": EVENT_ID},
        "causation_id": EVENT_ID,
    }
    with sessions() as session:
        with pytest.raises(RuntimeResumeError, match="requires executable_step_id"):
            matcher.match_in_session(
                session,
                **base,
                executable_step_id=None,
                resume_target_kind="EXECUTABLE_STEP",
            )
        with pytest.raises(RuntimeResumeError, match="cannot reference"):
            matcher.match_in_session(
                session,
                **base,
                executable_step_id="step-id",
                resume_target_kind="PRODUCT_COORDINATOR",
            )
        with pytest.raises(RuntimeResumeError, match="step lineage differs"):
            matcher.match_in_session(
                session,
                **base,
                executable_step_id="step-id",
                resume_target_kind="EXECUTABLE_STEP",
            )
    with pytest.raises(RuntimeResumeError, match="non-empty string"):
        SqlAlchemyResumeRouteSource(sessions).resolve(
            tenant_id=" ", runtime_job_id="job"
        )


def test_step_route_and_product_authority_drift_are_distinct(runtime_store) -> None:
    engine, sessions = runtime_store
    queue = _queue(sessions)
    step_wait = "wait-step-6b1a3"
    step_event = "event-step-6b1a3"
    step_job = "66666666-6666-4666-8666-666666666b13"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ae_wait_registration VALUES "
                "(:tenant, :wait, :execution, :step, 'WORK_RESULT', :external, "
                "'EXECUTABLE_STEP', 'RESUME_QUEUED', 1, :now, :now, :event, "
                ":job, :now)"
            ),
            {
                "tenant": TENANT,
                "wait": step_wait,
                "execution": EXECUTION_ID,
                "step": "step-6b1a3",
                "external": "wc://work/6b1a3",
                "now": NOW,
                "event": step_event,
                "job": step_job,
            },
        )
    queue.enqueue_unique(
        tenant_id=TENANT,
        runtime_job_id=step_job,
        job_type="RESUME_EXECUTION",
        execution_id=EXECUTION_ID,
        executable_step_id="step-6b1a3",
        wait_id=step_wait,
        dedup_key="step-route-6b1a3",
        run_after=NOW,
        correlation_id="correlation-step-6b1a3",
        now=NOW,
        payload={"wait_id": step_wait, "event_id": step_event},
    )
    source = SqlAlchemyResumeRouteSource(sessions)
    route = source.resolve(tenant_id=TENANT, runtime_job_id=step_job)
    assert route.resume_target_kind == "EXECUTABLE_STEP"
    assert route.product_context is None

    unbound_wait = "wait-product-unbound-6b1a3"
    unbound_event = "event-product-unbound-6b1a3"
    unbound_job = "77777777-7777-4777-8777-777777776b13"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ae_wait_registration VALUES "
                "(:tenant, :wait, :execution, NULL, 'PRODUCT_PREPARATION', "
                ":external, 'PRODUCT_COORDINATOR', 'RESUME_QUEUED', 1, :now, "
                ":now, :event, :job, :now)"
            ),
            {
                "tenant": TENANT,
                "wait": unbound_wait,
                "execution": EXECUTION_ID,
                "external": "wc://approval/unbound-6b1a3",
                "now": NOW,
                "event": unbound_event,
                "job": unbound_job,
            },
        )
    queue.enqueue_unique(
        tenant_id=TENANT,
        runtime_job_id=unbound_job,
        job_type="RESUME_EXECUTION",
        execution_id=EXECUTION_ID,
        executable_step_id=None,
        resume_target_kind="PRODUCT_COORDINATOR",
        wait_id=unbound_wait,
        dedup_key="unbound-product-route-6b1a3",
        run_after=NOW,
        correlation_id="correlation-unbound-6b1a3",
        now=NOW,
        payload={"wait_id": unbound_wait, "event_id": unbound_event},
    )
    with pytest.raises(RuntimeResumeError, match="binding is incomplete"):
        source.resolve(tenant_id=TENANT, runtime_job_id=unbound_job)

    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=queue, clock=lambda: NOW_DT
    )
    result = service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_runtime_job SET payload_json = :payload "
                "WHERE runtime_job_id = :job"
            ),
            {
                "payload": json.dumps(
                    {
                        "wait_id": WAIT_ID,
                        "event_id": EVENT_ID,
                        "resume_target_kind": "PRODUCT_COORDINATOR",
                        "dispatch_contract_version": (
                            "ae.product_coordinator_resume_dispatch.v1"
                        ),
                        "checkpoint_id": CHECKPOINT_ID,
                        "checkpoint_hash": HASH_B,
                        "coordinator_id": COORDINATOR_ID,
                        "coordinator_version": "1.0.0",
                        "coordinator_registration_hash": HASH_A,
                    }
                ),
                "job": result["resume_runtime_job_id"],
            },
        )
    with pytest.raises(RuntimeResumeError, match="payload differs from authority"):
        source.resolve(tenant_id=TENANT, runtime_job_id=result["resume_runtime_job_id"])


def test_route_rejects_non_object_payload(runtime_store) -> None:
    engine, sessions = runtime_store
    service = SqlAlchemyProductPreparationResumeService(
        sessions, runtime_jobs=_queue(sessions), clock=lambda: NOW_DT
    )
    result = service.reconcile(tenant_id=TENANT, event_id=EVENT_ID)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_runtime_job SET payload_json = '[]' "
                "WHERE runtime_job_id = :job"
            ),
            {"job": result["resume_runtime_job_id"]},
        )
    with pytest.raises(RuntimeResumeError, match="must be an object"):
        SqlAlchemyResumeRouteSource(sessions).resolve(
            tenant_id=TENANT, runtime_job_id=result["resume_runtime_job_id"]
        )


def _seed_product_context(connection) -> None:
    connection.execute(
        text("INSERT INTO ae_agent_execution VALUES (:tenant, :execution)"),
        {"tenant": TENANT, "execution": EXECUTION_ID},
    )
    connection.execute(
        text(
            "INSERT INTO ae_product_prep_checkpoint VALUES "
            "(:tenant, :checkpoint, :execution, :intent, :coordinator, '1.0.0', "
            ":hash, :correlation)"
        ),
        {
            "tenant": TENANT,
            "checkpoint": CHECKPOINT_ID,
            "execution": EXECUTION_ID,
            "intent": WORK_INTENT_ID,
            "coordinator": COORDINATOR_ID,
            "hash": HASH_A,
            "correlation": "correlation-6b1a3",
        },
    )
    connection.execute(
        text(
            "INSERT INTO ae_wait_registration VALUES "
            "(:tenant, :wait, :execution, NULL, 'PRODUCT_PREPARATION', :authority, "
            "'PRODUCT_COORDINATOR', 'PENDING', 1, :now, NULL, NULL, NULL, :now)"
        ),
        {
            "tenant": TENANT,
            "wait": WAIT_ID,
            "execution": EXECUTION_ID,
            "authority": "wc://approval/case-6b1a3",
            "now": NOW,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ae_product_prep_wait_binding VALUES "
            "(:tenant, :wait, :checkpoint, :hash, :coordinator, '1.0.0', :hash, "
            "'BUSINESS_APPROVAL_CHANGED', 'BUSINESS_FORMAL', :authority, "
            ":execution, :intent)"
        ),
        {
            "tenant": TENANT,
            "wait": WAIT_ID,
            "checkpoint": CHECKPOINT_ID,
            "hash": HASH_A,
            "coordinator": COORDINATOR_ID,
            "authority": "wc://approval/case-6b1a3",
            "execution": EXECUTION_ID,
            "intent": WORK_INTENT_ID,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ae_external_event_inbox VALUES "
            "(:tenant, :event, 'PRODUCT_PREPARATION', 'BUSINESS_APPROVAL_CHANGED', "
            ":authority, :payload, 'RECEIVED', :now, NULL)"
        ),
        {
            "tenant": TENANT,
            "event": EVENT_ID,
            "authority": "wc://approval/case-6b1a3",
            "payload": '{"notification_ref":"wc-event://decision/6b1a3"}',
            "now": NOW,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ae_product_prep_event_binding VALUES "
            "(:tenant, :event, :wait, :checkpoint, :hash, :coordinator, '1.0.0', "
            ":hash, 'BUSINESS_FORMAL', :notification, :execution, :intent)"
        ),
        {
            "tenant": TENANT,
            "event": EVENT_ID,
            "wait": WAIT_ID,
            "checkpoint": CHECKPOINT_ID,
            "hash": HASH_A,
            "coordinator": COORDINATOR_ID,
            "notification": "wc-event://decision/6b1a3",
            "execution": EXECUTION_ID,
            "intent": WORK_INTENT_ID,
        },
    )


_SCHEMA = (
    """CREATE TABLE ae_agent_execution (
        tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
        PRIMARY KEY (tenant_id, agent_execution_id))""",
    """CREATE TABLE ae_wait_registration (
        tenant_id TEXT NOT NULL, wait_id TEXT NOT NULL,
        agent_execution_id TEXT NOT NULL, executable_step_id TEXT,
        wait_type TEXT NOT NULL, external_ref TEXT NOT NULL,
        resume_target_kind TEXT NOT NULL, state TEXT NOT NULL,
        version INTEGER NOT NULL, created_at TEXT NOT NULL,
        satisfied_at TEXT, matched_event_id TEXT, resume_runtime_job_id TEXT,
        updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id, wait_id))""",
    """CREATE TABLE ae_external_event_inbox (
        tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
        event_family TEXT NOT NULL, event_type TEXT NOT NULL,
        external_ref TEXT NOT NULL, event_payload TEXT NOT NULL,
        state TEXT NOT NULL, received_at TEXT NOT NULL, processed_at TEXT,
        PRIMARY KEY (tenant_id, event_id))""",
    """CREATE TABLE ae_product_prep_checkpoint (
        tenant_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
        agent_execution_id TEXT NOT NULL, work_intent_id TEXT NOT NULL,
        coordinator_id TEXT NOT NULL, coordinator_version TEXT NOT NULL,
        coordinator_registration_hash TEXT NOT NULL, correlation_id TEXT NOT NULL,
        PRIMARY KEY (tenant_id, checkpoint_id))""",
    """CREATE TABLE ae_product_prep_wait_binding (
        tenant_id TEXT NOT NULL, wait_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
        checkpoint_hash TEXT NOT NULL, coordinator_id TEXT NOT NULL,
        coordinator_version TEXT NOT NULL, coordinator_registration_hash TEXT NOT NULL,
        expected_event_type TEXT NOT NULL, authority_kind TEXT NOT NULL,
        authority_ref TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
        work_intent_id TEXT NOT NULL, PRIMARY KEY (tenant_id, wait_id))""",
    """CREATE TABLE ae_product_prep_event_binding (
        tenant_id TEXT NOT NULL, event_id TEXT NOT NULL, wait_id TEXT NOT NULL,
        checkpoint_id TEXT NOT NULL, checkpoint_hash TEXT NOT NULL,
        coordinator_id TEXT NOT NULL, coordinator_version TEXT NOT NULL,
        coordinator_registration_hash TEXT NOT NULL, authority_kind TEXT NOT NULL,
        notification_ref TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
        work_intent_id TEXT NOT NULL, PRIMARY KEY (tenant_id, event_id))""",
    """CREATE TABLE ae_runtime_job (
        tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL, job_type TEXT NOT NULL,
        execution_id TEXT NOT NULL, executable_step_id TEXT, wait_id TEXT,
        reconciliation_id TEXT, result_delivery_id TEXT,
        publication_reconciliation_id TEXT, state TEXT NOT NULL,
        dedup_key TEXT NOT NULL, attempt_no INTEGER NOT NULL, run_after TEXT NOT NULL,
        lease_owner TEXT, lease_token TEXT, lease_until TEXT, payload_json TEXT NOT NULL,
        correlation_id TEXT NOT NULL, causation_id TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id, runtime_job_id),
        UNIQUE (tenant_id, dedup_key))""",
    """CREATE TABLE ae_runtime_job_attempt (
        attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
        runtime_job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
        worker_id TEXT NOT NULL, lease_token TEXT NOT NULL, started_at TEXT NOT NULL,
        ended_at TEXT, outcome TEXT NOT NULL, error_ref TEXT,
        retry_disposition_ref TEXT, UNIQUE (tenant_id, runtime_job_id, attempt_no))""",
)
