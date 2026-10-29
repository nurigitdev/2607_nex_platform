from __future__ import annotations

from types import SimpleNamespace

import run_gb2_ca00_s05_ae_agent_runtime_worker as ae_runner
import run_gb2_ca00_s06_wc_event_delivery_worker as wc_runner
import run_gb2_ca00_s07_eos_outbox_publisher as eos_runner


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = tuple(rows)

    def scalar_one(self):
        return self._scalar

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def execute(self, statement, _parameters=None):
        query = str(statement)
        if "FROM ae_step_result" in query:
            return _Result(scalar=0)
        if "FROM ae_runtime_job_attempt" in query:
            return _Result(
                rows=(
                    {"runtime_job_id": "job-1", "outcome": "DONE"},
                    {"runtime_job_id": "job-2", "outcome": "DONE"},
                )
            )
        if "FROM ae_runtime_job" in query:
            return _Result(
                rows=(
                    {"runtime_job_id": "job-1", "state": "DONE"},
                    {"runtime_job_id": "job-2", "state": "DONE"},
                )
            )
        raise AssertionError(f"unexpected query: {query}")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _Factory:
    def __call__(self):
        return _Session()


class _Queue:
    def __init__(self, _factory):
        pass

    def claim(self, **_values):
        return {"runtime_job_id": "job-1"}

    def get(self, _tenant_id, _job_id):
        return {"state": "QUEUED", "attempt_no": 0}


class _Engine:
    def __init__(self, _factory, _queue):
        self.calls = 0

    def schedule_next(self, **_values):
        self.calls += 1
        return {
            "runtime_job_id": f"job-{self.calls}",
            "executable_step_id": f"step-{self.calls}",
        }


class _PreparationWorker:
    def __init__(self, **_values):
        pass

    def run_claim(self, **_values):
        return SimpleNamespace(disposition="TERMINAL")


class _InstalledProcess:
    def __init__(self, execution_count: int):
        self.execution_count = execution_count
        self.close_calls = 0

    def readiness(self):
        return {
            "database": {
                "database_name": ae_runner.EXPECTED_DATABASE,
                "database_user": ae_runner.EXPECTED_ROLE,
            },
            "readiness_status": "READY",
            "checks": {"database": True, "worker": True},
        }

    def run_once(self):
        return {
            "execution_count": self.execution_count,
            "succeeded_count": self.execution_count,
            "failed_count": 0,
        }

    def close(self):
        self.close_calls += 1


def test_ae_canonical_worker_orchestrates_without_a_database(monkeypatch) -> None:
    factory = _Factory()
    fixture = {
        "factory": factory,
        "tenant_id": "tenant-1",
        "execution": {
            "legacy_interaction_id": "interaction-1",
            "agent_execution_id": "execution-1",
        },
        "executable_plan": {
            "executable_plan_id": "plan-1",
            "steps": [
                {"executor_kind": "P4_CHAT_RAG_COMPATIBILITY"},
                {"executor_kind": "DETERMINISTIC_REPORT"},
            ],
        },
        "now": "2026-10-29T00:00:00Z",
    }
    processes = iter((_InstalledProcess(0), _InstalledProcess(1), _InstalledProcess(0)))
    monkeypatch.setattr(ae_runner, "_install_report_binding", lambda *_a, **_k: None)
    monkeypatch.setattr(ae_runner, "SqlAlchemyRuntimeJobQueue", _Queue)
    monkeypatch.setattr(ae_runner, "SqlAlchemyMultiStepEngine", _Engine)
    monkeypatch.setattr(ae_runner, "P5StepExecutionWorker", _PreparationWorker)
    monkeypatch.setattr(ae_runner, "default_p5_executor_registry", lambda _fn: {})
    monkeypatch.setattr(
        ae_runner,
        "build_installed_agent_runtime_process",
        lambda *_a, **_k: next(processes),
    )
    monkeypatch.setattr(
        ae_runner,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda _factory: SimpleNamespace(
            get_heartbeat=lambda *_a: {
                "status": "STOPPED",
                "metadata": {"process_id": ae_runner.PROCESS_ID},
            }
        ),
    )
    monkeypatch.setattr(
        ae_runner,
        "_cleanup_component_rows",
        lambda *_a, **_k: {"component_remaining": 0},
    )

    evidence = ae_runner._verify_canonical_worker(
        fixture,
        database_url="postgresql://nex_ae_user:secret@localhost/nex_ae_test",
    )

    assert all(evidence["checks"].values())
    assert evidence["row_counts"] == {
        "runtime_job": 2,
        "runtime_job_attempt": 2,
        "heartbeat": 1,
    }
    assert evidence["cleanup_counts"] == {"component_remaining": 0}


def test_ae_canonical_worker_closes_partial_process_on_failure(monkeypatch) -> None:
    process = _InstalledProcess(0)
    monkeypatch.setattr(ae_runner, "_install_report_binding", lambda *_a, **_k: None)
    monkeypatch.setattr(ae_runner, "SqlAlchemyRuntimeJobQueue", _Queue)

    class MissingJobEngine(_Engine):
        def schedule_next(self, **_values):
            return None

    monkeypatch.setattr(ae_runner, "SqlAlchemyMultiStepEngine", MissingJobEngine)
    monkeypatch.setattr(ae_runner, "P5StepExecutionWorker", _PreparationWorker)
    monkeypatch.setattr(ae_runner, "default_p5_executor_registry", lambda _fn: {})
    monkeypatch.setattr(
        ae_runner,
        "build_installed_agent_runtime_process",
        lambda *_a, **_k: process,
    )
    monkeypatch.setattr(
        ae_runner,
        "_cleanup_component_rows",
        lambda *_a, **_k: {"component_remaining": 0},
    )
    fixture = {
        "factory": _Factory(),
        "tenant_id": "tenant-1",
        "execution": {
            "legacy_interaction_id": "interaction-1",
            "agent_execution_id": "execution-1",
        },
        "executable_plan": {"executable_plan_id": "plan-1", "steps": []},
        "now": "2026-10-29T00:00:00Z",
    }

    try:
        ae_runner._verify_canonical_worker(fixture, database_url="unused")
    except RuntimeError as exc:
        assert "claimable" in str(exc)
    else:
        raise AssertionError("missing admitted job must fail closed")
    assert process.close_calls == 0


class _DbResult:
    def __init__(self, *, row=None, scalar=None, rowcount=1):
        self._row = row
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one(self):
        return self._row

    def scalar_one(self):
        return self._scalar


class _DbConnection:
    def __init__(self, owner: str):
        self.owner = owner

    def execute(self, statement, _parameters=None):
        query = str(statement)
        if "FROM service_jobs" in query:
            if "error" in query:
                return _DbResult(
                    row={
                        "job_id": "job-1",
                        "status": "QUEUED",
                        "attempt_count": 1,
                        "error": "denied",
                    }
                )
            return _DbResult(row={"status": "SUCCEEDED", "attempt_count": 2})
        if "UPDATE service_jobs" in query:
            return _DbResult()
        if "count(*) FROM ae_agent_execution" in query:
            return _DbResult(scalar=0 if self.owner == "ae-connect" else 1)
        if "count(*) FROM ae_claim_handoff_inbox" in query:
            return _DbResult(scalar=1)
        if "SELECT current_database(), current_user" in query:
            if self.owner.startswith("ae"):
                return _DbResult(row=("nex_ae_test", "nex_ae_user"))
            return _DbResult(row=("nex_wc_test", "nex_wc_user"))
        if "SELECT agent_execution_id FROM wc_assignment" in query:
            return _DbResult(scalar="execution-1")
        raise AssertionError(f"unexpected {self.owner} query: {query}")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _DbEngine:
    def __init__(self, owner: str):
        self.owner = owner
        self.disposed = False

    def begin(self):
        return _DbConnection(self.owner)

    def connect(self):
        owner = "ae-connect" if self.owner == "ae" else self.owner
        return _DbConnection(owner)

    def dispose(self):
        self.disposed = True


class _DbSessions:
    def __init__(self, owner: str):
        self.owner = owner

    def __call__(self):
        return _DbConnection(self.owner)


class _WcRegistry:
    def __init__(self, *_args, **_kwargs):
        self.registered = False

    def register_agent(self, **_values):
        self.registered = True

    def list_eligible_agents(self, **_values):
        return ({"agent_id": "agent-1"},)

    def get_agent(self, **_values):
        return {"agent_id": "agent-1"}


class _Coordination:
    def __init__(self, _sessions):
        self.event_reads = 0

    def get_work_item(self, **_values):
        return {"work_item": {"version": 2}}

    def load_handoff_event(self, **_values):
        self.event_reads += 1
        return {"delivery_state": "ENQUEUED" if self.event_reads == 1 else "DELIVERED"}


class _CoordinationService:
    def __init__(self, repository, **_values):
        self.repository = repository

    def route(self, **_values):
        return {"state": "ROUTED"}

    def claim(self, **_values):
        return {
            "outbox_id": "outbox-1",
            "event_id": "event-1",
            "claim": {"state": "ACTIVE"},
            "assignment": {"assignment_id": "assignment-1"},
        }


class _WcProcess:
    def __init__(self, kind: str):
        self.kind = kind
        self.queue = SimpleNamespace(get_job=lambda _job_id: {"job_id": "job-1"})
        self.coordination = SimpleNamespace()
        self.handoff_client = SimpleNamespace()
        self.heartbeat = SimpleNamespace(
            store=SimpleNamespace(
                get_heartbeat=lambda *_a: {
                    "status": "STOPPED",
                    "metadata": {"process_id": wc_runner.PROCESS_ID},
                }
            )
        )
        self.closed = False

    def readiness(self):
        return {"readiness_status": "READY", "checks": {"database": True}}

    def close(self):
        self.closed = True


def test_wc_canonical_delivery_orchestrates_retry_and_replay_without_db(
    monkeypatch,
) -> None:
    engines = iter((_DbEngine("wc"), _DbEngine("ae")))
    processes = iter(
        (_WcProcess("wrong"), _WcProcess("delivery"), _WcProcess("restart"))
    )
    coordination = _Coordination(None)
    admission = SimpleNamespace(
        public_snapshot=lambda: {"admission_counts": {"accepted_signed": 3}}
    )
    bridge = SimpleNamespace(status_codes=[403, 200, 200])

    monkeypatch.setattr(wc_runner, "create_engine", lambda _url: next(engines))
    monkeypatch.setattr(
        wc_runner,
        "sessionmaker",
        lambda *, bind, expire_on_commit=False: _DbSessions(bind.owner),
    )
    monkeypatch.setattr(wc_runner, "_cleanup_wc", lambda *_a, **_k: {"wc_remaining": 0})
    monkeypatch.setattr(wc_runner, "_cleanup_ae", lambda *_a, **_k: {"ae_remaining": 0})
    monkeypatch.setattr(wc_runner, "SqlAlchemyAgentIdentityRegistry", _WcRegistry)
    monkeypatch.setattr(
        wc_runner, "SqlAlchemyAgentExecutionRepository", lambda _sessions: object()
    )
    monkeypatch.setattr(
        wc_runner, "AgentExecutionAdmissionService", lambda **_values: object()
    )
    monkeypatch.setattr(
        wc_runner,
        "_signed_trust",
        lambda **_values: {
            "admission": admission,
            "wrong_token": "wrong-token",
            "token": "right-token",
        },
    )
    monkeypatch.setattr(
        wc_runner, "FastAPI", lambda: SimpleNamespace(state=SimpleNamespace())
    )
    monkeypatch.setattr(
        wc_runner, "register_claim_handoff_routes", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        wc_runner, "TestClient", lambda _app: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(wc_runner, "_TestClientUrlOpen", lambda _client: bridge)
    monkeypatch.setattr(
        wc_runner, "SqlAlchemyWorkItemRepository", lambda _sessions: object()
    )
    monkeypatch.setattr(
        wc_runner,
        "WorkItemService",
        lambda *_a, **_k: SimpleNamespace(
            create=lambda _payload: {"work_item": {"work_item_id": "work-1"}}
        ),
    )
    monkeypatch.setattr(
        wc_runner, "SqlAlchemyCoordinationRepository", lambda _sessions: coordination
    )
    monkeypatch.setattr(wc_runner, "WorkCoordinationService", _CoordinationService)
    monkeypatch.setattr(
        wc_runner,
        "build_installed_wc_event_delivery_process",
        lambda *_a, **_k: next(processes),
    )

    def run_process(process, **_values):
        if process.kind == "wrong":
            return {"failed_count": 1, "work_cycles": 1}
        if process.kind == "delivery":
            return {"failed_count": 0, "work_cycles": 1}
        return {"failed_count": 0, "work_cycles": 0}

    monkeypatch.setattr(
        wc_runner, "run_installed_wc_event_delivery_process", run_process
    )
    monkeypatch.setattr(
        wc_runner,
        "run_handoff_delivery_job",
        lambda *_a, **_k: {"agent_execution_id": "execution-1"},
    )

    evidence = wc_runner._execute_protected_component(
        wc_database_url="wc", ae_database_url="ae"
    )

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"] == {"wc_remaining": 0, "ae_remaining": 0}
    assert evidence["row_counts"]["http_attempts"] == 3


class _EosConnection:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, statement, _parameters=None):
        query = str(statement)
        if "SELECT current_database(), current_user" in query:
            if self.engine.owner == "ae":
                return _DbResult(row=("nex_ae_test", "nex_ae_user"))
            return _DbResult(row=("nex_eos_test", "nex_eos_user"))
        if "FROM eos_outbox" in query and "delivery_state" in query:
            self.engine.outbox_reads += 1
            if self.engine.outbox_reads == 1:
                return _DbResult(
                    row={
                        "delivery_state": "PENDING",
                        "attempt_count": 1,
                        "published_at": None,
                    }
                )
            return _DbResult(
                row={
                    "delivery_state": "PUBLISHED",
                    "attempt_count": 2,
                    "published_at": "2026-10-29T00:00:00Z",
                }
            )
        if "SELECT count(*)" in query and "tenant_id" in query:
            return _DbResult(scalar=1)
        raise AssertionError(f"unexpected {self.engine.owner} query: {query}")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _EosEngine:
    def __init__(self, owner: str):
        self.owner = owner
        self.outbox_reads = 0
        self.disposed = False

    def connect(self):
        return _EosConnection(self)

    def dispose(self):
        self.disposed = True


class _TransactionCoordinator:
    def __init__(self, _sessions, *, id_factory, clock):
        self.id_factory = id_factory
        self.clock = clock

    def execute(self, request, mutation):
        outbox_id = self.id_factory()
        event_id = self.id_factory()
        result = mutation(object())
        assert result["business_result_ref"].startswith("eos:voucher:")
        return SimpleNamespace(
            created=True,
            outbox_id=outbox_id,
            tenant_id=request.tenant_id,
            event_id=event_id,
            business_operation_id=request.business_operation_id,
            event_type=request.event_type,
            operation=request.operation,
            event_payload_hash="sha256:" + "4" * 64,
        )


class _EosTransport:
    def __init__(self, **_values):
        pass

    def publish(self, event):
        return SimpleNamespace(
            event_id=event.event_id,
            event_payload_hash=event.event_payload_hash,
        )


class _EosProcess:
    def __init__(self, kind: str):
        self.kind = kind
        self.transport = None
        self.heartbeat = SimpleNamespace(
            store=SimpleNamespace(
                get_heartbeat=lambda *_a: {
                    "status": "STOPPED",
                    "metadata": {"process_id": eos_runner.PROCESS_ID},
                }
            )
        )
        self.closed = False

    def readiness(self):
        return {"readiness_status": "READY", "checks": {"outbox": True}}

    def close(self):
        self.closed = True


def test_eos_canonical_outbox_orchestrates_retry_and_replay_without_db(
    monkeypatch,
) -> None:
    engines = iter((_EosEngine("eos"), _EosEngine("ae")))
    processes = iter(
        (_EosProcess("denied"), _EosProcess("admitted"), _EosProcess("restart"))
    )
    admission = SimpleNamespace()
    bridge = SimpleNamespace(status_codes=[403, 201, 200])
    event_counts = iter((0, 1))

    monkeypatch.setattr(eos_runner, "create_engine", lambda _url: next(engines))
    monkeypatch.setattr(
        eos_runner,
        "sessionmaker",
        lambda *, bind, expire_on_commit=False: _DbSessions(bind.owner),
    )
    monkeypatch.setattr(
        eos_runner, "_cleanup_eos", lambda *_a, **_k: {"eos_remaining": 0}
    )
    monkeypatch.setattr(
        eos_runner, "_cleanup_ae", lambda *_a, **_k: {"ae_remaining": 0}
    )
    monkeypatch.setattr(
        eos_runner,
        "SqlAlchemyEosBusinessTransactionCoordinator",
        _TransactionCoordinator,
    )
    monkeypatch.setattr(
        eos_runner,
        "_signed_trust",
        lambda **_values: {
            "admission": admission,
            "wrong_token": "wrong-token",
            "token": "right-token",
        },
    )
    monkeypatch.setattr(
        eos_runner, "FastAPI", lambda: SimpleNamespace(state=SimpleNamespace())
    )
    monkeypatch.setattr(
        eos_runner, "SqlAlchemyOperationalEventStore", lambda _sessions: object()
    )
    monkeypatch.setattr(
        eos_runner, "register_eos_outbox_event_routes", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        eos_runner, "TestClient", lambda _app: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(eos_runner, "_TestClientUrlOpen", lambda _client: bridge)
    monkeypatch.setattr(eos_runner, "HttpAeEosOutboxTransport", _EosTransport)
    monkeypatch.setattr(
        eos_runner,
        "build_installed_eos_outbox_publisher_process",
        lambda *_a, **_k: next(processes),
    )

    def run_process(process, **_values):
        if process.kind == "denied":
            return {"failed_count": 1, "published_count": 0, "work_cycles": 1}
        if process.kind == "admitted":
            return {"failed_count": 0, "published_count": 1, "work_cycles": 1}
        return {"failed_count": 0, "published_count": 0, "work_cycles": 0}

    monkeypatch.setattr(
        eos_runner, "run_installed_eos_outbox_publisher_process", run_process
    )
    monkeypatch.setattr(
        eos_runner, "_ae_event_count", lambda *_a, **_k: next(event_counts)
    )

    evidence = eos_runner._execute_protected_component(
        eos_database_url="eos", ae_database_url="ae"
    )

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"] == {"eos_remaining": 0, "ae_remaining": 0}
    assert evidence["row_counts"]["http_attempts"] == 3
