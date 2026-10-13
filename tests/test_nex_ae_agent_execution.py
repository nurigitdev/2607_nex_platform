from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import nex_ae_api.agent_execution as execution_module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_execution import (
    AGENT_EXECUTION_PHASES,
    AGENT_EXECUTION_STATES,
    AgentExecutionAdmissionService,
    AgentExecutionError,
    ExecutionTriggerV21,
    SqlAlchemyAgentExecutionRepository,
    agent_runtime_mode,
)
from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2003_ae_agent_execution.sql"
TRIGGER_SCHEMA = ROOT / (
    "docs/transition/P4/P4_CA01_Candidate/execution-trigger-v2.1.schema.json"
)
TENANT = "tenant-a"
PRINCIPAL = "user-a"
AGENT_ID = "11111111-1111-4111-8111-111111111111"
ASSIGNMENT_ID = "22222222-2222-4222-8222-222222222222"
WORKSPACE_ID = "33333333-3333-4333-8333-333333333333"
CONVERSATION_ID = "44444444-4444-4444-8444-444444444444"
TRIGGER_ID = "55555555-5555-4555-8555-555555555555"
INTERACTION_ID = "66666666-6666-4666-8666-666666666666"
EXECUTION_ID = "77777777-7777-4777-8777-777777777777"
NOW_DT = datetime(2026, 10, 13, 3, 0, 0, tzinfo=UTC)
NOW = "2026-10-13T03:00:00Z"


def _session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys = ON"))
            connection.execute(text("""
                CREATE TABLE ae_agent_identity (
                    tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL, agent_type TEXT NOT NULL,
                    profile_ref TEXT NOT NULL, status TEXT NOT NULL,
                    project_id TEXT, created_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, agent_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_ia_principal_assignment (
                    assignment_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, version INTEGER NOT NULL,
                    UNIQUE (tenant_id, principal_id), UNIQUE (tenant_id, agent_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_workspaces (
                    workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_conversations (
                    conversation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    trigger_schema_version TEXT NOT NULL,
                    trigger_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    project_id TEXT,
                    workspace_id TEXT,
                    conversation_id TEXT,
                    legacy_interaction_id TEXT,
                    state TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    result_id TEXT,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    received_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_execution_id),
                    UNIQUE (tenant_id, trigger_id)
                )
            """))
            connection.execute(
                text("INSERT INTO ae_workspaces VALUES (:id, :tenant, :owner)"),
                {"id": WORKSPACE_ID, "tenant": TENANT, "owner": PRINCIPAL},
            )
            connection.execute(
                text("INSERT INTO ae_conversations VALUES (:id, :tenant, :workspace, :owner)"),
                {
                    "id": CONVERSATION_ID,
                    "tenant": TENANT,
                    "workspace": WORKSPACE_ID,
                    "owner": PRINCIPAL,
                },
            )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ids(*values: str):
    items = iter(values)
    return lambda: next(items)


def _components(*, mode: str = "required", sessions=None):
    sessions = sessions or _session_factory()
    identities = SqlAlchemyAgentIdentityRegistry(
        sessions,
        id_factory=_ids(AGENT_ID, ASSIGNMENT_ID),
        clock=lambda: NOW_DT,
    )
    repository = SqlAlchemyAgentExecutionRepository(sessions)
    service = AgentExecutionAdmissionService(
        identities=identities,
        executions=repository,
        mode=mode,
        id_factory=_ids(EXECUTION_ID, "88888888-8888-4888-8888-888888888888"),
        clock=lambda: NOW_DT,
    )
    return sessions, identities, repository, service


def _admit(service, **overrides):
    values = {
        "tenant_id": TENANT,
        "principal_id": PRINCIPAL,
        "profile_ref": "urn:nex:agent-profile:ia:default:v1",
        "trigger_id": TRIGGER_ID,
        "interaction_id": INTERACTION_ID,
        "workspace_id": WORKSPACE_ID,
        "conversation_id": CONVERSATION_ID,
        "correlation_id": "correlation-a",
    }
    return service.admit_prompt(**{**values, **overrides})


def _trigger(**overrides):
    values = {
        "trigger_id": TRIGGER_ID,
        "source_type": "PROMPT",
        "source_ref": INTERACTION_ID,
        "tenant_id": TENANT,
        "agent_type": "IA",
        "agent_id": AGENT_ID,
        "project_id": None,
        "correlation_id": "correlation-a",
        "received_at": NOW,
        "requester_ref": PRINCIPAL,
    }
    return ExecutionTriggerV21(**{**values, **overrides})


def test_required_admission_is_canonical_project_neutral_and_idempotent() -> None:
    sessions, _, repository, service = _components()

    first = _admit(service)
    repeated = _admit(service)

    assert first == repeated
    assert first.mode == "required"
    assert first.execution == {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": "IA",
        "principal_id": PRINCIPAL,
        "trigger_schema_version": "2.1",
        "trigger_id": TRIGGER_ID,
        "source_type": "PROMPT",
        "source_ref": INTERACTION_ID,
        "project_id": None,
        "workspace_id": WORKSPACE_ID,
        "conversation_id": CONVERSATION_ID,
        "legacy_interaction_id": INTERACTION_ID,
        "state": "QUEUED",
        "phase": "INTAKE",
        "version": 1,
        "result_id": None,
        "correlation_id": "correlation-a",
        "causation_id": None,
        "received_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert repository.get(TENANT, EXECUTION_ID) == first.execution
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_execution")).scalar() == 1


def test_prompt_with_resolved_project_and_nullable_scope_are_supported() -> None:
    _, _, _, service = _components()
    admitted = _admit(
        service,
        project_id="project-known",
        workspace_id=None,
        conversation_id=None,
        causation_id="cause-a",
    )

    assert admitted.execution["project_id"] == "project-known"
    assert admitted.execution["workspace_id"] is None
    assert admitted.execution["conversation_id"] is None
    assert admitted.execution["causation_id"] == "cause-a"


def test_trigger_matches_amended_schema_and_rejects_forbidden_shapes() -> None:
    validator = Draft202012Validator(
        json.loads(TRIGGER_SCHEMA.read_text()),
        format_checker=FormatChecker(),
    )
    validator.validate(_trigger().to_dict())
    validator.validate(_trigger(project_id="project-a").to_dict())

    valid_claim = _trigger(
        source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        project_id="project-a",
        work_item_ref="work-a",
        claim_ref="claim-a",
        assignment_ref="assignment-a",
        claim_generation=1,
    )
    validator.validate(valid_claim.to_dict())
    for overrides in (
        {"source_type": "PROMPT", "agent_type": "PA"},
        {"source_type": "CLAIMED_WORKITEM", "agent_type": "IA"},
        {"source_type": "CLAIMED_WORKITEM", "agent_type": "PA"},
        {"source_type": "UNKNOWN"},
        {"project_id": ""},
        {"claim_generation": 0},
        {"claim_generation": True},
        {"schema_version": "1.0"},
        {"tenant_id": ""},
    ):
        with pytest.raises(AgentExecutionError):
            _trigger(**overrides)


def test_repository_rejects_claimed_workitem_in_p4() -> None:
    _, identities, repository, _ = _components()
    identities.resolve_or_provision_ia(
        tenant_id=TENANT, principal_id=PRINCIPAL, profile_ref="profile-a"
    )
    claimed = _trigger(
        source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        project_id="project-a",
        work_item_ref="work-a",
        claim_ref="claim-a",
        assignment_ref="assignment-a",
    )
    with pytest.raises(AgentExecutionError) as exc_info:
        repository.admit_prompt(
            trigger=claimed,
            principal_id=PRINCIPAL,
            agent_execution_id=EXECUTION_ID,
            workspace_id=None,
            conversation_id=None,
            legacy_interaction_id=None,
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.agent_execution_invalid"


def test_admission_rejects_identity_and_conversation_scope() -> None:
    sessions, identities, repository, _ = _components()
    identities.resolve_or_provision_ia(
        tenant_id=TENANT, principal_id=PRINCIPAL, profile_ref="profile-a"
    )

    with sessions.begin() as session:
        session.execute(text("UPDATE ae_agent_identity SET status = 'SUSPENDED'"))
    with pytest.raises(AgentExecutionError) as identity_failure:
        repository.admit_prompt(
            trigger=_trigger(),
            principal_id=PRINCIPAL,
            agent_execution_id=EXECUTION_ID,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            legacy_interaction_id=INTERACTION_ID,
            now=NOW,
        )
    assert identity_failure.value.error_code == "ae.agent_execution_identity_forbidden"

    with sessions.begin() as session:
        session.execute(text("UPDATE ae_agent_identity SET status = 'ACTIVE'"))
        session.execute(text("UPDATE ae_conversations SET owner_user_id = 'user-b'"))
    with pytest.raises(AgentExecutionError) as conversation_failure:
        repository.admit_prompt(
            trigger=_trigger(),
            principal_id=PRINCIPAL,
            agent_execution_id=EXECUTION_ID,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            legacy_interaction_id=INTERACTION_ID,
            now=NOW,
        )
    assert conversation_failure.value.error_code == (
        "ae.agent_execution_conversation_forbidden"
    )


def test_duplicate_trigger_with_different_semantics_fails() -> None:
    _, identities, repository, _ = _components()
    identities.resolve_or_provision_ia(
        tenant_id=TENANT, principal_id=PRINCIPAL, profile_ref="profile-a"
    )
    repository.admit_prompt(
        trigger=_trigger(),
        principal_id=PRINCIPAL,
        agent_execution_id=EXECUTION_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        legacy_interaction_id=INTERACTION_ID,
        now=NOW,
    )

    with pytest.raises(AgentExecutionError) as exc_info:
        repository.admit_prompt(
            trigger=_trigger(correlation_id="different"),
            principal_id=PRINCIPAL,
            agent_execution_id="88888888-8888-4888-8888-888888888888",
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            legacy_interaction_id=INTERACTION_ID,
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.agent_execution_trigger_conflict"


def test_frozen_state_phase_transitions_use_cas_and_fail_closed_ack_guard() -> None:
    _, _, repository, service = _components()
    execution = _admit(service).execution
    assert execution is not None

    version = 1
    for state, phase in zip(
        sorted(AGENT_EXECUTION_STATES - {"SUCCEEDED"}),
        sorted(AGENT_EXECUTION_PHASES),
        strict=False,
    ):
        transitioned = repository.transition(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            expected_version=version,
            state=state,
            phase=phase,
            updated_at=NOW,
        )
        version += 1
        assert transitioned["version"] == version
        assert (transitioned["state"], transitioned["phase"]) == (state, phase)

    with pytest.raises(AgentExecutionError) as no_ack:
        repository.transition(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            expected_version=version,
            state="SUCCEEDED",
            phase="FINALIZE",
            updated_at=NOW,
        )
    assert no_ack.value.error_code == "ae.agent_execution_delivery_ack_required"
    unchanged = repository.get(TENANT, EXECUTION_ID)
    assert unchanged["state"] != "SUCCEEDED"
    assert unchanged["version"] == version


def test_transition_rejects_unknown_vocab_stale_version_and_missing_execution() -> None:
    _, _, repository, service = _components()
    _admit(service)

    for values in (
        {"state": "UNKNOWN", "phase": "INTAKE", "expected_version": 1},
        {"state": "RUNNING", "phase": "UNKNOWN", "expected_version": 1},
        {"state": "RUNNING", "phase": "INTAKE", "expected_version": 0},
        {"state": "RUNNING", "phase": "INTAKE", "expected_version": True},
    ):
        with pytest.raises(AgentExecutionError) as invalid:
            repository.transition(
                tenant_id=TENANT,
                agent_execution_id=EXECUTION_ID,
                updated_at=NOW,
                **values,
            )
        assert invalid.value.error_code == "ae.agent_execution_invalid"

    with pytest.raises(AgentExecutionError) as stale:
        repository.transition(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            expected_version=2,
            state="RUNNING",
            phase="STEP_EXECUTION",
            updated_at=NOW,
        )
    assert stale.value.error_code == "ae.agent_execution_version_conflict"
    assert stale.value.retryable is True
    with pytest.raises(AgentExecutionError) as missing:
        repository.transition(
            tenant_id=TENANT,
            agent_execution_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            expected_version=1,
            state="RUNNING",
            phase="STEP_EXECUTION",
            updated_at=NOW,
        )
    assert missing.value.error_code == "ae.agent_execution_not_found"


class _FailingIdentities:
    def resolve_or_provision_ia(self, **kwargs):
        raise AgentIdentityRepositoryError("ae.identity.down", "down", True)


class _RecordingExecutions:
    def __init__(self):
        self.calls = 0

    def admit_prompt(self, **kwargs):
        self.calls += 1
        return {"agent_execution_id": EXECUTION_ID}


def test_rollout_modes_are_disabled_by_default_shadow_safe_and_required_closed() -> None:
    executions = _RecordingExecutions()
    disabled = AgentExecutionAdmissionService(
        identities=_FailingIdentities(),  # type: ignore[arg-type]
        executions=executions,  # type: ignore[arg-type]
    )
    assert _admit(disabled).execution is None
    assert executions.calls == 0

    shadow = AgentExecutionAdmissionService(
        identities=_FailingIdentities(),  # type: ignore[arg-type]
        executions=executions,  # type: ignore[arg-type]
        mode="shadow",
    )
    shadow_result = _admit(shadow)
    assert shadow_result.execution is None
    assert shadow_result.shadow_error_code == "ae.identity.down"

    required = AgentExecutionAdmissionService(
        identities=_FailingIdentities(),  # type: ignore[arg-type]
        executions=executions,  # type: ignore[arg-type]
        mode="required",
    )
    with pytest.raises(AgentIdentityRepositoryError):
        _admit(required)
    with pytest.raises(AgentExecutionError):
        AgentExecutionAdmissionService(
            identities=_FailingIdentities(),  # type: ignore[arg-type]
            executions=executions,  # type: ignore[arg-type]
            mode="bad",
        )

    assert agent_runtime_mode({}) == "disabled"
    assert agent_runtime_mode({"NEX_AE_AGENT_RUNTIME_MODE": " SHADOW "}) == "shadow"
    with pytest.raises(AgentExecutionError):
        agent_runtime_mode({"NEX_AE_AGENT_RUNTIME_MODE": "bad"})


def test_browser_agent_id_is_not_an_admission_parameter() -> None:
    signature = inspect.signature(AgentExecutionAdmissionService.admit_prompt)
    assert "agent_id" not in signature.parameters


def test_repository_wraps_database_failures_and_missing_reads() -> None:
    unavailable = SqlAlchemyAgentExecutionRepository(
        _session_factory(with_schema=False)
    )
    assert SqlAlchemyAgentExecutionRepository(_session_factory()).get(TENANT, EXECUTION_ID) is None
    with pytest.raises(AgentExecutionError) as read_failure:
        unavailable.get(TENANT, EXECUTION_ID)
    assert read_failure.value.error_code == "ae.agent_execution_store_unavailable"
    assert read_failure.value.retryable is True
    assert str(read_failure.value) == "AE AgentExecution store is unavailable."
    with pytest.raises(AgentExecutionError):
        unavailable.admit_prompt(
            trigger=_trigger(),
            principal_id=PRINCIPAL,
            agent_execution_id=EXECUTION_ID,
            workspace_id=None,
            conversation_id=None,
            legacy_interaction_id=INTERACTION_ID,
            now=NOW,
        )
    with pytest.raises(AgentExecutionError):
        unavailable.transition(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            expected_version=1,
            state="RUNNING",
            phase="INTAKE",
            updated_at=NOW,
        )


def test_post_write_reload_failures_are_typed(monkeypatch) -> None:
    _, identities, repository, _ = _components()
    identities.resolve_or_provision_ia(
        tenant_id=TENANT, principal_id=PRINCIPAL, profile_ref="profile-a"
    )
    monkeypatch.setattr(execution_module, "_load_by_trigger", lambda *args: None)
    with pytest.raises(AgentExecutionError) as admission_failure:
        repository.admit_prompt(
            trigger=_trigger(),
            principal_id=PRINCIPAL,
            agent_execution_id=EXECUTION_ID,
            workspace_id=None,
            conversation_id=None,
            legacy_interaction_id=INTERACTION_ID,
            now=NOW,
        )
    assert admission_failure.value.error_code == "ae.agent_execution_write_conflict"

    monkeypatch.undo()
    _, _, repository, service = _components()
    _admit(service)
    real_load = execution_module._load_execution
    calls = 0

    def disappear_after_update(*args):
        nonlocal calls
        calls += 1
        return None if calls == 1 else real_load(*args)

    monkeypatch.setattr(execution_module, "_load_execution", disappear_after_update)
    with pytest.raises(AgentExecutionError) as transition_failure:
        repository.transition(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            expected_version=1,
            state="RUNNING",
            phase="INTAKE",
            updated_at=NOW,
        )
    assert transition_failure.value.error_code == "ae.agent_execution_write_conflict"


def test_migration_uses_canonical_identity_vocabulary_and_no_parallel_run() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_agent_execution" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_execution_trigger" not in sql
    assert "ae_ia_chat_run" not in sql
    assert "UNIQUE (tenant_id, trigger_id)" in sql
    assert "CHECK (source_type = 'PROMPT')" in sql
    assert "CHECK (agent_type = 'IA')" in sql
    assert "project_id TEXT NULL" in sql
    for value in AGENT_EXECUTION_STATES | AGENT_EXECUTION_PHASES:
        assert f"'{value}'" in sql
    assert "2003_ae_agent_execution" in sql
    assert len("ae_agent_execution") <= 30
