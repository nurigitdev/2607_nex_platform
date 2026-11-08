from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.p8_demo_runtime_composition as composition
import pytest
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.p8_demo_controlled_skill import (
    P8DemoControlledSkillError,
    P8DemoControlledSkillRuntime,
    _context_projection,
    _controlled_write_outcome,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim
from nex_ae_api.step_executors import LocalSkillExecutorDependencies, P5WorkerExecution
from nex_runtime.demo_fixture import load_demo_business_fixture
from nex_runtime.demo_nsl_runtime_adapter import write_stable_json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def test_installed_runtime_cycle_projects_canonical_worker_counters() -> None:
    installed = SimpleNamespace(
        run_cycle=lambda: {
            "status": "WORK",
            "domain_claiming_enabled": True,
            "composition_mode": "GENERIC_INSTALLED_RUNTIME",
            "execution_count": 1,
            "succeeded_count": 1,
            "failed_count": 0,
            "stop_reason": "MAX_CYCLES",
            "result_closure": {
                "candidate_count": 1,
                "finalized_count": 1,
                "published_count": 1,
                "replayed_count": 0,
                "failed_count": 0,
                "failures": [],
            },
        },
    )
    runtime = composition.InstalledP8RuntimeComposition(
        controlled_skill=SimpleNamespace(package_readiness={"status": "PASS"}),
        installed_runtime=installed,
    )

    result = runtime.run_cycle()

    assert result == {
        "status": "WORK",
        "domain_claiming_enabled": True,
        "composition_mode": "EXISTING_COMPONENT_COMPOSITION",
        "execution_count": 1,
        "succeeded_count": 1,
        "failed_count": 0,
        "stop_reason": "MAX_CYCLES",
        "result_closure": {
            "candidate_count": 1,
            "finalized_count": 1,
            "published_count": 1,
            "replayed_count": 0,
            "failed_count": 0,
            "failures": [],
        },
    }


def test_installed_runtime_cycle_reports_idle() -> None:
    installed = SimpleNamespace(
        run_cycle=lambda: {
            "status": "IDLE",
            "domain_claiming_enabled": True,
            "composition_mode": "GENERIC_INSTALLED_RUNTIME",
            "execution_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "stop_reason": "MAX_CYCLES",
            "result_closure": {
                "candidate_count": 0,
                "finalized_count": 0,
                "published_count": 0,
                "replayed_count": 0,
                "failed_count": 0,
                "failures": [],
            },
        }
    )
    runtime = composition.InstalledP8RuntimeComposition(
        controlled_skill=SimpleNamespace(package_readiness={"status": "PASS"}),
        installed_runtime=installed,
    )

    assert runtime.run_cycle()["status"] == "IDLE"


def test_composition_reuses_existing_dispatcher_worker_and_executor_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    dependencies = LocalSkillExecutorDependencies(
        artifact_gateway=SimpleNamespace(resolve_verified=lambda **_values: {}),
        binding_repository=SimpleNamespace(bind_request=lambda **_values: {}),
        request_builder=lambda **_values: {},
        backend=SimpleNamespace(
            backend_profile="NSL_V02_IN_PROCESS",
            execute=lambda **_values: {},
        ),
        result_mapper=lambda value: value,
    )
    controlled = SimpleNamespace(
        backend_profile="NSL_V02_IN_PROCESS",
        dependencies=dependencies,
        initial=lambda *_values: None,
        resume=lambda *_values: None,
        package_readiness={"status": "PASS"},
    )
    monkeypatch.setattr(
        composition,
        "P8DemoControlledSkillRuntime",
        lambda _sessions, _config: controlled,
    )
    monkeypatch.setattr(
        composition,
        "_controlled_skill_config",
        lambda _environ: object(),
    )
    resource = SimpleNamespace(
        sessions=sessions,
        config=SimpleNamespace(worker_id="ae-demo-agent-runtime-1"),
        heartbeat=SimpleNamespace(store=object()),
    )

    runtime = composition.build_installed_p8_runtime_composition(resource, {})

    assert isinstance(runtime.handler, composition.InstalledP8StepAssignmentHandler)
    assert isinstance(
        runtime.installed_runtime, composition.InstalledRuntimeComposition
    )
    assert runtime.assignment_source is runtime.installed_runtime.assignment_source
    assert runtime.heartbeat_emitter is resource.heartbeat
    assert runtime.result_closer is runtime.installed_runtime.result_closer
    assert runtime.worker_config.mode == "enabled"
    assert runtime.worker_config.profile.worker_id == "ae-demo-agent-runtime-1"
    assert runtime.worker_config.profile.supported_executor_kinds == (
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
        "P4_CHAT_RAG_COMPATIBILITY",
    )
    assert runtime.executor_kinds == (
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
        "P4_CHAT_RAG_COMPATIBILITY",
    )
    assert runtime.backend_profiles == ("NSL_V02_IN_PROCESS",)


def test_demo_composition_is_a_thin_generic_factory_adapter() -> None:
    source = inspect.getsource(composition)

    assert "build_installed_runtime_composition(" in source
    for orchestration_owner in (
        "SqlAlchemyRuntimeJobQueue",
        "SqlAlchemyMultiStepEngine",
        "SqlAlchemyAgentRuntimeDispatcher",
        "SqlAlchemyAgentRuntimeAssignmentSource",
        "P5StepExecutionWorker",
        "AgentRuntimeWorkerLifecycle",
        "run_bounded_agent_runtime_worker",
        "SqlAlchemyInstalledIaResultCloser",
        "SqlAlchemyWorkspaceResultPublisher",
    ):
        assert orchestration_owner not in source


def test_demo_controlled_skill_config_resolves_adapter_owned_paths(
    tmp_path: Path,
) -> None:
    paths = {
        "NEX_AE_DEMO_NSL_BUNDLE_MANIFEST": tmp_path / "manifest.json",
        "NEX_AE_DEMO_NSL_WHEEL": tmp_path / "runtime.whl",
        "NEX_AE_DEMO_PLATFORM_LOCK": tmp_path / "platform.lock",
        "NEX_AE_DEMO_NSL_SKILL_ROOT": tmp_path / "skill",
        "NEX_AE_DEMO_FIXTURE": tmp_path / "demo.json",
        "NEX_AE_DEMO_BASE_FIXTURE": tmp_path / "base.json",
    }
    for path in paths.values():
        path.mkdir() if path.name == "skill" else path.write_text("{}")
    state_root = tmp_path / "state-not-created"
    environ = {
        **{name: str(path) for name, path in paths.items()},
        "NEX_AE_DEMO_NSL_STATE_ROOT": str(state_root),
        "NEX_OA_BASE_URL": "http://oa.example",
        "NEX_EOS_BASE_URL": "http://eos.example",
        "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-token",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-token",
    }

    config = composition._controlled_skill_config(environ)

    assert config.manifest_path == paths["NEX_AE_DEMO_NSL_BUNDLE_MANIFEST"]
    assert config.wheel_path == paths["NEX_AE_DEMO_NSL_WHEEL"]
    assert config.platform_lock_path == paths["NEX_AE_DEMO_PLATFORM_LOCK"]
    assert config.skill_root == paths["NEX_AE_DEMO_NSL_SKILL_ROOT"]
    assert config.demo_fixture_path == paths["NEX_AE_DEMO_FIXTURE"]
    assert config.base_fixture_path == paths["NEX_AE_DEMO_BASE_FIXTURE"]
    assert config.state_root == state_root
    assert config.oa_base_url == "http://oa.example"
    assert config.eos_base_url == "http://eos.example"


def test_demo_adapter_helpers_fail_closed_and_preserve_optional_wa_boundary(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}")
    missing = tmp_path / "missing.json"

    assert composition._path({}, "PATH", existing) == existing
    assert composition._path({}, "PATH", missing, require_existing=False) == missing
    with pytest.raises(ValueError, match="PATH is unavailable"):
        composition._path({}, "PATH", missing)
    with pytest.raises(ValueError, match="TOKEN is required"):
        composition._text({}, "TOKEN")
    assert (
        composition._optional_wa_notifier(
            SimpleNamespace(sessions=object()),
            {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "STAGING"},
        )
        is None
    )


def test_installed_handler_schedules_successor_after_terminal_outcome() -> None:
    scheduled: list[dict[str, str]] = []
    claim = RuntimeJobClaim(
        job={
            "tenant_id": "VO00",
            "runtime_job_id": "job-1",
            "execution_id": "execution-1",
            "state": "RUNNING",
            "lease_owner": "worker-1",
            "lease_token": "lease-1",
        },
        attempt={"attempt_no": 1},
        executor_kind="DETERMINISTIC_REPORT",
        backend_profile=None,
    )
    worker = SimpleNamespace(
        run_claim=lambda **_values: P5WorkerExecution(
            disposition="TERMINAL",
            step={"executable_step_id": "step-1"},
            step_result={"step_result_id": "result-1", "status": "SUCCEEDED"},
            runtime_job={"state": "DONE"},
        )
    )
    engine = SimpleNamespace(
        schedule_next=lambda **values: (
            scheduled.append(values) or {"runtime_job_id": "job-2"}
        )
    )
    handler = composition.InstalledP8StepAssignmentHandler(worker, engine)

    result = handler(
        AgentRuntimeAssignment(
            tenant_id="VO00",
            executor_kind="DETERMINISTIC_REPORT",
            backend_profile="NSL_V02_IN_PROCESS",
            claim=claim,
        )
    )

    assert result["successor_scheduled"] is True
    assert scheduled[0]["tenant_id"] == "VO00"
    assert scheduled[0]["execution_id"] == "execution-1"


def test_installed_handler_does_not_schedule_while_step_is_waiting() -> None:
    claim = RuntimeJobClaim(
        job={
            "tenant_id": "VO00",
            "runtime_job_id": "job-1",
            "execution_id": "execution-1",
            "state": "RUNNING",
            "lease_owner": "worker-1",
            "lease_token": "lease-1",
        },
        attempt={"attempt_no": 1},
        executor_kind="LOCAL_SKILL",
        backend_profile="NSL_V02_IN_PROCESS",
    )
    worker = SimpleNamespace(
        run_claim=lambda **_values: P5WorkerExecution(
            disposition="WAITING",
            step={"executable_step_id": "step-1"},
            step_result=None,
            runtime_job={"state": "DONE"},
        )
    )
    engine = SimpleNamespace(
        schedule_next=lambda **_values: pytest.fail(
            "WAITING step must not schedule its successor"
        )
    )

    result = composition.InstalledP8StepAssignmentHandler(worker, engine)(
        AgentRuntimeAssignment(
            tenant_id="VO00",
            executor_kind="LOCAL_SKILL",
            backend_profile="NSL_V02_IN_PROCESS",
            claim=claim,
        )
    )

    assert result["successor_scheduled"] is False
    assert result["step_result_id"] is None


def test_controlled_skill_rejects_direct_backend_invocation() -> None:
    runtime = object.__new__(P8DemoControlledSkillRuntime)

    with pytest.raises(P8DemoControlledSkillError, match="initial/resume handlers"):
        runtime.execute(request={})


def test_stable_runtime_document_is_idempotent_and_collision_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.json"

    write_stable_json(path, {"tenant_id": "VO00", "amount": 62000})
    write_stable_json(path, {"amount": 62000, "tenant_id": "VO00"})

    assert path.read_text(encoding="utf-8") == ('{"amount":62000,"tenant_id":"VO00"}')
    with pytest.raises(P8DemoControlledSkillError, match="collision"):
        write_stable_json(path, {"tenant_id": "OTHER"})


def test_context_projection_accepts_postgres_mapping_and_sqlite_json_text() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(engine, expire_on_commit=False)
    _, fixture = load_demo_business_fixture(
        ROOT / "scripts/deployment/data/p8_demo_vo00_fixture.v1.json",
        base_fixture_path=ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json",
    )
    principal_id = fixture["scenario"]["requester_subject_id"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_agent_context (tenant_id TEXT, context_id TEXT, "
                "context_generation INTEGER, context_hash TEXT, context_json TEXT, "
                "agent_execution_id TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_context VALUES "
                "('VO00', 'context-1', 1, :hash, :document, 'execution-1')"
            ),
            {
                "hash": "sha256:" + "a" * 64,
                "document": '{"identity":{"principal_id":"' + principal_id + '"}}',
            },
        )

    result = _context_projection(
        sessions,
        tenant_id="VO00",
        execution_id="execution-1",
        fixture=fixture,
    )

    assert result["agent_context_ref"] == "AE:AGENT_CONTEXT:context-1:1"
    assert result["verified_principal"]["subject_id"] == principal_id

    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_agent_context SET context_json = '[]'"))
    with pytest.raises(P8DemoControlledSkillError, match="must be an object"):
        _context_projection(
            sessions,
            tenant_id="VO00",
            execution_id="execution-1",
            fixture=fixture,
        )


@pytest.mark.parametrize(
    ("commit_state", "verification", "expected_state"),
    (
        ("COMMITTED", "VERIFIED", "SUCCEEDED"),
        ("NOT_COMMITTED", None, "FAILED"),
        ("UNKNOWN_COMMIT_STATE", None, "BLOCKED"),
        ("COMMITTED", "FAILED", "BLOCKED"),
    ),
)
def test_controlled_write_outcome_preserves_reconciliation_boundary(
    commit_state: str,
    verification: str | None,
    expected_state: str,
) -> None:
    result = SimpleNamespace(
        outcome=SimpleNamespace(commit_state=SimpleNamespace(value=commit_state)),
        verification=(
            None
            if verification is None
            else SimpleNamespace(status=SimpleNamespace(value=verification))
        ),
        write_request=SimpleNamespace(idempotency_key="idempotency-1"),
    )

    outcome = _controlled_write_outcome(
        result,
        business_operation_id="business-operation-1",
    )

    assert outcome.state == expected_state
    assert outcome.result_payload["commit_state"] == commit_state
    assert outcome.business_operation_id == "business-operation-1"
