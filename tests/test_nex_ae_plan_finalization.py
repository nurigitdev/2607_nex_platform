from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api import agent_results
from nex_ae_api import plan_finalization as finalization
from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.executable_plans import executable_plan_semantic_projection
from nex_ae_api.plan_finalization import (
    P5CompletionVerification,
    P5PlanFinalizationError,
    SqlAlchemyP5PlanFinalizationService,
    build_plan_agent_result,
    derive_plan_result_ids,
    verify_plan_completion,
)
from nex_ae_api.step_results import build_step_result
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from test_nex_ae_executable_plans import (
    EXECUTABLE_PLAN_ID,
    EXECUTION_ID,
    STEP_2_ID,
    _compiled,
)

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = ROOT / (
    "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/"
    "NeX_Platform_v2.1_Controlled_Amendment_Batch08_E2E11_RESULT_PUBLICATION/"
    "AE_PUBLICATION/agent-result-v2.1.schema.json"
)
DELIVERY_SCHEMA = RESULT_SCHEMA.with_name("result-delivery-v2.1.schema.json")
TENANT = "tenant-p5-finalization"
AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RESULT_1_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
RESULT_2_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NOW = "2026-10-14T09:00:00Z"


def _step_results(statuses=("SUCCEEDED", "SUCCEEDED"), plan=None):
    plan = plan or _compiled()
    values = []
    for index, (step, status, result_id) in enumerate(
        zip(plan["steps"], statuses, (RESULT_1_ID, RESULT_2_ID), strict=True),
        start=1,
    ):
        values.append(
            build_step_result(
                step_result_id=result_id,
                execution_id=EXECUTION_ID,
                executable_plan_id=EXECUTABLE_PLAN_ID,
                executable_step_id=step["executable_step_id"],
                compiled_step_key=step["compiled_step_key"],
                logical_step_ref=step["logical_step_ref"],
                attempt_no=1,
                status=status,
                result_contract_ref=step["output_contract_ref"],
                result_payload={"result_ref": f"result-{index}"},
                external_refs=(f"CX:RESULT:{index}",),
                artifact_refs=(f"AE:ARTIFACT:{index}",),
                evidence_refs=(f"AE:EVIDENCE:{index}",),
                error_ref=None if status == "SUCCEEDED" else f"error-{index}",
                started_at=NOW,
                completed_at=NOW,
            )
        )
    return values


def _execution(*, phase="RESULT_VERIFY", state="RUNNING", project_id=None):
    return {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": "IA",
        "project_id": project_id,
        "workspace_id": WORKSPACE_ID,
        "state": state,
        "phase": phase,
        "version": 1,
        "result_id": None,
        "correlation_id": "p5-finalization",
        "causation_id": "p5-s7",
    }


def _factory(
    *,
    statuses=("SUCCEEDED", "SUCCEEDED"),
    execution=True,
    plan=True,
    phase="RESULT_VERIFY",
    state="RUNNING",
):
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        for ddl in (
            """CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, agent_type TEXT NOT NULL, project_id TEXT,
                workspace_id TEXT, state TEXT NOT NULL, phase TEXT NOT NULL,
                version INTEGER NOT NULL, result_id TEXT, correlation_id TEXT NOT NULL,
                causation_id TEXT, completed_at TEXT, updated_at TEXT,
                PRIMARY KEY (tenant_id, agent_execution_id))""",
            """CREATE TABLE ae_executable_plan (
                tenant_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                executable_plan_version INTEGER NOT NULL, agent_execution_id TEXT NOT NULL,
                plan_json TEXT NOT NULL, PRIMARY KEY (tenant_id, executable_plan_id))""",
            """CREATE TABLE ae_step_result (
                tenant_id TEXT NOT NULL, step_result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                executable_step_id TEXT NOT NULL, compiled_step_key TEXT NOT NULL,
                result_hash TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, step_result_id))""",
            """CREATE TABLE ae_agent_result (
                tenant_id TEXT NOT NULL, result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                agent_id TEXT, project_id TEXT, status TEXT NOT NULL, quality TEXT,
                structured_result_json TEXT NOT NULL, result_envelope_json TEXT NOT NULL,
                result_hash TEXT NOT NULL, source_work_item_ref TEXT,
                source_claim_ref TEXT, source_claim_generation INTEGER,
                source_claimant_agent_id TEXT, source_assignment_ref TEXT,
                created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, result_id),
                UNIQUE (tenant_id, agent_execution_id))""",
            """CREATE TABLE ae_result_delivery (
                tenant_id TEXT NOT NULL, delivery_id TEXT NOT NULL, result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, target_type TEXT NOT NULL,
                target_ref TEXT NOT NULL, required BOOLEAN NOT NULL, state TEXT NOT NULL,
                publication_operation_id TEXT NOT NULL, idempotency_key_ref TEXT NOT NULL,
                attempt_no INTEGER NOT NULL, external_delivery_ref TEXT,
                latest_preflight_ref TEXT, publication_reconciliation_ref TEXT,
                correlation_id TEXT NOT NULL, causation_id TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, acknowledged_at TEXT,
                PRIMARY KEY (tenant_id, delivery_id),
                UNIQUE (tenant_id, result_id, target_type, target_ref))""",
        ):
            connection.execute(text(ddl))
        if execution:
            value = _execution(phase=phase, state=state)
            connection.execute(
                text("""INSERT INTO ae_agent_execution VALUES (
                    :tenant_id, :agent_execution_id, :agent_id, :agent_type,
                    :project_id, :workspace_id, :state, :phase, :version,
                    :result_id, :correlation_id, :causation_id, NULL, :now)"""),
                {**value, "now": NOW},
            )
        if plan:
            compiled = _compiled()
            connection.execute(
                text("INSERT INTO ae_executable_plan VALUES (:t, :p, 1, :e, :j)"),
                {
                    "t": TENANT,
                    "p": EXECUTABLE_PLAN_ID,
                    "e": EXECUTION_ID,
                    "j": json.dumps(compiled),
                },
            )
            for item in _step_results(statuses, compiled):
                connection.execute(
                    text("INSERT INTO ae_step_result VALUES (:t,:r,:e,:p,:s,:k,:h,:j)"),
                    {
                        "t": TENANT,
                        "r": item["step_result_id"],
                        "e": EXECUTION_ID,
                        "p": EXECUTABLE_PLAN_ID,
                        "s": item["executable_step_id"],
                        "k": item["compiled_step_key"],
                        "h": item["result_hash"],
                        "j": json.dumps(item),
                    },
                )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _validated_result(statuses=("SUCCEEDED", "SUCCEEDED")):
    plan = _compiled()
    results = _step_results(statuses, plan)
    verification = verify_plan_completion(executable_plan=plan, step_results=results)
    result_id, _ = derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    result = build_plan_agent_result(
        execution=_execution(),
        executable_plan=plan,
        step_results=results,
        verification=verification,
        result_id=result_id,
        created_at=NOW,
    )
    return plan, results, verification, result


def _validate(path: Path, payload: dict) -> None:
    Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(payload)


def test_verifies_and_builds_reference_only_plan_agent_result() -> None:
    plan, _, verification, result = _validated_result()

    _validate(RESULT_SCHEMA, result)
    assert verification.status == "SUCCEEDED"
    assert verification.required_compiled_step_keys == ("E2",)
    assert result["status"] == "SUCCEEDED"
    assert result["quality"] == "COMPLETE"
    assert result["work_intent_ref"].startswith("AE:WORK_INTENT:")
    assert result["executable_plan_ref"].endswith(plan["executable_plan_hash"])
    output = result["structured_result"]["output_step_results"]
    assert [item["compiled_step_key"] for item in output] == ["E2"]
    assert result["artifact_refs"] == ["AE:ARTIFACT:1", "AE:ARTIFACT:2"]
    assert len(result["evidence_refs"]) == 4
    assert "result_payload" not in json.dumps(result)


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "BLOCKED"])
def test_completion_status_uses_fail_closed_precedence(status: str) -> None:
    verification = verify_plan_completion(
        executable_plan=_compiled(),
        step_results=_step_results(("SUCCEEDED", status)),
    )

    assert verification.status == status


def test_completion_verification_rejects_incomplete_duplicate_and_lineage_drift() -> (
    None
):
    plan = _compiled()
    results = _step_results(plan=plan)
    with pytest.raises(P5PlanFinalizationError) as incomplete:
        verify_plan_completion(executable_plan=plan, step_results=results[:1])
    assert incomplete.value.error_code == "ae.p5_plan_result_set_incomplete"

    with pytest.raises(P5PlanFinalizationError, match="duplicate"):
        verify_plan_completion(
            executable_plan=plan, step_results=[results[0], results[0]]
        )

    drifted = copy.deepcopy(results)
    drifted[0]["executable_step_id"] = STEP_2_ID
    drifted[0]["result_hash"] = finalization.semantic_sha256_hash_ref(
        {
            key: value
            for key, value in drifted[0].items()
            if key
            not in {"step_result_id", "started_at", "completed_at", "result_hash"}
        }
    )
    with pytest.raises(P5PlanFinalizationError, match="lineage"):
        verify_plan_completion(executable_plan=plan, step_results=drifted)

    invalid_result = copy.deepcopy(results)
    invalid_result[0]["result_hash"] = "sha256:bad"
    with pytest.raises(P5PlanFinalizationError, match="hash"):
        verify_plan_completion(executable_plan=plan, step_results=invalid_result)

    no_required = copy.deepcopy(plan)
    no_required["completion_criteria"][0]["required"] = False
    no_required["executable_plan_hash"] = semantic_sha256_hash_ref(
        executable_plan_semantic_projection(no_required)
    )
    with pytest.raises(P5PlanFinalizationError, match="no required"):
        verify_plan_completion(executable_plan=no_required, step_results=results)


def test_builder_rejects_project_and_verification_drift() -> None:
    plan = _compiled()
    results = _step_results(plan=plan)
    verification = verify_plan_completion(executable_plan=plan, step_results=results)
    result_id, _ = derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    with pytest.raises(P5PlanFinalizationError, match="project-neutral"):
        build_plan_agent_result(
            execution=_execution(project_id="project-a"),
            executable_plan=plan,
            step_results=results,
            verification=verification,
            result_id=result_id,
            created_at=NOW,
        )
    mismatched = P5CompletionVerification(
        status=verification.status,
        required_compiled_step_keys=verification.required_compiled_step_keys,
        completion_verification_refs=verification.completion_verification_refs,
        step_result_hashes={"E1": "sha256:" + "0" * 64},
        input_result_set_hash=verification.input_result_set_hash,
    )
    with pytest.raises(P5PlanFinalizationError, match="does not match"):
        build_plan_agent_result(
            execution=_execution(),
            executable_plan=plan,
            step_results=results,
            verification=mismatched,
            result_id=result_id,
            created_at=NOW,
        )


def test_builder_rejects_unsupported_and_incomplete_background_lineage() -> None:
    plan = _compiled()
    results = _step_results(plan=plan)
    verification = verify_plan_completion(executable_plan=plan, step_results=results)
    result_id, _ = derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    with pytest.raises(P5PlanFinalizationError, match="supported Agent"):
        build_plan_agent_result(
            execution={**_execution(), "agent_type": "UNSUPPORTED"},
            executable_plan=plan,
            step_results=results,
            verification=verification,
            result_id=result_id,
            created_at=NOW,
        )
    with pytest.raises(P5PlanFinalizationError, match="source lineage"):
        build_plan_agent_result(
            execution={
                **_execution(project_id="project-p7"),
                "agent_type": "PA",
                "source_type": "CLAIMED_WORKITEM",
            },
            executable_plan=plan,
            step_results=results,
            verification=verification,
            result_id=result_id,
            created_at=NOW,
        )


def test_service_persists_agent_result_delivery_and_replays_idempotently() -> None:
    factory = _factory()
    service = SqlAlchemyP5PlanFinalizationService(factory)

    first = service.finalize(
        tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW
    )
    replayed = service.finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at="2026-10-14T10:00:00Z",
    )

    assert replayed == first
    _validate(RESULT_SCHEMA, first.result)
    _validate(DELIVERY_SCHEMA, first.delivery)
    assert first.delivery["state"] == "PENDING"
    assert first.delivery["target_type"] == "WORKSPACE_RESULT"
    assert first.execution["state"] == "RUNNING"
    assert first.execution["phase"] == "RESULT_PUBLISH"
    assert first.execution["result_id"] == first.result["result_id"]


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "BLOCKED"])
def test_service_terminalizes_non_success_plan_result(status: str) -> None:
    aggregate = SqlAlchemyP5PlanFinalizationService(
        _factory(statuses=("SUCCEEDED", status))
    ).finalize(tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW)

    assert aggregate.result["status"] == status
    assert aggregate.execution["state"] == status
    assert aggregate.execution["phase"] == "FINALIZE"
    assert aggregate.delivery["state"] == "PENDING"


def test_repository_rechecks_plan_phase_hash_set_and_provenance() -> None:
    plan, _, verification, result = _validated_result()
    result_id, delivery_id = derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    result["result_id"] = result_id
    result["result_hash"] = agent_results.result_hash(result)

    not_ready = SqlAlchemyAgentResultRepository(_factory(phase="STEP_EXECUTION"))
    with pytest.raises(agent_results.AgentResultError) as phase_error:
        not_ready.persist_plan_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            executable_plan_id=plan["executable_plan_id"],
            step_result_hashes=verification.step_result_hashes,
            input_result_set_hash=verification.input_result_set_hash,
        )
    assert phase_error.value.error_code == "ae.agent_result_plan_not_ready"

    missing_plan = SqlAlchemyAgentResultRepository(_factory(plan=False))
    with pytest.raises(agent_results.AgentResultError) as plan_error:
        missing_plan.persist_plan_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            executable_plan_id=plan["executable_plan_id"],
            step_result_hashes=verification.step_result_hashes,
            input_result_set_hash=verification.input_result_set_hash,
        )
    assert plan_error.value.error_code == "ae.agent_result_plan_not_found"

    conflict = dict(verification.step_result_hashes)
    conflict["E2"] = "sha256:" + "0" * 64
    with pytest.raises(agent_results.AgentResultError) as hash_error:
        SqlAlchemyAgentResultRepository(_factory()).persist_plan_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            executable_plan_id=plan["executable_plan_id"],
            step_result_hashes=conflict,
            input_result_set_hash=verification.input_result_set_hash,
        )
    assert hash_error.value.error_code == "ae.agent_result_step_set_conflict"
    assert hash_error.value.retryable is True

    with pytest.raises(agent_results.AgentResultError, match="hash set"):
        SqlAlchemyAgentResultRepository(_factory()).persist_plan_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            executable_plan_id=plan["executable_plan_id"],
            step_result_hashes={},
            input_result_set_hash=verification.input_result_set_hash,
        )

    with pytest.raises(agent_results.AgentResultError, match="provenance"):
        SqlAlchemyAgentResultRepository(_factory()).persist_plan_with_pending_delivery(
            result=result,
            delivery_id=delivery_id,
            executable_plan_id=plan["executable_plan_id"],
            step_result_hashes=verification.step_result_hashes,
            input_result_set_hash="sha256:" + "f" * 64,
        )


def test_service_guards_missing_state_store_and_repository_errors(monkeypatch) -> None:
    with pytest.raises(P5PlanFinalizationError) as missing_execution:
        SqlAlchemyP5PlanFinalizationService(_factory(execution=False)).finalize(
            tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW
        )
    assert (
        missing_execution.value.error_code == "ae.p5_finalization_execution_not_found"
    )

    with pytest.raises(P5PlanFinalizationError) as missing_plan:
        SqlAlchemyP5PlanFinalizationService(_factory(plan=False)).finalize(
            tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW
        )
    assert missing_plan.value.error_code == "ae.p5_finalization_plan_not_found"

    factory = _factory()
    monkeypatch.setattr(
        finalization,
        "_load_execution",
        lambda *a: (_ for _ in ()).throw(SQLAlchemyError("store")),
    )
    with pytest.raises(P5PlanFinalizationError) as unavailable:
        SqlAlchemyP5PlanFinalizationService(factory).finalize(
            tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW
        )
    assert unavailable.value.retryable is True

    class _FailingResults:
        def persist_plan_with_pending_delivery(self, **_kwargs):
            raise agent_results.AgentResultError("result.failed", "failed", True)

    monkeypatch.setattr(finalization, "_load_execution", lambda *a: _execution())
    monkeypatch.setattr(finalization, "_load_latest_plan", lambda *a: _compiled())
    monkeypatch.setattr(
        finalization, "load_step_results_for_plan", lambda *a: _step_results()
    )
    with pytest.raises(P5PlanFinalizationError) as result_error:
        SqlAlchemyP5PlanFinalizationService(
            factory, results=_FailingResults()
        ).finalize(tenant_id=TENANT, execution_id=EXECUTION_ID, created_at=NOW)
    assert result_error.value.error_code == "result.failed"
    assert result_error.value.retryable is True


def test_identity_and_primitive_guards_are_deterministic() -> None:
    verification = verify_plan_completion(
        executable_plan=_compiled(), step_results=_step_results()
    )
    first = derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    assert first == derive_plan_result_ids(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        input_result_set_hash=verification.input_result_set_hash,
    )
    with pytest.raises(P5PlanFinalizationError, match="UUID"):
        derive_plan_result_ids(
            tenant_id=TENANT,
            execution_id="bad",
            input_result_set_hash=verification.input_result_set_hash,
        )
    with pytest.raises(P5PlanFinalizationError, match="timestamp"):
        SqlAlchemyP5PlanFinalizationService(_factory()).finalize(
            tenant_id=TENANT, execution_id=EXECUTION_ID, created_at="bad"
        )
    with pytest.raises(P5PlanFinalizationError, match="valid JSON"):
        finalization._json_object("not-json")
    with pytest.raises(P5PlanFinalizationError, match="not an object"):
        finalization._json_object("[]")
    with pytest.raises(P5PlanFinalizationError, match="bounded string"):
        finalization._required_text("field", "", 8)
    with pytest.raises(P5PlanFinalizationError, match="canonical UUID"):
        finalization._required_uuid("field", "{11111111-1111-4111-8111-111111111111}")
    with pytest.raises(P5PlanFinalizationError, match="timezone"):
        finalization._timestamp("field", "2026-10-14T09:00:00")
    with pytest.raises(P5PlanFinalizationError, match="must be an array"):
        finalization._union_result_refs([{"artifact_refs": "bad"}], "artifact_refs")
    assert str(P5PlanFinalizationError("code", "detail")) == "detail"
