from __future__ import annotations

import builtins
import copy
import json
import sys
import types
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nex_ae_api.nsl_read_backends as backend_module
import pytest
from nex_ae_api.nsl_read_backends import (
    BACKEND_PROFILE,
    NSLReadBackendError,
    NSLReadExecutionService,
    SqlAlchemyNSLBackendRunRepository,
    V01ProcessEntrypoint,
    V01ReadBackendAdapter,
    build_v01_process_isolated_backend,
    build_v01_skill_execution_job,
    nsl_backend_run_table_sql,
    validate_nsl_backend_run,
)
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    nsl_step_execution_table_sql,
)
from nex_ae_api.skill_artifacts import (
    SqlAlchemySkillArtifactRepository,
    skill_artifact_table_sql,
)
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/transition/P6/contracts/examples"
MIGRATION = ROOT / "database/nex-ae-api/migrations/2204_ae_nsl_backend_run.sql"
TENANT = "tenant-p6-golden"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
CONTEXT_ID = "44444444-4444-4444-8444-444444444444"
NSL_ID = "66666666-6666-4666-8666-666666666666"
BOI = "77777777-7777-4777-8777-777777777777"
NOW = "2026-10-14T07:00:00Z"
COMPLETED = datetime(2026, 10, 14, 7, 0, 1, tzinfo=UTC)


def _example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _progress_event(sequence: int, state: str) -> dict[str, Any]:
    terminal = state in {"COMPLETED", "FAILED"}
    return {
        "format": "NEX-NSL-EXECUTION-PROGRESS",
        "schema_version": "1.0",
        "execution_id": NSL_ID,
        "sequence": sequence,
        "state": state,
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "skill_version": "1.0.0",
        "runtime_status": state if terminal else None,
        "error_code": "RUNTIME_FAILED" if state == "FAILED" else None,
    }


def _child_response(*, runtime_status: str = "COMPLETED") -> bytes:
    terminal_state = "COMPLETED" if runtime_status == "COMPLETED" else "FAILED"
    result = {
        "schema_version": "1.0",
        "execution_id": NSL_ID,
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "skill_version": "1.0.0",
        "semantic_hash": _example("p6-golden-verified-artifact-v1.json")[
            "skill_semantic_hash"
        ],
        "status": runtime_status,
        "completeness": "COMPLETE",
        "checks": [],
        "outputs": [],
        "resources": {
            "tool_calls": 2,
            "loop_iterations": 1,
            "emitted_rows": 1,
            "max_collection_size_seen": 3,
        },
        "error": None if runtime_status == "COMPLETED" else {"code": "FAILED"},
    }
    response = {
        "format": "NEX-P6-NSL-V01-CHILD-RESPONSE",
        "schema_version": "1.0",
        "runtime_result_envelope": {
            "format": "NEX-NSL-RUNTIME-RESULT",
            "schema_version": "1.0",
            "runtime_result": result,
        },
        "progress_events": [
            _progress_event(1, "STARTED"),
            _progress_event(2, "SKILL_RESOLVED"),
            _progress_event(3, "RUNNING"),
            _progress_event(4, terminal_state),
        ],
        "evidence_refs": [f"NSL:AUDIT:{NSL_ID}", f"NSL:SNAPSHOT:{NSL_ID}"],
    }
    return canonical_json(response).encode("utf-8")


@dataclass(frozen=True)
class _IsolationResult:
    status: str
    payload: bytes | None
    exit_code: int | None
    error_code: str | None


class _IsolationRuntime:
    timeout_ms = 30_000
    max_payload_bytes = 8 * 1024 * 1024

    def __init__(self, result: _IsolationResult | Exception) -> None:
        self.result = result
        self.calls: list[bytes] = []

    def execute(self, payload: bytes) -> _IsolationResult:
        self.calls.append(payload)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _adapter(
    result: _IsolationResult | Exception | None = None,
) -> tuple[V01ReadBackendAdapter, _IsolationRuntime]:
    runtime = _IsolationRuntime(
        result
        or _IsolationResult(
            status="COMPLETED",
            payload=_child_response(),
            exit_code=0,
            error_code=None,
        )
    )
    return V01ReadBackendAdapter(runtime, clock=lambda: COMPLETED), runtime


def _execute(adapter: V01ReadBackendAdapter, **overrides: Any) -> dict[str, Any]:
    values = {
        "request": _example("p6-golden-skill-execution-request-v1.json"),
        "context_projection": _example("p6-golden-context-projection-v1.json"),
        "artifact": _example("p6-golden-verified-artifact-v1.json"),
        "attempt_no": 1,
        "started_at": NOW,
    }
    return adapter.execute(**{**values, **overrides})


def _rehash(record: dict[str, Any]) -> dict[str, Any]:
    record["record_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "record_hash"}
    )
    return record


def test_v01_job_mapping_is_exact_project_neutral_and_source_compatible() -> None:
    request = _example("p6-golden-skill-execution-request-v1.json")
    context = _example("p6-golden-context-projection-v1.json")
    artifact = _example("p6-golden-verified-artifact-v1.json")

    job = build_v01_skill_execution_job(
        request=request, context_projection=context, artifact=artifact
    )

    assert job == {
        "format": "NEX-NSL-SKILL-EXECUTION-JOB",
        "schema_version": "1.0",
        "execution_id": NSL_ID,
        "skill_id": artifact["skill_id"],
        "skill_version": artifact["skill_version"],
        "expected_semantic_hash": artifact["skill_semantic_hash"],
        "inputs": {"year": 2026},
        "input_provenance": {"year": "USER"},
        "runtime_context": {"user": {"team_id": "TEAM-FINANCE"}},
        "principal": context["verified_principal"],
        "data_policy": {
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    }
    assert "project_id" not in canonical_json(job)


def test_v01_adapter_bridges_terminal_result_progress_and_evidence() -> None:
    adapter, runtime = _adapter()

    record = _execute(adapter)
    child_request = json.loads(runtime.calls[0])

    assert record["isolation_status"] == "COMPLETED"
    assert record["runtime_status"] == "COMPLETED"
    assert record["record_hash"].startswith("sha256:")
    assert [event["state"] for event in record["progress_events"]] == [
        "STARTED",
        "SKILL_RESOLVED",
        "RUNNING",
        "COMPLETED",
    ]
    assert record["evidence_refs"] == sorted(
        [
            f"AE:NSL_BACKEND_RUN:{NSL_ID}:1",
            f"NSL:AUDIT:{NSL_ID}",
            f"NSL:SNAPSHOT:{NSL_ID}",
        ]
    )
    assert child_request["backend_artifact_handle"].startswith("nsp+sha256://")
    assert child_request["job"]["execution_id"] == NSL_ID
    assert adapter.timeout_ms == 30_000
    assert adapter.max_payload_bytes == 8 * 1024 * 1024


def test_process_entrypoint_uses_stable_api_and_validates_session(
    monkeypatch,
) -> None:
    class _Event:
        def to_data(self):
            return {"sequence": 1}

    class _Progress:
        def __init__(self) -> None:
            self.events = [_Event()]

    class _Job:
        @classmethod
        def from_data(cls, value):
            assert value["execution_id"] == NSL_ID
            return value

    class _Envelope:
        def to_data(self):
            return {"runtime_result": {"status": "COMPLETED"}}

    class _Worker:
        async def execute(self, _job):
            return _Envelope()

    api = types.ModuleType("nsl.api")
    api.InMemoryProgressSink = _Progress
    api.SkillExecutionJob = _Job
    api.SkillExecutionWorker = _Worker
    package = types.ModuleType("nsl")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "nsl", package)
    monkeypatch.setitem(sys.modules, "nsl.api", api)
    artifact = _example("p6-golden-verified-artifact-v1.json")
    job = build_v01_skill_execution_job(
        request=_example("p6-golden-skill-execution-request-v1.json"),
        context_projection=_example("p6-golden-context-projection-v1.json"),
        artifact=artifact,
    )
    payload = canonical_json(
        {
            "format": "NEX-P6-NSL-V01-CHILD-REQUEST",
            "schema_version": "1.0",
            "backend_artifact_handle": artifact["backend_artifact_handle"],
            "job": job,
        }
    ).encode()

    class _Session:
        worker = _Worker()

        def evidence_refs(self):
            return ["NSL:AUDIT:test"]

    response = json.loads(V01ProcessEntrypoint(lambda *_args: _Session())(payload))
    assert response["progress_events"] == [{"sequence": 1}]
    assert response["evidence_refs"] == ["NSL:AUDIT:test"]

    with pytest.raises(TypeError, match="callable"):
        V01ProcessEntrypoint(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="invalid worker"):
        V01ProcessEntrypoint(
            lambda *_args: types.SimpleNamespace(worker=object(), evidence_refs=list)
        )(payload)
    with pytest.raises(TypeError, match="evidence bridge"):
        V01ProcessEntrypoint(lambda *_args: types.SimpleNamespace(worker=_Worker()))(
            payload
        )


def test_process_backend_builder_composes_explicit_v01_profile(monkeypatch) -> None:
    isolation = types.ModuleType("nsl.process_isolation")

    class _ProcessRuntime:
        def __init__(self, target, *, timeout_ms, max_payload_bytes) -> None:
            if timeout_ms < 1:
                raise ValueError("bad timeout")
            self.target = target
            self.timeout_ms = timeout_ms
            self.max_payload_bytes = max_payload_bytes

        def execute(self, payload):
            return self.target(payload)

    isolation.ProcessIsolatedRuntime = _ProcessRuntime
    package = types.ModuleType("nsl")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "nsl", package)
    monkeypatch.setitem(sys.modules, "nsl.process_isolation", isolation)

    backend = build_v01_process_isolated_backend(
        lambda payload: payload, timeout_ms=100, max_payload_bytes=1024
    )
    assert backend.backend_profile == BACKEND_PROFILE
    assert backend.timeout_ms == 100
    with pytest.raises(NSLReadBackendError, match="configuration"):
        build_v01_process_isolated_backend(lambda payload: payload, timeout_ms=0)

    real_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "nsl.process_isolation":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(NSLReadBackendError, match="unavailable"):
        build_v01_process_isolated_backend(lambda payload: payload)


@pytest.mark.parametrize(
    ("status", "exit_code", "supplied_code", "retryable"),
    [
        ("TARGET_ERROR", 0, "ISOLATED_RUNTIME_TARGET_ERROR", False),
        ("CRASHED", 17, "ISOLATED_RUNTIME_CRASH", True),
        ("TIMED_OUT", -15, "ISOLATED_RUNTIME_TIMEOUT", True),
        ("PROTOCOL_ERROR", 0, "CUSTOM_PROTOCOL_ERROR", False),
        ("UNKNOWN", 0, None, False),
    ],
)
def test_v01_adapter_contains_isolation_failures(
    status: str, exit_code: int, supplied_code: str | None, retryable: bool
) -> None:
    adapter, _runtime = _adapter(
        _IsolationResult(status, None, exit_code, supplied_code)
    )

    record = _execute(adapter)

    expected_status = status if status != "UNKNOWN" else "PROTOCOL_ERROR"
    assert record["isolation_status"] == expected_status
    assert record["runtime_result_envelope"] is None
    assert record["progress_events"] == []
    assert record["retryable"] is retryable
    assert record["error_code"]


def test_v01_adapter_contains_start_and_child_protocol_failures() -> None:
    start_failure, _runtime = _adapter(RuntimeError("private launch detail"))
    started = _execute(start_failure)
    malformed, _runtime = _adapter(_IsolationResult("COMPLETED", b"{}", 0, None))
    protocol = _execute(malformed)

    assert started["isolation_status"] == "PROTOCOL_ERROR"
    assert started["error_code"] == "ISOLATED_RUNTIME_START_FAILED"
    assert started["retryable"] is True
    assert protocol["isolation_status"] == "PROTOCOL_ERROR"
    assert protocol["error_code"] == "ISOLATED_RUNTIME_PROTOCOL_ERROR"
    assert "private" not in canonical_json(started)

    non_bytes, _runtime = _adapter(_IsolationResult("COMPLETED", None, 0, None))
    assert _execute(non_bytes)["isolation_status"] == "PROTOCOL_ERROR"

    tiny_runtime = _IsolationRuntime(
        _IsolationResult("COMPLETED", _child_response(), 0, None)
    )
    tiny_runtime.max_payload_bytes = 100
    with pytest.raises(NSLReadBackendError, match="request exceeds"):
        _execute(V01ReadBackendAdapter(tiny_runtime, clock=lambda: COMPLETED))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["runtime_result_envelope"]["runtime_result"].update(
            status="RUNNING"
        ),
        lambda value: value["runtime_result_envelope"]["runtime_result"].update(
            execution_id="88888888-8888-4888-8888-888888888888"
        ),
        lambda value: value["runtime_result_envelope"]["runtime_result"].update(
            semantic_hash="sha256:" + "0" * 64
        ),
        lambda value: value["progress_events"][1].update(sequence=9),
        lambda value: value.update(evidence_refs=["same", "same"]),
        lambda value: value.update(format="OTHER"),
    ],
)
def test_v01_adapter_converts_untrusted_child_contract_drift_to_protocol_evidence(
    mutator,
) -> None:
    value = json.loads(_child_response())
    mutator(value)
    payload = canonical_json(value).encode("utf-8")
    adapter, _runtime = _adapter(_IsolationResult("COMPLETED", payload, 0, None))

    record = _execute(adapter)

    assert record["isolation_status"] == "PROTOCOL_ERROR"
    assert record["runtime_status"] is None


def test_job_mapping_rejects_context_artifact_and_path_drift() -> None:
    request = _example("p6-golden-skill-execution-request-v1.json")
    context = _example("p6-golden-context-projection-v1.json")
    artifact = _example("p6-golden-verified-artifact-v1.json")
    changed_request = {**request, "tenant_id": "tenant-other"}
    with pytest.raises(NSLReadBackendError, match="context projection"):
        build_v01_skill_execution_job(
            request=changed_request, context_projection=context, artifact=artifact
        )

    changed_request = {**request, "skill_id": "FINANCE.OTHER"}
    with pytest.raises(NSLReadBackendError, match="Skill artifact"):
        build_v01_skill_execution_job(
            request=changed_request, context_projection=context, artifact=artifact
        )

    overlap = copy.deepcopy(context)
    overlap["runtime_context_entries"].insert(
        0,
        {
            "path": "user",
            "value": {},
            "classification": "INTERNAL",
            "source_ref": context["agent_context_ref"],
        },
    )
    overlap["projection_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in overlap.items() if key != "projection_hash"}
    )
    request = {**request, "context_projection_hash": overlap["projection_hash"]}
    with pytest.raises(NSLReadBackendError, match="overlap"):
        build_v01_skill_execution_job(
            request=request, context_projection=overlap, artifact=artifact
        )

    reverse_overlap = copy.deepcopy(context)
    reverse_overlap["runtime_context_entries"].append(
        {
            "path": "user",
            "value": {},
            "classification": "INTERNAL",
            "source_ref": context["agent_context_ref"],
        }
    )
    reverse_overlap["projection_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in reverse_overlap.items()
            if key != "projection_hash"
        }
    )
    request = {**request, "context_projection_hash": reverse_overlap["projection_hash"]}
    with pytest.raises(NSLReadBackendError, match="overlap"):
        build_v01_skill_execution_job(
            request=request,
            context_projection=reverse_overlap,
            artifact=artifact,
        )


@pytest.mark.parametrize(
    ("timeout_ms", "payload_bytes"),
    [(0, 1024), (30_001, 1024), (1000, 0), (1000, 8 * 1024 * 1024 + 1)],
)
def test_adapter_configuration_fails_closed(
    timeout_ms: int, payload_bytes: int
) -> None:
    runtime = _IsolationRuntime(
        _IsolationResult("COMPLETED", _child_response(), 0, None)
    )
    runtime.timeout_ms = timeout_ms
    runtime.max_payload_bytes = payload_bytes
    with pytest.raises(NSLReadBackendError) as caught:
        V01ReadBackendAdapter(runtime)
    assert caught.value.error_code == "ae.nsl_read_backend_unavailable"

    with pytest.raises(NSLReadBackendError):
        V01ReadBackendAdapter(object())  # type: ignore[arg-type]


def test_backend_run_validator_rejects_identity_time_and_failure_drift() -> None:
    adapter, _runtime = _adapter()
    valid = _execute(adapter)
    mutations = []
    distinct = copy.deepcopy(valid)
    distinct["business_operation_id"] = distinct["nsl_execution_id"]
    mutations.append(distinct)
    bad_time = copy.deepcopy(valid)
    bad_time["completed_at"] = "2026-10-14T06:59:59Z"
    mutations.append(bad_time)
    bad_refs = copy.deepcopy(valid)
    bad_refs["evidence_refs"] = list(reversed(bad_refs["evidence_refs"]))
    mutations.append(bad_refs)
    bad_exit = copy.deepcopy(valid)
    bad_exit["exit_code"] = 1
    mutations.append(bad_exit)
    bad_hash = copy.deepcopy(valid)
    bad_hash["record_hash"] = "sha256:" + "0" * 64
    mutations.append(bad_hash)
    bad_fields = copy.deepcopy(valid)
    bad_fields["extra"] = True
    mutations.append(bad_fields)
    bad_profile = copy.deepcopy(valid)
    bad_profile["backend_profile"] = "DIRECT"
    mutations.append(bad_profile)
    bad_isolation = copy.deepcopy(valid)
    bad_isolation["isolation_status"] = "OTHER"
    mutations.append(bad_isolation)
    bad_retryable = copy.deepcopy(valid)
    bad_retryable["retryable"] = 1
    mutations.append(bad_retryable)
    bad_exit_type = copy.deepcopy(valid)
    bad_exit_type["exit_code"] = "zero"
    mutations.append(bad_exit_type)
    bad_runtime_status = copy.deepcopy(valid)
    bad_runtime_status["runtime_status"] = "FAILED"
    _rehash(bad_runtime_status)
    mutations.append(bad_runtime_status)
    for changed in mutations:
        with pytest.raises(NSLReadBackendError):
            validate_nsl_backend_run(changed)

    crashed, _runtime = _adapter(
        _IsolationResult("CRASHED", None, 9, "ISOLATED_RUNTIME_CRASH")
    )
    invalid_crash = _execute(crashed)
    invalid_crash["exit_code"] = 0
    _rehash(invalid_crash)
    with pytest.raises(NSLReadBackendError, match="non-zero"):
        validate_nsl_backend_run(invalid_crash)

    failed, _runtime = _adapter(
        _IsolationResult("TIMED_OUT", None, -15, "ISOLATED_RUNTIME_TIMEOUT")
    )
    invalid_failure = _execute(failed)
    invalid_failure["progress_events"] = [{}]
    _rehash(invalid_failure)
    with pytest.raises(NSLReadBackendError, match="Failed"):
        validate_nsl_backend_run(invalid_failure)


def test_runtime_and_progress_validators_reject_exact_contract_drift() -> None:
    response = json.loads(_child_response())
    envelope = response["runtime_result_envelope"]
    invalid_envelopes = []
    invalid_envelopes.append([])
    changed = copy.deepcopy(envelope)
    changed["format"] = "OTHER"
    invalid_envelopes.append(changed)
    changed = copy.deepcopy(envelope)
    changed["runtime_result"].pop("checks")
    invalid_envelopes.append(changed)
    changed = copy.deepcopy(envelope)
    changed["runtime_result"]["completeness"] = "BAD"
    invalid_envelopes.append(changed)
    changed = copy.deepcopy(envelope)
    changed["runtime_result"]["outputs"] = "bad"
    invalid_envelopes.append(changed)
    changed = copy.deepcopy(envelope)
    changed["runtime_result"]["resources"] = {}
    invalid_envelopes.append(changed)
    changed = copy.deepcopy(envelope)
    changed["runtime_result"]["error"] = "bad"
    invalid_envelopes.append(changed)
    for value in invalid_envelopes:
        with pytest.raises(NSLReadBackendError):
            backend_module._validate_runtime_envelope(value, nsl_execution_id=NSL_ID)

    events = response["progress_events"]
    invalid_events = [[], [{}]]
    changed_events = copy.deepcopy(events)
    changed_events[0]["state"] = "RUNNING"
    invalid_events.append(changed_events)
    changed_events = copy.deepcopy(events)
    changed_events[-1]["state"] = "FAILED"
    invalid_events.append(changed_events)
    changed_events = copy.deepcopy(events)
    changed_events[0]["runtime_status"] = "RUNNING"
    invalid_events.append(changed_events)
    for value in invalid_events:
        with pytest.raises(NSLReadBackendError):
            backend_module._validate_progress_events(
                value,
                nsl_execution_id=NSL_ID,
                skill_id="FINANCE.PROJECT_BUDGET_CHECK",
                skill_version="1.0.0",
                runtime_status="COMPLETED",
            )


def test_child_request_and_failed_record_guards() -> None:
    artifact = _example("p6-golden-verified-artifact-v1.json")
    job = build_v01_skill_execution_job(
        request=_example("p6-golden-skill-execution-request-v1.json"),
        context_projection=_example("p6-golden-context-projection-v1.json"),
        artifact=artifact,
    )
    valid = {
        "format": "NEX-P6-NSL-V01-CHILD-REQUEST",
        "schema_version": "1.0",
        "backend_artifact_handle": artifact["backend_artifact_handle"],
        "job": job,
    }
    assert backend_module._decode_child_request(canonical_json(valid).encode()) == valid
    for changed in (
        {**valid, "extra": True},
        {**valid, "format": "OTHER"},
        {**valid, "job": []},
    ):
        with pytest.raises(NSLReadBackendError):
            backend_module._decode_child_request(canonical_json(changed).encode())

    request = _example("p6-golden-skill-execution-request-v1.json")
    with pytest.raises(NSLReadBackendError, match="mismatched"):
        backend_module._failed_backend_run(
            request=request,
            artifact={**artifact, "skill_id": "FINANCE.OTHER"},
            attempt_no=1,
            started_at=NOW,
            completed_at=NOW,
            isolation_status="TARGET_ERROR",
            error_code="TARGET_ERROR",
            exit_code=0,
            retryable=False,
        )


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    artifact = _example("p6-golden-verified-artifact-v1.json")
    context = _example("p6-golden-context-projection-v1.json")
    skill_binding = {
        "skill_id": artifact["skill_id"],
        "exact_skill_version": artifact["skill_version"],
        "skill_semantic_hash": artifact["skill_semantic_hash"],
        "runtime_contract_ref": artifact["runtime_contract_ref"],
        "trust_policy_id": artifact["trust_evidence"]["trust_policy_id"],
        "backend_profile": BACKEND_PROFILE,
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        connection.execute(
            text("""
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL, executable_plan_id TEXT,
                    step_type TEXT, executor_kind TEXT, required_capability TEXT,
                    capability_version TEXT, correlation_id TEXT NOT NULL,
                    causation_id TEXT, compiled_step_key TEXT, logical_step_id TEXT,
                    state TEXT NOT NULL, skill_binding_json TEXT,
                    PRIMARY KEY (tenant_id, executable_step_id)
                )
            """)
        )
        connection.execute(
            text("""
                CREATE TABLE ae_agent_context (
                    tenant_id TEXT NOT NULL, context_id TEXT NOT NULL,
                    context_generation INTEGER NOT NULL, agent_execution_id TEXT NOT NULL,
                    context_hash TEXT NOT NULL, PRIMARY KEY (tenant_id, context_id)
                )
            """)
        )
        for statement in skill_artifact_table_sql("sqlite"):
            connection.execute(text(statement))
        for statement in nsl_step_execution_table_sql("sqlite"):
            connection.execute(text(statement))
        for statement in nsl_backend_run_table_sql("sqlite"):
            connection.execute(text(statement))
        connection.execute(
            text("INSERT INTO ae_agent_context VALUES (:t, :c, 1, :e, :h)"),
            {
                "t": TENANT,
                "c": CONTEXT_ID,
                "e": EXECUTION_ID,
                "h": context["agent_context_hash"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_executable_step VALUES (
                    :t, :s, :e, :p, 'LOCAL_SKILL', 'LOCAL_SKILL',
                    :skill, '1.0.0', 'p6-golden-correlation',
                    'p6-golden-prompt', 'E1', 'S1', 'READY', :binding
                )
            """),
            {
                "t": TENANT,
                "s": STEP_ID,
                "e": EXECUTION_ID,
                "p": PLAN_ID,
                "skill": artifact["skill_id"],
                "binding": canonical_json(skill_binding),
            },
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    artifacts = SqlAlchemySkillArtifactRepository(factory)
    artifacts.save(tenant_id=TENANT, artifact=artifact)
    ids = iter((NSL_ID, BOI))
    bindings = SqlAlchemyNSLStepExecutionRepository(factory, id_factory=ids.__next__)
    bindings.bind_request(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        verified_artifact_ref=artifact["artifact_ref"],
        context_projection=context,
        compiled_inputs={"year": 2026},
        input_provenance={"year": "USER"},
        now=NOW,
    )
    yield engine, factory, bindings, artifacts
    engine.dispose()


def test_execution_service_marks_running_persists_and_replays_attempt(store) -> None:
    _engine, factory, bindings, artifacts = store
    backend, runtime = _adapter()
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    service = NSLReadExecutionService(
        bindings=bindings,
        artifacts=artifacts,
        backend=backend,
        runs=runs,
        clock=lambda: datetime(2026, 10, 14, 7, 0, 0, tzinfo=UTC),
    )

    first = service.execute_bound(
        tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
    )
    replay = service.execute_bound(
        tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
    )
    restarted = SqlAlchemyNSLBackendRunRepository(factory).get(
        tenant_id=TENANT, nsl_execution_id=NSL_ID, attempt_no=1
    )
    binding = bindings.get(tenant_id=TENANT, executable_step_id=STEP_ID)

    assert first == replay == restarted
    assert len(runtime.calls) == 1
    assert binding is not None
    assert binding["binding"]["state"] == "RUNNING"
    assert binding["binding"]["invocation_started_at"] == NOW


def test_backend_run_repository_is_immutable_and_restart_safe(store) -> None:
    _engine, factory, _bindings, _artifacts = store
    repository = SqlAlchemyNSLBackendRunRepository(factory)
    adapter, _runtime = _adapter()
    record = _execute(adapter)
    assert repository.save(record=record) == record
    assert repository.save(record=record) == record

    changed = copy.deepcopy(record)
    changed["completed_at"] = "2026-10-14T07:00:02Z"
    _rehash(changed)
    with pytest.raises(NSLReadBackendError) as caught:
        repository.save(record=changed)
    assert caught.value.error_code == "ae.nsl_backend_run_immutable_conflict"


def test_execution_service_and_repositories_fail_closed(store) -> None:
    engine, factory, bindings, artifacts = store
    backend, _runtime = _adapter()
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    service = NSLReadExecutionService(
        bindings=bindings, artifacts=artifacts, backend=backend, runs=runs
    )
    with pytest.raises(NSLReadBackendError) as caught:
        service.execute_bound(
            tenant_id="tenant-other", executable_step_id=STEP_ID, attempt_no=1
        )
    assert caught.value.error_code == "ae.nsl_backend_binding_not_found"

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_nsl_artifact"))
    with pytest.raises(NSLReadBackendError) as caught:
        service.execute_bound(
            tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
        )
    assert caught.value.error_code == "ae.nsl_backend_artifact_not_found"

    for field, value in (
        ("bindings", object()),
        ("artifacts", object()),
        ("backend", object()),
        ("runs", object()),
    ):
        values = {
            "bindings": bindings,
            "artifacts": artifacts,
            "backend": backend,
            "runs": runs,
        }
        values[field] = value
        with pytest.raises(NSLReadBackendError):
            NSLReadExecutionService(**values)  # type: ignore[arg-type]

    wrong_profile = types.SimpleNamespace(
        backend_profile="DIRECT", execute=lambda **_kwargs: {}
    )
    with pytest.raises(NSLReadBackendError, match="unsupported"):
        NSLReadExecutionService(
            bindings=bindings,
            artifacts=artifacts,
            backend=wrong_profile,
            runs=runs,
        )

    in_process_backend = types.SimpleNamespace(
        backend_profile="NSL_V01_IN_PROCESS", execute=lambda **_kwargs: {}
    )
    in_process_service = NSLReadExecutionService(
        bindings=bindings,
        artifacts=artifacts,
        backend=in_process_backend,
        runs=runs,
    )
    with pytest.raises(NSLReadBackendError) as mismatch:
        in_process_service.execute_bound(
            tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
        )
    assert mismatch.value.error_code == "ae.nsl_backend_profile_mismatch"
    assert mismatch.value.retryable is True


def test_mark_invocation_started_is_idempotent_and_state_guarded(store) -> None:
    engine, _factory, bindings, _artifacts = store
    first = bindings.mark_invocation_started(
        tenant_id=TENANT, executable_step_id=STEP_ID, now=NOW
    )
    assert (
        bindings.mark_invocation_started(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            now="2026-10-14T08:00:00Z",
        )
        == first
    )
    with engine.begin() as connection:
        binding = copy.deepcopy(first["binding"])
        binding.update(
            state="SUCCEEDED",
            completed_at="2026-10-14T08:00:00Z",
            result_summary_ref=f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
            result_summary_hash="sha256:" + "a" * 64,
        )
        connection.execute(
            text(
                "UPDATE ae_nsl_step_execution SET state = 'SUCCEEDED', "
                "binding_json = :binding WHERE tenant_id = :tenant"
            ),
            {"binding": canonical_json(binding), "tenant": TENANT},
        )
    with pytest.raises(NSLStepExecutionError) as caught:
        bindings.mark_invocation_started(
            tenant_id=TENANT, executable_step_id=STEP_ID, now=NOW
        )
    assert caught.value.error_code == "ae.nsl_binding_state_conflict"


def test_backend_run_store_unavailable_and_low_level_guards() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyNSLBackendRunRepository(sessionmaker(bind=engine))
    with pytest.raises(NSLReadBackendError) as caught:
        repository.get(tenant_id=TENANT, nsl_execution_id=NSL_ID, attempt_no=1)
    assert caught.value.error_code == "ae.nsl_backend_run_store_unavailable"
    assert caught.value.retryable is True
    adapter, _runtime = _adapter()
    with pytest.raises(NSLReadBackendError) as caught:
        repository.save(record=_execute(adapter))
    assert caught.value.error_code == "ae.nsl_backend_run_store_unavailable"
    engine.dispose()

    with pytest.raises(NSLReadBackendError, match="canonical JSON"):
        backend_module._canonical_bytes_object(b'{"b":1, "a":2}', "fixture")
    for value in (b"", b"not-json", b"[]"):
        with pytest.raises(NSLReadBackendError):
            backend_module._canonical_bytes_object(value, "fixture")
    with pytest.raises(NSLReadBackendError, match="object"):
        backend_module._canonical_mapping("fixture", [])
    with pytest.raises(NSLReadBackendError, match="canonical JSON"):
        backend_module._canonical_mapping("fixture", {"bad": {1, 2}})
    with pytest.raises(NSLReadBackendError, match="invalid value"):
        backend_module._clock_timestamp(lambda: "bad")  # type: ignore[arg-type]
    with pytest.raises(NSLReadBackendError, match="timezone-aware"):
        backend_module._clock_timestamp(
            lambda: datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
        )
    with pytest.raises(NSLReadBackendError, match="UUID"):
        backend_module._uuid("id", "NOT-A-UUID")
    with pytest.raises(NSLReadBackendError, match="UUID"):
        backend_module._uuid("id", None)
    with pytest.raises(NSLReadBackendError, match="canonical UUID"):
        backend_module._uuid("id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA")
    with pytest.raises(NSLReadBackendError, match="SHA-256"):
        backend_module._hash("hash", "bad")
    with pytest.raises(NSLReadBackendError, match="bounded string"):
        backend_module._text("text", "", 10)
    with pytest.raises(NSLReadBackendError, match="between"):
        backend_module._bounded_int("count", True, 0, 1)
    for value in (None, "not-time", "2026-10-14T07:00:00"):
        with pytest.raises(NSLReadBackendError):
            backend_module._timestamp("time", value)
    with pytest.raises(NSLReadBackendError, match="array"):
        backend_module._canonical_refs("not-an-array")
    with pytest.raises(NSLReadBackendError, match="unique"):
        backend_module._canonical_refs(["same", "same"])
    assert "JSONB" in nsl_backend_run_table_sql("postgresql")[1]
    assert "CAST(:record_json AS JSONB)" in backend_module._backend_run_insert_sql(
        "postgresql"
    )


def test_migration_is_additive_short_named_and_binding_scoped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    names = (
        "ae_nsl_backend_run",
        "uq_ae_nsl_step_run_ref",
        "pk_ae_nsl_backend_run",
        "fk_ae_nsl_run_binding",
        "ck_ae_nsl_run_attempt",
        "ck_ae_nsl_run_isolation",
        "ck_ae_nsl_run_runtime",
        "ck_ae_nsl_run_hash",
        "ck_ae_nsl_run_json",
        "idx_ae_nsl_run_step",
        "idx_ae_nsl_run_state",
    )
    assert "2204_ae_nsl_backend_run" in sql
    assert "executable_step_id TEXT NOT NULL" in sql
    assert "tenant_id, executable_step_id, nsl_execution_id" in sql
    assert all(len(name) <= 30 for name in names)
