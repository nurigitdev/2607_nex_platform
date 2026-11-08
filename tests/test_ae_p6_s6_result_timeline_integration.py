from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import nex_ae_api.agent_execution_timeline as timeline_module
import nex_ae_api.nsl_result_integration as result_module
import pytest
from nex_ae_api.agent_execution_timeline import (
    AgentExecutionTimelineError,
    SqlAlchemyAgentExecutionTimeline,
    build_agent_execution_timeline,
    validate_agent_execution_timeline,
)
from nex_ae_api.nsl_read_backends import (
    SqlAlchemyNSLBackendRunRepository,
    nsl_backend_run_table_sql,
)
from nex_ae_api.nsl_result_integration import (
    NSLResultIntegrationError,
    NSLResultIntegrationService,
    build_nsl_result_summary,
    build_step_execution_outcome,
    to_p5_executor_outcome,
    validate_nsl_result_summary,
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
from nex_ae_api.step_executors import P5ExecutorOutcome
from nex_ae_api.step_results import build_step_result
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/transition/P6/contracts/examples"
TENANT = "tenant-p6-golden"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
NSL_ID = "66666666-6666-4666-8666-666666666666"
BOI = "77777777-7777-4777-8777-777777777777"
RESULT_ID = "88888888-8888-4888-8888-888888888888"
NOW = "2026-10-14T07:00:00Z"
COMPLETED = "2026-10-14T07:00:01Z"


def _example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _binding(*, state: str = "RUNNING") -> dict[str, Any]:
    value = _example("p6-golden-step-execution-binding-v1.json")
    value.update(
        {
            "state": state,
            "result_summary_ref": None,
            "result_summary_hash": None,
            "completed_at": None,
            "updated_at": NOW,
        }
    )
    return value


def _progress(sequence: int, state: str, runtime_status: str) -> dict[str, Any]:
    terminal = state in {"COMPLETED", "FAILED"}
    return {
        "format": "NEX-NSL-EXECUTION-PROGRESS",
        "schema_version": "1.0",
        "execution_id": NSL_ID,
        "sequence": sequence,
        "state": state,
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "skill_version": "1.0.0",
        "runtime_status": runtime_status if terminal else None,
        "error_code": None if not terminal or state == "COMPLETED" else "FAILED",
    }


def _backend_run(status: str = "COMPLETED") -> dict[str, Any]:
    terminal = "COMPLETED" if status == "COMPLETED" else "FAILED"
    runtime = {
        "schema_version": "1.0",
        "execution_id": NSL_ID,
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "skill_version": "1.0.0",
        "semantic_hash": _example("p6-golden-verified-artifact-v1.json")[
            "skill_semantic_hash"
        ],
        "status": status,
        "completeness": "COMPLETE" if status == "COMPLETED" else "PARTIAL",
        "checks": [],
        "outputs": [{"budget": 100_000_000}] if status == "COMPLETED" else [],
        "resources": {
            "tool_calls": 2,
            "loop_iterations": 1,
            "emitted_rows": 1,
            "max_collection_size_seen": 3,
        },
        "error": None if status in {"COMPLETED", "CANCELLED"} else {"code": status},
    }
    record = {
        "schema_version": "1.0",
        "tenant_id": TENANT,
        "executable_step_id": STEP_ID,
        "nsl_execution_id": NSL_ID,
        "business_operation_id": BOI,
        "attempt_no": 1,
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
        "isolation_status": "COMPLETED",
        "runtime_status": status,
        "runtime_result_envelope": {
            "format": "NEX-NSL-RUNTIME-RESULT",
            "schema_version": "1.0",
            "runtime_result": runtime,
        },
        "progress_events": [
            _progress(1, "STARTED", status),
            _progress(2, "SKILL_RESOLVED", status),
            _progress(3, "RUNNING", status),
            _progress(4, terminal, status),
        ],
        "evidence_refs": sorted(
            [
                f"AE:NSL_BACKEND_RUN:{NSL_ID}:1",
                f"NSL:AUDIT:{NSL_ID}",
                f"NSL:SNAPSHOT:{NSL_ID}",
            ]
        ),
        "error_code": None,
        "exit_code": 0,
        "retryable": False,
        "started_at": NOW,
        "completed_at": COMPLETED,
    }
    record["record_hash"] = semantic_sha256_hash_ref(record)
    return record


def _terminal_binding(summary: dict[str, Any]) -> dict[str, Any]:
    state = {
        "COMPLETED": "SUCCEEDED",
        "VALIDATION_ERROR": "BLOCKED",
        "CANCELLED": "CANCELLED",
    }.get(summary["execution_status"], "FAILED")
    value = _binding(state=state)
    value.update(
        {
            "result_summary_ref": f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
            "result_summary_hash": semantic_sha256_hash_ref(summary),
            "completed_at": COMPLETED,
            "updated_at": COMPLETED,
        }
    )
    return value


def test_completed_result_maps_to_bounded_summary_and_p6_executor_outcome() -> None:
    summary = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(),
    )
    terminal = _terminal_binding(summary)
    outcome = build_step_execution_outcome(summary=summary, binding=terminal)
    executor_outcome = to_p5_executor_outcome(outcome)

    assert summary["execution_status"] == "COMPLETED"
    assert summary["result_ref"] == f"AE:NSL_RUNTIME_RESULT:{NSL_ID}:1"
    assert summary["result_hash"].startswith("sha256:")
    assert "outputs" not in summary
    assert "runtime_result_envelope" not in summary
    assert outcome.state == "SUCCEEDED"
    assert outcome.result_payload == {
        "nsl_result_summary_ref": f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
        "nsl_execution_id": NSL_ID,
        "execution_status": "COMPLETED",
    }
    assert isinstance(executor_outcome, P5ExecutorOutcome)
    assert executor_outcome.business_operation_id == BOI
    assert executor_outcome.started_at == NOW
    assert executor_outcome.completed_at == COMPLETED


@pytest.mark.parametrize(
    ("runtime_status", "expected_state"),
    [
        ("COMPLETED", "SUCCEEDED"),
        ("FAILED", "FAILED"),
        ("TOOL_ERROR", "FAILED"),
        ("VALIDATION_ERROR", "BLOCKED"),
        ("LIMIT_EXCEEDED", "FAILED"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_terminal_runtime_status_mapping_is_exhaustive(
    runtime_status: str, expected_state: str
) -> None:
    summary = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(runtime_status),
    )
    outcome = build_step_execution_outcome(
        summary=summary, binding=_terminal_binding(summary)
    )

    assert outcome.state == expected_state
    assert (summary["result_ref"] is not None) is (runtime_status == "COMPLETED")
    assert (summary["error_code"] is not None) is (
        runtime_status not in {"COMPLETED", "CANCELLED"}
    )


def test_result_summary_rejects_isolation_failure_and_lineage_drift() -> None:
    failed = _backend_run()
    failed.update(
        {
            "isolation_status": "TIMED_OUT",
            "runtime_status": None,
            "runtime_result_envelope": None,
            "progress_events": [],
            "error_code": "ISOLATED_RUNTIME_TIMEOUT",
            "exit_code": None,
            "retryable": True,
        }
    )
    failed["record_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in failed.items() if key != "record_hash"}
    )
    with pytest.raises(NSLResultIntegrationError, match="isolated backend failure"):
        build_nsl_result_summary(
            binding=_binding(),
            artifact=_example("p6-golden-verified-artifact-v1.json"),
            backend_run=failed,
        )

    drifted = _binding()
    drifted["verified_artifact_hash"] = "sha256:" + "0" * 64
    with pytest.raises(NSLResultIntegrationError, match="lineage"):
        build_nsl_result_summary(
            binding=drifted,
            artifact=_example("p6-golden-verified-artifact-v1.json"),
            backend_run=_backend_run(),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(schema_version="2.0"),
        lambda value: value.update(pre_write_eligibility=True),
        lambda value: value.update(result_ref=None),
        lambda value: value.update(error_code="BAD"),
        lambda value: value.update(resource_summary={}),
        lambda value: value.update(evidence_refs=["same", "same"]),
    ],
)
def test_result_summary_validation_fails_closed(mutator) -> None:
    value = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(),
    )
    mutator(value)
    with pytest.raises(NSLResultIntegrationError):
        validate_nsl_result_summary(value)


class _Bindings:
    def __init__(self, value: dict[str, Any] | None) -> None:
        self.value = value
        self.calls = 0

    def get(self, **_kwargs):
        return None if self.value is None else {"binding": self.value}

    def mark_result_terminal(self, **kwargs):
        self.calls += 1
        assert self.value is not None
        self.value = {
            **self.value,
            "state": kwargs["state"],
            "result_summary_ref": kwargs["result_summary_ref"],
            "result_summary_hash": kwargs["result_summary_hash"],
            "completed_at": kwargs["completed_at"],
            "updated_at": kwargs["completed_at"],
        }
        return {"binding": self.value}


class _Lookup:
    def __init__(self, value: dict[str, Any] | None) -> None:
        self.value = value

    def get(self, **_kwargs):
        return self.value


def test_result_integration_service_terminalizes_and_replays() -> None:
    bindings = _Bindings(_binding())
    service = NSLResultIntegrationService(
        bindings=bindings,  # type: ignore[arg-type]
        artifacts=_Lookup(_example("p6-golden-verified-artifact-v1.json")),
        runs=_Lookup(_backend_run()),  # type: ignore[arg-type]
    )

    first = service.finalize_bound(
        tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
    )
    second = service.finalize_bound(
        tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
    )

    assert first.summary == second.summary
    assert first.outcome == second.outcome
    assert first.binding["state"] == "SUCCEEDED"
    assert first.summary_hash == first.binding["result_summary_hash"]
    assert bindings.calls == 2


@pytest.mark.parametrize("missing", ["binding", "artifact", "run"])
def test_result_integration_service_requires_all_durable_sources(missing: str) -> None:
    service = NSLResultIntegrationService(
        bindings=_Bindings(None if missing == "binding" else _binding()),  # type: ignore[arg-type]
        artifacts=_Lookup(
            None
            if missing == "artifact"
            else _example("p6-golden-verified-artifact-v1.json")
        ),
        runs=_Lookup(None if missing == "run" else _backend_run()),  # type: ignore[arg-type]
    )
    with pytest.raises(NSLResultIntegrationError, match="requires"):
        service.finalize_bound(
            tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
        )


@pytest.fixture
def sqlite_store():
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
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
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
                "c": "44444444-4444-4444-8444-444444444444",
                "e": EXECUTION_ID,
                "h": context["agent_context_hash"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_executable_step VALUES (
                    :t, :s, :e, :p, 'LOCAL_SKILL', 'LOCAL_SKILL',
                    :skill, '1.0.0', 'corr-p6-s6', 'cause-p6-s6',
                    'E1', 'S1', 'READY', :binding
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
    bindings.mark_invocation_started(
        tenant_id=TENANT, executable_step_id=STEP_ID, now=NOW
    )
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    runs.save(record=_backend_run())
    yield factory, bindings, artifacts, runs
    engine.dispose()


def test_sqlite_binding_terminalization_and_result_service_are_restart_safe(
    sqlite_store,
) -> None:
    factory, bindings, artifacts, runs = sqlite_store
    service = NSLResultIntegrationService(
        bindings=bindings, artifacts=artifacts, runs=runs
    )

    first = service.finalize_bound(
        tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1
    )
    restarted = NSLResultIntegrationService(
        bindings=SqlAlchemyNSLStepExecutionRepository(factory),
        artifacts=SqlAlchemySkillArtifactRepository(factory),
        runs=SqlAlchemyNSLBackendRunRepository(factory),
    ).finalize_bound(tenant_id=TENANT, executable_step_id=STEP_ID, attempt_no=1)

    assert first == restarted
    assert first.binding["state"] == "SUCCEEDED"
    assert first.binding["result_summary_ref"] == first.summary_ref
    with pytest.raises(NSLStepExecutionError, match="different terminal evidence"):
        bindings.mark_result_terminal(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            state="FAILED",
            result_summary_ref=first.summary_ref,
            result_summary_hash=first.summary_hash,
            completed_at=COMPLETED,
        )


def _timeline() -> dict[str, Any]:
    summary = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(),
    )
    terminal = _terminal_binding(summary)
    step_result = build_step_result(
        step_result_id=RESULT_ID,
        execution_id=EXECUTION_ID,
        executable_plan_id=PLAN_ID,
        executable_step_id=STEP_ID,
        compiled_step_key="E1",
        logical_step_ref="S1",
        executor_kind="LOCAL_SKILL",
        business_operation_id=BOI,
        attempt_no=1,
        status="SUCCEEDED",
        result_contract_ref="contract://nex/ae/nsl-read-result/v1",
        result_payload={
            "nsl_result_summary_ref": f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
            "nsl_execution_id": NSL_ID,
            "execution_status": "COMPLETED",
        },
        artifact_refs=(terminal["verified_artifact_ref"],),
        evidence_refs=tuple(summary["evidence_refs"]),
        started_at=NOW,
        completed_at=COMPLETED,
    )
    return build_agent_execution_timeline(
        tenant_id=TENANT,
        execution={
            "agent_execution_id": EXECUTION_ID,
            "state": "RUNNING",
            "phase": "STEP_EXECUTION",
            "version": 4,
            "source_type": "PROMPT",
            "correlation_id": "corr-p6-s6",
            "causation_id": "prompt-p6-s6",
            "received_at": NOW,
            "created_at": NOW,
            "updated_at": COMPLETED,
            "completed_at": None,
        },
        plans=[
            {
                "executable_plan_id": PLAN_ID,
                "executable_plan_version": 1,
                "plan_hash": "sha256:" + "1" * 64,
                "compiled_at": NOW,
            }
        ],
        steps=[
            {
                "executable_step_id": STEP_ID,
                "logical_step_id": "S1",
                "compiled_step_key": "E1",
                "executor_kind": "LOCAL_SKILL",
                "state": "SUCCEEDED",
                "version": 3,
                "result_ref": f"AE:STEP_RESULT:{RESULT_ID}",
                "error_ref": None,
                "created_at": NOW,
                "updated_at": COMPLETED,
            }
        ],
        jobs=[
            {
                "runtime_job_id": "job-p6-s6",
                "job_type": "START_EXECUTION",
                "executable_step_id": STEP_ID,
                "state": "DONE",
                "attempt_no": 1,
                "created_at": NOW,
                "updated_at": COMPLETED,
            }
        ],
        attempts=[
            {
                "attempt_id": "attempt-p6-s6",
                "runtime_job_id": "job-p6-s6",
                "attempt_no": 1,
                "worker_id": "worker-p6-s6",
                "started_at": NOW,
                "ended_at": COMPLETED,
                "outcome": "DONE",
                "error_ref": None,
            }
        ],
        bindings=[{"binding_json": terminal}],
        backend_runs=[{"record_json": _backend_run()}],
        step_results=[{"result_json": step_result}],
        agent_results=[
            {
                "result_id": "99999999-9999-4999-8999-999999999999",
                "status": "SUCCEEDED",
                "result_hash": "sha256:" + "2" * 64,
                "created_at": COMPLETED,
            }
        ],
        deliveries=[
            {
                "delivery_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "target_type": "WORKSPACE_RESULT",
                "required": True,
                "state": "PENDING",
                "attempt_no": 0,
                "created_at": COMPLETED,
                "updated_at": COMPLETED,
                "acknowledged_at": None,
            }
        ],
    )


def test_timeline_is_deterministic_complete_over_retained_evidence_and_bounded() -> (
    None
):
    first = _timeline()
    second = _timeline()

    assert first == second
    assert first["projection_hash"] == second["projection_hash"]
    assert [event["sequence"] for event in first["events"]] == list(
        range(1, len(first["events"]) + 1)
    )
    assert {event["event_type"] for event in first["events"]} >= {
        "EXECUTION_ADMITTED",
        "PLAN_COMPILED",
        "JOB_ATTEMPT_STARTED",
        "NSL_PROGRESS_SKILL_RESOLVED",
        "NSL_RESULT_SUMMARY_RECORDED",
        "STEP_RESULT_RECORDED",
        "AGENT_RESULT_RECORDED",
        "RESULT_DELIVERY_CREATED",
    }
    assert {gap["gap_code"] for gap in first["projection_gaps"]} == {
        "EXECUTION_TRANSITION_HISTORY_UNAVAILABLE",
        "NSL_PROGRESS_TIMESTAMPS_UNAVAILABLE",
        "STEP_TRANSITION_HISTORY_UNAVAILABLE",
    }
    serialized = json.dumps(first, sort_keys=True)
    assert "100000000" not in serialized
    assert "runtime_result_envelope" not in serialized


def test_timeline_validation_rejects_reordering_private_details_and_hash_drift() -> (
    None
):
    reordered = _timeline()
    reordered["events"][0], reordered["events"][-1] = (
        reordered["events"][-1],
        reordered["events"][0],
    )
    with pytest.raises(AgentExecutionTimelineError, match="sequence|ordered"):
        validate_agent_execution_timeline(reordered)

    private = _timeline()
    private["events"][0]["details"]["prompt"] = "private"
    with pytest.raises(AgentExecutionTimelineError, match="private"):
        validate_agent_execution_timeline(private)

    changed = copy.deepcopy(_timeline())
    changed["source_counts"]["jobs"] = 99
    with pytest.raises(AgentExecutionTimelineError, match="hash"):
        validate_agent_execution_timeline(changed)


def _timeline_repository_factory(*, seed: bool):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for ddl in (
            """CREATE TABLE ae_agent_execution (
                tenant_id TEXT, agent_execution_id TEXT, state TEXT, phase TEXT,
                version INTEGER, source_type TEXT, correlation_id TEXT,
                causation_id TEXT, received_at TEXT, created_at TEXT,
                updated_at TEXT, completed_at TEXT)""",
            """CREATE TABLE ae_executable_plan (
                tenant_id TEXT, executable_plan_id TEXT,
                executable_plan_version INTEGER, agent_execution_id TEXT,
                plan_hash TEXT, compiled_at TEXT)""",
            """CREATE TABLE ae_executable_step (
                tenant_id TEXT, executable_step_id TEXT, agent_execution_id TEXT,
                logical_step_id TEXT, compiled_step_key TEXT, step_index INTEGER,
                executor_kind TEXT, state TEXT, version INTEGER, result_ref TEXT,
                error_ref TEXT, created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE ae_runtime_job (
                tenant_id TEXT, runtime_job_id TEXT, job_type TEXT,
                execution_id TEXT, executable_step_id TEXT, state TEXT,
                attempt_no INTEGER, created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE ae_runtime_job_attempt (
                tenant_id TEXT, attempt_id TEXT, runtime_job_id TEXT,
                attempt_no INTEGER, worker_id TEXT, started_at TEXT,
                ended_at TEXT, outcome TEXT, error_ref TEXT)""",
            """CREATE TABLE ae_nsl_step_execution (
                tenant_id TEXT, agent_execution_id TEXT, executable_step_id TEXT,
                nsl_execution_id TEXT, allocated_at TEXT, binding_json TEXT)""",
            """CREATE TABLE ae_nsl_backend_run (
                tenant_id TEXT, nsl_execution_id TEXT, attempt_no INTEGER,
                started_at TEXT, record_json TEXT)""",
            """CREATE TABLE ae_step_result (
                tenant_id TEXT, agent_execution_id TEXT, step_result_id TEXT,
                completed_at TEXT, result_json TEXT)""",
            """CREATE TABLE ae_agent_result (
                tenant_id TEXT, agent_execution_id TEXT, result_id TEXT,
                status TEXT, result_hash TEXT, created_at TEXT)""",
            """CREATE TABLE ae_result_delivery (
                tenant_id TEXT, agent_execution_id TEXT, delivery_id TEXT,
                target_type TEXT, required BOOLEAN, state TEXT,
                attempt_no INTEGER, created_at TEXT, updated_at TEXT,
                acknowledged_at TEXT)""",
        ):
            connection.execute(text(ddl))
        if seed:
            summary = build_nsl_result_summary(
                binding=_binding(),
                artifact=_example("p6-golden-verified-artifact-v1.json"),
                backend_run=_backend_run(),
            )
            terminal = _terminal_binding(summary)
            step_result = build_step_result(
                step_result_id=RESULT_ID,
                execution_id=EXECUTION_ID,
                executable_plan_id=PLAN_ID,
                executable_step_id=STEP_ID,
                compiled_step_key="E1",
                logical_step_ref="S1",
                executor_kind="LOCAL_SKILL",
                business_operation_id=BOI,
                attempt_no=1,
                status="SUCCEEDED",
                result_contract_ref="contract://nex/ae/nsl-read-result/v1",
                result_payload={
                    "nsl_result_summary_ref": f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
                    "nsl_execution_id": NSL_ID,
                    "execution_status": "COMPLETED",
                },
                artifact_refs=(terminal["verified_artifact_ref"],),
                evidence_refs=tuple(summary["evidence_refs"]),
                started_at=NOW,
                completed_at=COMPLETED,
            )
            statements = (
                (
                    (
                        "INSERT INTO ae_agent_execution VALUES "
                        "(:t,:e,'RUNNING','STEP_EXECUTION',4,'PROMPT','corr','cause',"
                        ":now,:now,:done,NULL)"
                    ),
                    {},
                ),
                (
                    "INSERT INTO ae_executable_plan VALUES (:t,:p,1,:e,:hash,:now)",
                    {"hash": "sha256:" + "1" * 64},
                ),
                (
                    (
                        "INSERT INTO ae_executable_step VALUES "
                        "(:t,:s,:e,'S1','E1',0,'LOCAL_SKILL','SUCCEEDED',3,"
                        ":result_ref,NULL,:now,:done)"
                    ),
                    {"result_ref": f"AE:STEP_RESULT:{RESULT_ID}"},
                ),
                (
                    (
                        "INSERT INTO ae_runtime_job VALUES "
                        "(:t,'job-p6-s6','START_EXECUTION',:e,:s,'DONE',1,:now,:done)"
                    ),
                    {},
                ),
                (
                    (
                        "INSERT INTO ae_runtime_job_attempt VALUES "
                        "(:t,'attempt-p6-s6','job-p6-s6',1,'worker-p6-s6',"
                        ":now,:done,'DONE',NULL)"
                    ),
                    {},
                ),
                (
                    (
                        "INSERT INTO ae_nsl_step_execution VALUES "
                        "(:t,:e,:s,:nsl,:now,:json)"
                    ),
                    {"nsl": NSL_ID, "json": canonical_json(terminal)},
                ),
                (
                    "INSERT INTO ae_nsl_backend_run VALUES (:t,:nsl,1,:now,:json)",
                    {"nsl": NSL_ID, "json": canonical_json(_backend_run())},
                ),
                (
                    "INSERT INTO ae_step_result VALUES (:t,:e,:result_id,:done,:json)",
                    {"result_id": RESULT_ID, "json": canonical_json(step_result)},
                ),
                (
                    (
                        "INSERT INTO ae_agent_result VALUES "
                        "(:t,:e,'99999999-9999-4999-8999-999999999999',"
                        "'SUCCEEDED',:hash,:done)"
                    ),
                    {"hash": "sha256:" + "2" * 64},
                ),
                (
                    (
                        "INSERT INTO ae_result_delivery VALUES "
                        "(:t,:e,'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',"
                        "'WORKSPACE_RESULT',1,'PENDING',0,:done,:done,NULL)"
                    ),
                    {},
                ),
            )
            base = {
                "t": TENANT,
                "e": EXECUTION_ID,
                "p": PLAN_ID,
                "s": STEP_ID,
                "now": NOW,
                "done": COMPLETED,
            }
            for sql, params in statements:
                connection.execute(text(sql), {**base, **params})
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_timeline_repository_reads_all_canonical_sources() -> None:
    repository = SqlAlchemyAgentExecutionTimeline(
        _timeline_repository_factory(seed=True)
    )

    projection = repository.project(tenant_id=TENANT, agent_execution_id=EXECUTION_ID)

    assert projection["source_counts"] == {
        "agent_execution": 1,
        "agent_results": 1,
        "backend_runs": 1,
        "bindings": 1,
        "deliveries": 1,
        "jobs": 1,
        "plans": 1,
        "runtime_attempts": 1,
        "step_results": 1,
        "steps": 1,
    }
    assert projection["events"][-1]["event_time"] == COMPLETED


def test_timeline_repository_distinguishes_not_found_and_store_failure() -> None:
    repository = SqlAlchemyAgentExecutionTimeline(
        _timeline_repository_factory(seed=False)
    )
    with pytest.raises(AgentExecutionTimelineError) as not_found:
        repository.project(tenant_id=TENANT, agent_execution_id=EXECUTION_ID)
    assert not_found.value.error_code == "ae.execution_timeline_not_found"

    empty = create_engine("sqlite+pysqlite:///:memory:")
    unavailable = SqlAlchemyAgentExecutionTimeline(sessionmaker(bind=empty))
    with pytest.raises(AgentExecutionTimelineError) as failed:
        unavailable.project(tenant_id=TENANT, agent_execution_id=EXECUTION_ID)
    assert failed.value.error_code == "ae.execution_timeline_unavailable"
    assert failed.value.retryable is True


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(schema_version="2.0"),
        lambda value: value.update(ordering_profile="bad"),
        lambda value: value.update(events="bad"),
        lambda value: value["events"][0].pop("state"),
        lambda value: value["events"][0].update(sequence=2),
        lambda value: value["events"][0].update(event_time_basis="bad"),
        lambda value: value["events"][0].update(phase="bad"),
        lambda value: value["events"][0].update(evidence_refs=["z", "a"]),
        lambda value: value.update(projection_gaps="bad"),
        lambda value: value["projection_gaps"][0].pop("detail"),
        lambda value: value.update(source_counts={"bad": -1}),
    ],
)
def test_timeline_contract_negative_matrix(mutator) -> None:
    value = _timeline()
    mutator(value)
    with pytest.raises(AgentExecutionTimelineError):
        validate_agent_execution_timeline(value)


def test_timeline_validation_detects_ordering_without_sequence_drift() -> None:
    value = _timeline()
    value["events"][0]["event_time"] = "2099-01-01T00:00:00Z"
    with pytest.raises(AgentExecutionTimelineError, match="ordered"):
        validate_agent_execution_timeline(value)


def test_timeline_internal_guards_cover_nested_privacy_and_malformed_values() -> None:
    with pytest.raises(AgentExecutionTimelineError, match="private"):
        timeline_module._safe_details({"nested": [{"token": "secret"}]})
    with pytest.raises(AgentExecutionTimelineError, match="size"):
        timeline_module._safe_details({"safe": "x" * 20_000})
    assert timeline_module._json_object('{"safe":true}') == {"safe": True}
    with pytest.raises(AgentExecutionTimelineError, match="object"):
        timeline_module._json_object([])
    with pytest.raises(AgentExecutionTimelineError, match="object"):
        timeline_module._canonical_mapping("value", [])
    with pytest.raises(AgentExecutionTimelineError, match="array"):
        timeline_module._refs("bad", 1)
    with pytest.raises(AgentExecutionTimelineError, match="unique"):
        timeline_module._refs(["same", "same"], 2)
    with pytest.raises(AgentExecutionTimelineError, match="UUID"):
        timeline_module._uuid("id", 1)
    with pytest.raises(AgentExecutionTimelineError, match="UUID"):
        timeline_module._uuid("id", "bad")
    with pytest.raises(AgentExecutionTimelineError, match="canonical"):
        timeline_module._uuid("id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA")
    with pytest.raises(AgentExecutionTimelineError, match="SHA-256"):
        timeline_module._hash("hash", "bad")
    with pytest.raises(AgentExecutionTimelineError, match="bounded"):
        timeline_module._text("text", "", 1)
    with pytest.raises(AgentExecutionTimelineError, match="timestamp"):
        timeline_module._timestamp("time", 1)
    with pytest.raises(AgentExecutionTimelineError, match="timestamp"):
        timeline_module._timestamp("time", "bad")
    with pytest.raises(AgentExecutionTimelineError, match="timezone"):
        timeline_module._timestamp("time", "2026-01-01T00:00:00")
    assert timeline_module._json_value(UUID(EXECUTION_ID)) == EXECUTION_ID
    assert timeline_module._json_value(3) == 3
    assert (
        timeline_module._timestamp(
            "time", datetime.fromisoformat("2026-01-01T00:00:00")
        )
        == "2026-01-01T00:00:00Z"
    )


def test_result_summary_internal_guards_and_dependency_checks() -> None:
    with pytest.raises(NSLResultIntegrationError, match="binding repository"):
        NSLResultIntegrationService(
            bindings=object(),
            artifacts=_Lookup({}),
            runs=_Lookup({}),  # type: ignore[arg-type]
        )
    with pytest.raises(NSLResultIntegrationError, match="artifact repository"):
        NSLResultIntegrationService(
            bindings=_Bindings(_binding()),
            artifacts=object(),
            runs=_Lookup({}),  # type: ignore[arg-type]
        )
    with pytest.raises(NSLResultIntegrationError, match="backend-run repository"):
        NSLResultIntegrationService(
            bindings=_Bindings(_binding()),
            artifacts=_Lookup({}),
            runs=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(NSLResultIntegrationError, match="object"):
        result_module._mapping("value", [])
    with pytest.raises(NSLResultIntegrationError, match="array"):
        result_module._refs("bad", 1)
    with pytest.raises(NSLResultIntegrationError, match="UUID"):
        result_module._uuid("id", 1)
    with pytest.raises(NSLResultIntegrationError, match="UUID"):
        result_module._uuid("id", "bad")
    with pytest.raises(NSLResultIntegrationError, match="canonical"):
        result_module._uuid("id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA")
    with pytest.raises(NSLResultIntegrationError, match="SHA-256"):
        result_module._hash("hash", "bad")
    with pytest.raises(NSLResultIntegrationError, match="timestamp"):
        result_module._timestamp("time", 1)
    with pytest.raises(NSLResultIntegrationError, match="timestamp"):
        result_module._timestamp("time", "bad")
    with pytest.raises(NSLResultIntegrationError, match="timezone"):
        result_module._timestamp("time", "2026-01-01T00:00:00")
    with pytest.raises(NSLResultIntegrationError, match="between"):
        result_module._bounded_int("count", True, 0, 1)


def test_result_summary_rejects_runtime_and_contract_semantic_drift() -> None:
    completed_with_error = _backend_run()
    completed_with_error["runtime_result_envelope"]["runtime_result"]["error"] = {
        "code": "IMPOSSIBLE"
    }
    completed_with_error["record_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in completed_with_error.items()
            if key != "record_hash"
        }
    )
    with pytest.raises(NSLResultIntegrationError, match="Completed NSL result"):
        build_nsl_result_summary(
            binding=_binding(),
            artifact=_example("p6-golden-verified-artifact-v1.json"),
            backend_run=completed_with_error,
        )

    baseline = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(),
    )
    mutations = (
        ("business_operation_id", NSL_ID, "distinct"),
        ("execution_status", "BAD", "status"),
        ("completeness", "BAD", "completeness"),
        ("evidence_refs", ["z", "a"], "canonical"),
    )
    for field, value, message in mutations:
        changed = copy.deepcopy(baseline)
        changed[field] = value
        with pytest.raises(NSLResultIntegrationError, match=message):
            validate_nsl_result_summary(changed)

    failed = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run("FAILED"),
    )
    failed["result_ref"] = f"AE:NSL_RUNTIME_RESULT:{NSL_ID}:1"
    failed["result_hash"] = "sha256:" + "1" * 64
    with pytest.raises(NSLResultIntegrationError, match="cannot carry a result"):
        validate_nsl_result_summary(failed)
    failed["result_ref"] = None
    failed["result_hash"] = None
    failed["error_code"] = None
    failed["error_ref"] = None
    with pytest.raises(NSLResultIntegrationError, match="requires bounded error"):
        validate_nsl_result_summary(failed)


def test_step_execution_outcome_rejects_binding_lineage_and_evidence_drift() -> None:
    summary = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=_backend_run(),
    )
    lineage = _terminal_binding(summary)
    lineage["skill_id"] = "OTHER.SKILL"
    with pytest.raises(NSLResultIntegrationError, match="lineage"):
        build_step_execution_outcome(summary=summary, binding=lineage)

    terminal = _terminal_binding(summary)
    terminal["result_summary_hash"] = "sha256:" + "0" * 64
    with pytest.raises(NSLResultIntegrationError, match="does not match"):
        build_step_execution_outcome(summary=summary, binding=terminal)

    not_started = _binding(state="REQUEST_BOUND")
    not_started["invocation_started_at"] = None
    with pytest.raises(NSLResultIntegrationError, match="invocation start"):
        build_step_execution_outcome(summary=summary, binding=not_started)


@pytest.mark.parametrize("error", [{}, {"code": 1}, {"code": " "}])
def test_failed_runtime_without_bounded_code_uses_stable_fallback(error) -> None:
    run = _backend_run("FAILED")
    run["runtime_result_envelope"]["runtime_result"]["error"] = error
    run["record_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in run.items() if key != "record_hash"}
    )

    summary = build_nsl_result_summary(
        binding=_binding(),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        backend_run=run,
    )

    assert summary["error_code"] == "NSL_FAILED"


def test_result_mapping_rejects_noncanonical_json_value() -> None:
    with pytest.raises(NSLResultIntegrationError, match="canonical JSON"):
        result_module._mapping("value", {"not_a_number": float("nan")})
