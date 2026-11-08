from __future__ import annotations

import copy
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import nex_ae_api.agent_results as result_module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_results import (
    AGENT_RESULT_STATUSES,
    AgentResultError,
    SqlAlchemyAgentResultRepository,
    build_agent_result,
    derive_publication_identity,
    execution_destination,
    result_hash,
    validate_agent_result,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2006_ae_agent_result.sql"
FROZEN_ROOT = ROOT / (
    "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/"
    "NeX_Platform_v2.1_Controlled_Amendment_Batch08_E2E11_RESULT_PUBLICATION/"
    "AE_PUBLICATION"
)
RESULT_SCHEMA = FROZEN_ROOT / "agent-result-v2.1.schema.json"
DELIVERY_SCHEMA = FROZEN_ROOT / "result-delivery-v2.1.schema.json"
TENANT = "tenant-a"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
AGENT_ID = "22222222-2222-4222-8222-222222222222"
WORKSPACE_ID = "33333333-3333-4333-8333-333333333333"
STEP_ID = "44444444-4444-4444-8444-444444444444"
INTERACTION_ID = "55555555-5555-4555-8555-555555555555"
RESULT_ID = "66666666-6666-4666-8666-666666666666"
DELIVERY_ID = "77777777-7777-4777-8777-777777777777"
NOW = "2026-10-13T04:00:00Z"


def _session_factory(
    *,
    with_schema: bool = True,
    with_execution: bool = True,
    with_step: bool = True,
    workspace_id: str | None = WORKSPACE_ID,
    execution_state: str = "QUEUED",
    execution_project_id: str | None = None,
    step_state: str = "SUCCEEDED",
):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if not with_schema:
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                project_id TEXT, workspace_id TEXT, state TEXT NOT NULL,
                phase TEXT NOT NULL, version INTEGER NOT NULL, result_id TEXT,
                correlation_id TEXT NOT NULL, causation_id TEXT,
                completed_at TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, agent_execution_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_executable_step (
                tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, step_kind TEXT NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY (tenant_id, executable_step_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_agent_result (
                tenant_id TEXT NOT NULL, result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                agent_id TEXT, project_id TEXT, status TEXT NOT NULL,
                quality TEXT, structured_result_json TEXT NOT NULL,
                result_envelope_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                source_work_item_ref TEXT, source_claim_ref TEXT,
                source_claim_generation INTEGER,
                source_claimant_agent_id TEXT, source_assignment_ref TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, result_id),
                UNIQUE (tenant_id, agent_execution_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_result_delivery (
                tenant_id TEXT NOT NULL, delivery_id TEXT NOT NULL,
                result_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                target_type TEXT NOT NULL, target_ref TEXT NOT NULL,
                required BOOLEAN NOT NULL, state TEXT NOT NULL,
                publication_operation_id TEXT NOT NULL,
                idempotency_key_ref TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                external_delivery_ref TEXT, latest_preflight_ref TEXT,
                publication_reconciliation_ref TEXT,
                correlation_id TEXT NOT NULL, causation_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                acknowledged_at TEXT,
                PRIMARY KEY (tenant_id, delivery_id),
                UNIQUE (tenant_id, result_id, target_type, target_ref)
            )
        """))
        if with_execution:
            connection.execute(
                text("""
                    INSERT INTO ae_agent_execution VALUES (
                        :tenant, :execution, :agent, 'IA', :project,
                        :workspace, :state, 'INTAKE', 1, NULL,
                        'correlation-a', NULL, NULL, :now
                    )
                """),
                {
                    "tenant": TENANT,
                    "execution": EXECUTION_ID,
                    "agent": AGENT_ID,
                    "project": execution_project_id,
                    "workspace": workspace_id,
                    "state": execution_state,
                    "now": NOW,
                },
            )
        if with_step:
            connection.execute(
                text("""
                    INSERT INTO ae_executable_step VALUES (
                        :tenant, :step, :execution,
                        'P4_CHAT_RAG_COMPATIBILITY', :state
                    )
                """),
                {
                    "tenant": TENANT,
                    "step": STEP_ID,
                    "execution": EXECUTION_ID,
                    "state": step_state,
                },
            )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _execution(**overrides):
    values = {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": "IA",
        "project_id": None,
    }
    return {**values, **overrides}


def _step(*, state: str = "SUCCEEDED", **overrides):
    values = {
        "tenant_id": TENANT,
        "executable_step_id": STEP_ID,
        "agent_execution_id": EXECUTION_ID,
        "legacy_interaction_id": INTERACTION_ID,
        "state": state,
        "retrieval_package_ref": "retrieval-a",
        "retrieval_package_hash": "sha256:retrieval",
        "cx_generation_id": "generation-a",
        "cx_job_id": "job-a",
        "generated_response_id": "response-a",
        "result_ref": f"ae-chat://interaction/{INTERACTION_ID}",
        "error_ref": None,
    }
    return {**values, **overrides}


def _legacy(*, status: str = "COMPLETED", boundary: str = "PASS", **overrides):
    values = {
        "interaction_id": INTERACTION_ID,
        "status": status,
        "generation": {
            "grounded_response_quality": {
                "boundary_status": boundary,
                "issue_count": 0,
            }
        },
        "retrieval": {"quality_warnings": {"recommended_action": "proceed"}},
        "artifact_refs": [
            {"artifact_id": "artifact-a", "artifact_version_id": "version-a"},
            "artifact-b",
        ],
    }
    return {**values, **overrides}


def _result(**overrides):
    status = overrides.pop("legacy_status", "COMPLETED")
    step_state = {
        "COMPLETED": "SUCCEEDED",
        "NO_ANSWER": "BLOCKED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }[status]
    return build_agent_result(
        execution=_execution(),
        step=_step(state=step_state),
        legacy_result=_legacy(status=status),
        result_id=RESULT_ID,
        created_at=NOW,
        structured_result_contract_ref="contract://p4/chat-result/v1",
        completion_verification_refs=("verify-b", "verify-a", "verify-a"),
        business_refs=("business-b", "business-a"),
        evidence_refs=("evidence-b", "evidence-a"),
        citation_refs=("citation-b", "citation-a"),
        **overrides,
    )


def _validate(schema_path: Path, payload: dict) -> None:
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    validator.validate(payload)


def test_database_timestamps_are_canonicalized_to_utc() -> None:
    database_value = datetime.fromisoformat("2026-10-13T13:00:00+09:00")
    sqlite_value = datetime.fromisoformat("2026-10-13T04:00:00")

    assert result_module._datetime_value(database_value) == NOW
    assert result_module._datetime_value(sqlite_value) == "2026-10-13T04:00:00"


def test_builds_complete_schema_valid_reference_only_result_and_fixed_hash() -> None:
    result = _result()

    _validate(RESULT_SCHEMA, result)
    assert result["status"] == "SUCCEEDED"
    assert result["quality"] == "COMPLETE"
    assert result["project_id"] is None
    assert result["source_claim_ref"] is None
    assert result["artifact_refs"] == ["artifact-b", "version-a"]
    assert result["business_refs"] == ["business-a", "business-b"]
    assert result["structured_result"]["generated_response_ref"] == "response-a"
    assert result["result_hash"] == (
        "sha256:3fdb7b3b4588638591da4057073aac6eb9a6cf0b668d3ef7e1e345f5d167334c"
    )
    serialized = json.dumps(result, sort_keys=True)
    for private_value in ("prompt body", "generated body", "evidence body"):
        assert private_value not in serialized


def _background_result(**overrides):
    value = {
        **_result(),
        "agent_type": "PA",
        "project_id": "project-p7",
        "source_work_item_ref": "work-item-p7",
        "source_claim_ref": "claim-p7",
        "source_claim_generation": 1,
        "source_claimant_agent_id": AGENT_ID,
        "source_assignment_ref": "assignment-p7",
        **overrides,
    }
    value["result_hash"] = result_hash(value)
    return value


@pytest.mark.parametrize(
    "overrides",
    (
        {"project_id": None},
        {"source_claim_ref": None},
        {"source_claimant_agent_id": "different-agent"},
        {"source_claim_generation": True},
        {"source_claim_generation": 0},
    ),
)
def test_background_result_requires_complete_exact_claim_lineage(overrides) -> None:
    with pytest.raises(AgentResultError, match="complete WC claim lineage"):
        validate_agent_result(_background_result(**overrides))


def test_background_result_execution_lineage_rejects_source_and_claim_drift() -> None:
    result = _background_result()
    execution = {
        "agent_type": "PA",
        "agent_id": AGENT_ID,
        "project_id": "project-p7",
        "source_type": "CLAIMED_WORKITEM",
        "work_item_ref": "work-item-p7",
        "claim_ref": "claim-p7",
        "claim_generation": 1,
        "assignment_ref": "assignment-p7",
        "state": "RUNNING",
    }
    validate_agent_result(result)
    result_module._require_execution_lineage(execution, result)

    with pytest.raises(AgentResultError, match="claim lineage"):
        result_module._require_execution_lineage(
            {**execution, "source_type": "PROMPT"}, result
        )
    with pytest.raises(AgentResultError, match="claim lineage"):
        result_module._require_execution_lineage(
            {**execution, "assignment_ref": "different-assignment"}, result
        )


def test_hash_excludes_identity_time_and_sorts_reference_sets() -> None:
    first = _result()
    second = copy.deepcopy(first)
    second["result_id"] = "different-id"
    second["created_at"] = "2027-01-01T00:00:00Z"
    second["business_refs"].reverse()
    second["citation_refs"].reverse()

    assert result_hash(second) == first["result_hash"]
    second["warnings"] = ["changed"]
    assert result_hash(second) != first["result_hash"]


@pytest.mark.parametrize(
    ("legacy_status", "step_state", "expected_status", "quality"),
    [
        ("NO_ANSWER", "BLOCKED", "BLOCKED", None),
        ("FAILED", "FAILED", "FAILED", None),
        ("CANCELLED", "CANCELLED", "CANCELLED", None),
    ],
)
def test_maps_legacy_non_success_to_frozen_result_status(
    legacy_status: str, step_state: str, expected_status: str, quality: str | None
) -> None:
    result = build_agent_result(
        execution=_execution(),
        step=_step(state=step_state),
        legacy_result=_legacy(status=legacy_status),
        result_id=RESULT_ID,
        created_at=NOW,
    )
    assert (result["status"], result["quality"]) == (expected_status, quality)


@pytest.mark.parametrize(
    ("quality,warning_action"),
    [
        ({"boundary_status": "WARN", "issue_count": 0}, "proceed"),
        ({"boundary_status": "PASS", "issue_count": 2}, "proceed"),
        ({"boundary_status": "UNKNOWN", "issue_count": True}, "proceed"),
        ({"boundary_status": "PASS", "issue_count": 0}, "ask_confirmation"),
        ({"boundary_status": "FAIL", "issue_count": 0}, "proceed"),
    ],
)
def test_completed_legacy_result_uses_real_quality_for_partial(
    quality: dict, warning_action: str
) -> None:
    legacy = _legacy(
        generation={"grounded_response_quality": quality},
        retrieval={
            "quality_warnings": {"recommended_action": warning_action}
        },
    )
    result = build_agent_result(
        execution=_execution(),
        step=_step(),
        legacy_result=legacy,
        result_id=RESULT_ID,
        created_at=NOW,
    )
    assert result["status"] == "PARTIAL"
    assert result["quality"] == "COMPLETE_WITH_WARNINGS"
    assert result["warnings"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("SUCCEEDED", ("RUNNING", "RESULT_PUBLISH", False)),
        ("PARTIAL", ("RUNNING", "RESULT_PUBLISH", False)),
        ("BLOCKED", ("BLOCKED", "FINALIZE", True)),
        ("FAILED", ("FAILED", "FINALIZE", True)),
        ("CANCELLED", ("CANCELLED", "FINALIZE", True)),
    ],
)
def test_issue_026_execution_destination_is_explicit(status: str, expected: tuple) -> None:
    assert execution_destination(status) == expected


def test_frozen_publication_identity_has_fixed_vector() -> None:
    assert derive_publication_identity(
        result_id=RESULT_ID,
        target_type="WORKSPACE_RESULT",
        target_ref=WORKSPACE_ID,
        result_hash_value="sha256:abc",
    ) == (
        "PUBOP:737b55389b6991cd87bca9af3b2ce769866dd51c450db93947d0fd37672b1d41",
        "PUBIDEMP:737b55389b6991cd87bca9af3b2ce769866dd51c450db93947d0fd37672b1d41",
    )


def test_repository_persists_result_delivery_and_success_handoff_atomically() -> None:
    sessions = _session_factory()
    repository = SqlAlchemyAgentResultRepository(sessions)
    result = _result()

    aggregate = repository.persist_with_pending_delivery(
        result=result, delivery_id=DELIVERY_ID
    )

    assert aggregate.result == result
    _validate(DELIVERY_SCHEMA, aggregate.delivery)
    assert aggregate.delivery["target_ref"] == WORKSPACE_ID
    assert aggregate.delivery["required"] is True
    assert aggregate.delivery["state"] == "PENDING"
    assert aggregate.delivery["latest_preflight_ref"] is None
    assert aggregate.execution["state"] == "RUNNING"
    assert aggregate.execution["phase"] == "RESULT_PUBLISH"
    assert aggregate.execution["completed_at"] is None
    assert aggregate.execution["result_id"] == RESULT_ID
    assert aggregate.execution["version"] == 2
    assert repository.get(TENANT, RESULT_ID) == aggregate
    assert repository.get(TENANT, "missing") is None


@pytest.mark.parametrize(
    ("legacy_status", "terminal_state"),
    [("NO_ANSWER", "BLOCKED"), ("FAILED", "FAILED"), ("CANCELLED", "CANCELLED")],
)
def test_repository_terminalizes_non_success_without_fake_running_state(
    legacy_status: str, terminal_state: str
) -> None:
    sessions = _session_factory(step_state=terminal_state)
    aggregate = SqlAlchemyAgentResultRepository(
        sessions
    ).persist_with_pending_delivery(
        result=_result(legacy_status=legacy_status), delivery_id=DELIVERY_ID
    )

    assert aggregate.execution["state"] == terminal_state
    assert aggregate.execution["phase"] == "FINALIZE"
    assert aggregate.execution["completed_at"] == NOW
    assert aggregate.delivery["state"] == "PENDING"


def test_repository_duplicate_is_idempotent_and_semantic_change_conflicts() -> None:
    sessions = _session_factory()
    repository = SqlAlchemyAgentResultRepository(sessions)
    result = _result()
    first = repository.persist_with_pending_delivery(
        result=result, delivery_id=DELIVERY_ID
    )
    duplicate = repository.persist_with_pending_delivery(
        result=result, delivery_id=DELIVERY_ID
    )
    assert duplicate == first

    changed = copy.deepcopy(result)
    changed["warnings"] = ["changed"]
    changed["result_hash"] = result_hash(changed)
    with pytest.raises(AgentResultError) as conflict:
        repository.persist_with_pending_delivery(
            result=changed, delivery_id=DELIVERY_ID
        )
    assert conflict.value.error_code == "ae.agent_result_semantic_conflict"

    changed_id = copy.deepcopy(result)
    changed_id["result_id"] = "88888888-8888-4888-8888-888888888888"
    with pytest.raises(AgentResultError) as identity_conflict:
        repository.persist_with_pending_delivery(
            result=changed_id,
            delivery_id="99999999-9999-4999-8999-999999999999",
        )
    assert identity_conflict.value.error_code == "ae.agent_result_semantic_conflict"


def test_delivery_failure_rolls_back_result_and_execution(monkeypatch) -> None:
    sessions = _session_factory()
    repository = SqlAlchemyAgentResultRepository(sessions)

    def fail_delivery(*_args):
        raise SQLAlchemyError("delivery failed")

    monkeypatch.setattr(repository, "_insert_delivery", fail_delivery)
    with pytest.raises(AgentResultError) as failed:
        repository.persist_with_pending_delivery(
            result=_result(), delivery_id=DELIVERY_ID
        )
    assert failed.value.error_code == "ae.agent_result_store_unavailable"
    assert failed.value.retryable is True
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_result")).scalar() == 0
        execution = session.execute(
            text("SELECT state, phase, result_id FROM ae_agent_execution")
        ).mappings().one()
    assert dict(execution) == {"state": "QUEUED", "phase": "INTAKE", "result_id": None}


@pytest.mark.parametrize(
    ("factory_kwargs", "error_code"),
    [
        ({"with_execution": False}, "ae.agent_result_execution_not_found"),
        ({"with_step": False}, "ae.agent_result_step_not_found"),
        ({"workspace_id": None}, "ae.agent_result_invalid"),
        ({"execution_project_id": "project-a"}, "ae.agent_result_invalid"),
        ({"execution_state": "SUCCEEDED"}, "ae.agent_result_delivery_ack_required"),
        ({"step_state": "FAILED"}, "ae.agent_result_invalid"),
    ],
)
def test_repository_fails_closed_on_invalid_runtime_lineage(
    factory_kwargs: dict, error_code: str
) -> None:
    repository = SqlAlchemyAgentResultRepository(_session_factory(**factory_kwargs))
    with pytest.raises(AgentResultError) as failed:
        repository.persist_with_pending_delivery(
            result=_result(), delivery_id=DELIVERY_ID
        )
    assert failed.value.error_code == error_code


def test_repository_detects_missing_delivery_and_execution_cas_conflict(monkeypatch) -> None:
    sessions = _session_factory()
    repository = SqlAlchemyAgentResultRepository(sessions)
    repository.persist_with_pending_delivery(result=_result(), delivery_id=DELIVERY_ID)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM ae_result_delivery"))
    with pytest.raises(AgentResultError) as missing:
        repository.get(TENANT, RESULT_ID)
    assert missing.value.error_code == "ae.agent_result_delivery_missing"
    with pytest.raises(AgentResultError) as duplicate_missing:
        repository.persist_with_pending_delivery(
            result=_result(), delivery_id=DELIVERY_ID
        )
    assert duplicate_missing.value.error_code == "ae.agent_result_delivery_missing"

    fresh = _session_factory()
    blocked = SqlAlchemyAgentResultRepository(fresh)
    monkeypatch.setattr(
        result_module,
        "_EXECUTION_RESULT_UPDATE_SQL",
        result_module._EXECUTION_RESULT_UPDATE_SQL + " AND 1 = 0",
    )
    with pytest.raises(AgentResultError) as conflict:
        blocked.persist_with_pending_delivery(result=_result(), delivery_id=DELIVERY_ID)
    assert conflict.value.error_code == "ae.agent_result_execution_conflict"
    assert conflict.value.retryable is True


def test_repository_maps_missing_schema_to_stable_unavailable_error() -> None:
    repository = SqlAlchemyAgentResultRepository(_session_factory(with_schema=False))
    with pytest.raises(AgentResultError) as read_error:
        repository.get(TENANT, RESULT_ID)
    assert read_error.value.error_code == "ae.agent_result_store_unavailable"
    with pytest.raises(AgentResultError) as write_error:
        repository.persist_with_pending_delivery(
            result=_result(), delivery_id=DELIVERY_ID
        )
    assert write_error.value.error_code == "ae.agent_result_store_unavailable"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda item: item.pop("provenance"),
        lambda item: item.__setitem__("schema_version", "1.0"),
        lambda item: item.__setitem__("status", "ESCALATED"),
        lambda item: item.__setitem__("source_claim_ref", "claim-a"),
        lambda item: item["structured_result"].__setitem__("content", "private"),
        lambda item: item.__setitem__("result_hash", "sha256:wrong"),
    ],
)
def test_validation_rejects_contract_privacy_and_hash_violations(mutator) -> None:
    result = _result()
    mutator(result)
    with pytest.raises(AgentResultError):
        validate_agent_result(result)


@pytest.mark.parametrize(
    "builder",
    [
        lambda: build_agent_result(
            execution=_execution(project_id="project-a"),
            step=_step(), legacy_result=_legacy(), result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(),
            step=_step(tenant_id="tenant-b"), legacy_result=_legacy(),
            result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(),
            legacy_result=_legacy(interaction_id="other"),
            result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(state="FAILED"),
            legacy_result=_legacy(), result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(),
            legacy_result=_legacy(status="PENDING"),
            result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(),
            legacy_result=_legacy(artifact_refs="bad"),
            result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(),
            legacy_result=_legacy(artifact_refs=[3]),
            result_id=RESULT_ID, created_at=NOW
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(), legacy_result=_legacy(),
            result_id=RESULT_ID, created_at="not-a-time"
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(), legacy_result=_legacy(),
            result_id=RESULT_ID, created_at="2026-10-13T04:00:00",
        ),
        lambda: build_agent_result(
            execution=_execution(), step=_step(), legacy_result=_legacy(),
            result_id=RESULT_ID, created_at=NOW, business_refs="bad"
        ),
    ],
)
def test_builder_rejects_invalid_terminal_input(builder) -> None:
    with pytest.raises(AgentResultError):
        builder()


def test_invalid_destination_identity_json_and_string_helpers_are_guarded() -> None:
    with pytest.raises(AgentResultError):
        execution_destination("ESCALATED")
    with pytest.raises(AgentResultError):
        derive_publication_identity(
            result_id="", target_type="WORKSPACE_RESULT",
            target_ref=WORKSPACE_ID, result_hash_value="sha256:a"
        )
    result = _result()
    result["structured_result"] = {"not_json": object()}
    with pytest.raises(AgentResultError):
        result_hash(result)
    non_list_projection = _result()
    non_list_projection["business_refs"] = None
    assert result_hash(non_list_projection).startswith("sha256:")


def test_invalid_stored_envelope_and_datetime_conversion_are_guarded() -> None:
    sessions = _session_factory()
    repository = SqlAlchemyAgentResultRepository(sessions)
    repository.persist_with_pending_delivery(result=_result(), delivery_id=DELIVERY_ID)
    with sessions.begin() as session:
        session.execute(
            text("UPDATE ae_agent_result SET result_envelope_json = '[]'")
        )
    with pytest.raises(AgentResultError) as invalid:
        repository.get(TENANT, RESULT_ID)
    assert invalid.value.error_code == "ae.agent_result_envelope_invalid"
    assert result_module._datetime_value(
        datetime(2026, 10, 13, 4, 0, tzinfo=UTC)
    ) == NOW
    assert str(AgentResultError("code", "detail")) == "detail"


def test_migration_and_source_keep_p4_boundary_explicit() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    source = inspect.getsource(result_module)

    assert "UNIQUE (tenant_id, agent_execution_id)" in migration
    assert "result_envelope_json JSONB NOT NULL" in migration
    assert "ADD COLUMN IF NOT EXISTS completed_at" in migration
    assert "ae_result_delivery" in migration
    assert "PUBLISH_RESULT" not in migration
    assert "WORKSPACE_RESULT" in source
    assert "WC_WORK_RESULT" in source
    assert 'target_type = "WC_WORK_RESULT" if background else "WORKSPACE_RESULT"' in source
    assert AGENT_RESULT_STATUSES == {
        "SUCCEEDED", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"
    }
