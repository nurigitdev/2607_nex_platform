from __future__ import annotations

import copy

import nex_wc.work_results as wc_work_results
import pytest
from nex_ae_api.business_result_summary import (
    build_project_allocation_summary,
    build_voucher_draft_summary,
    summary_from_step_results,
)
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.step_executors import P5StepExecutorError, _delegated_result_outcome
from nex_ae_api.step_results import build_step_result
from nex_ae_api.work_result_events import (
    WorkResultEventError,
    validate_work_result_event,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_runtime.work_result_business_projection import (
    WorkResultBusinessProjectionError,
    build_work_result_business_projection,
    validate_work_result_business_projection,
)

TENANT = "tenant-w80-ca00b"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"
RESULT_ID = "result-w80-ca00b"
EVENT_ID = "22222222-2222-4222-8222-222222222222"
EXECUTION_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_ID = "44444444-4444-4444-8444-444444444444"
ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
AGENT_ID = "66666666-6666-4666-8666-666666666666"
BUSINESS_OPERATION_ID = "77777777-7777-4777-8777-777777777777"
SECOND_BUSINESS_OPERATION_ID = "88888888-8888-4888-8888-888888888888"
CONTRACT = "contract://nex/mybee/finance-result/v1"
NOW = "2026-11-23T09:00:00Z"
AGENT_RESULT_HASH = semantic_sha256_hash_ref({"result": "pa-authority"})


def _summary(*, business_operation_id: str = BUSINESS_OPERATION_ID):
    return build_voucher_draft_summary(
        commit_state="COMMITTED",
        verification_status="VERIFIED",
        approval_state="APPROVED",
        business_operation_id=business_operation_id,
        voucher_number="M1-2026-0001",
        amount="10000.00",
        currency="USD",
        account_codes=("6100", "2100"),
        project_code="M1A7D260001",
    )


def _work_result():
    return {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "work_item_id": WORK_ITEM_ID,
        "revision_no": 1,
        "result_type": "AGENT_RESULT",
        "summary": None,
        "payload": {
            "agent_result_ref": f"AE:AGENT_RESULT:{RESULT_ID}",
            "agent_result_hash": AGENT_RESULT_HASH,
            "structured_result": {
                "external_refs": [
                    f"EOS:BUSINESS_OPERATION:{BUSINESS_OPERATION_ID}",
                    "EOS:JOURNAL:M1-2026-0001",
                ],
                "business_summary": _summary(),
            },
        },
        "schema_ref": CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "PENDING_VERIFICATION",
        "artifact_refs": [],
        "evidence_refs": [],
        "business_object_refs": [
            {
                "entity_type": "BUSINESS_OBJECT",
                "entity_id": f"EOS:BUSINESS_OPERATION:{BUSINESS_OPERATION_ID}",
            }
        ],
        "source_execution_ref": EXECUTION_ID,
        "source_plan_ref": "plan-w80-ca00b",
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "trace": {
            "correlation_id": "trace-w80-ca00b",
            "causation_id": EXECUTION_ID,
        },
        "submitted_at": NOW,
    }


def _allocation_summary():
    return build_project_allocation_summary(
        {
            "journal_ref": "eos.posted_journal:journal-1",
            "source_pool_ref": "eos.cost-source-pool:pool-1",
            "source_pool_hash": "sha256:" + "1" * 64,
            "allocation_batch_ref": "eos.cost-allocation-batch:batch-1",
            "allocation_reconciliation_hash": "sha256:" + "2" * 64,
            "pnl_refresh_hash": "sha256:" + "3" * 64,
            "project_results": [
                {
                    "project_code": "M1A7D260001",
                    "projection_id": "99999999-9999-4999-8999-999999999999",
                    "projection_version": 1,
                    "projection_hash": "sha256:" + "4" * 64,
                    "reconciliation_status": "VERIFIED",
                    "freshness_status": "CURRENT",
                    "data_classification": "CONFIDENTIAL_FINANCIAL",
                }
            ],
        }
    )


def _event():
    normalized = wc_work_results.validate_work_result(_work_result())
    return wc_work_results._result_event(
        normalized,
        event_id=EVENT_ID,
        now=NOW,
    )


def _context(event):
    return StepExecutionContext(
        job={
            "job_type": "RESUME_EXECUTION",
            "payload": {
                "event_id": event["event_id"],
                "result_id": event["result_id"],
                "external_ref": event["work_item_id"],
            },
        },
        attempt={},
        step={"output_contract_ref": CONTRACT},
        dependency_results=(),
        existing_result=None,
    )


def test_ca00b_projection_is_canonical_hash_bound_and_bounded() -> None:
    projection = build_work_result_business_projection(
        source_agent_result_hash=AGENT_RESULT_HASH,
        business_object_refs=_work_result()["business_object_refs"],
        external_refs=["EOS:JOURNAL:M1-2026-0001"],
        business_summary=_summary(),
    )
    assert validate_work_result_business_projection(projection) == projection
    assert projection["projection_hash"].startswith("sha256:")

    tampered = copy.deepcopy(projection)
    tampered["business_summary"]["summary"]["amount"] = "1.00"
    with pytest.raises(WorkResultBusinessProjectionError, match="hash"):
        validate_work_result_business_projection(tampered)

    duplicate = copy.deepcopy(projection)
    duplicate.pop("projection_hash")
    duplicate["business_object_refs"] *= 2
    with pytest.raises(WorkResultBusinessProjectionError, match="duplicate"):
        build_work_result_business_projection(
            source_agent_result_hash=duplicate["source_agent_result_hash"],
            business_object_refs=duplicate["business_object_refs"],
            external_refs=duplicate["external_refs"],
            business_summary=duplicate["business_summary"],
        )


def test_ca00b_wc_outbox_event_projects_only_safe_business_result() -> None:
    event = _event()
    projection = event["business_result"]
    assert projection["source_agent_result_hash"] == AGENT_RESULT_HASH
    assert projection["business_summary"] == _summary()
    assert projection["business_object_refs"] == _work_result()[
        "business_object_refs"
    ]
    assert "structured_result" not in projection
    assert "payload" not in projection
    assert validate_work_result_event(event) == event


def test_ca00b_ae_resume_restores_summary_and_business_operation_lineage() -> None:
    event = validate_work_result_event(_event())
    outcome = _delegated_result_outcome(_context(event), event)
    assert outcome.state == "SUCCEEDED"
    assert outcome.business_operation_id is None
    assert outcome.result_payload["business_summary"] == _summary()
    assert outcome.result_payload["source_agent_result_hash"] == AGENT_RESULT_HASH
    step_result = build_step_result(
        step_result_id="99999999-9999-4999-8999-999999999991",
        execution_id=EXECUTION_ID,
        executable_plan_id="99999999-9999-4999-8999-999999999992",
        executable_step_id="99999999-9999-4999-8999-999999999993",
        compiled_step_key="E1",
        logical_step_ref="S1",
        attempt_no=1,
        status=outcome.state,
        result_contract_ref=outcome.result_contract_ref,
        result_payload=outcome.result_payload,
        external_refs=outcome.external_refs,
        evidence_refs=outcome.evidence_refs,
        business_operation_id=outcome.business_operation_id,
        started_at=NOW,
        completed_at=NOW,
    )
    assert step_result["schema_version"] == "1.1"
    assert step_result["business_operation_id"] is None
    assert summary_from_step_results(
        ({"result_payload": outcome.result_payload},)
    ) == _summary()
    assert f"EOS:BUSINESS_OPERATION:{BUSINESS_OPERATION_ID}" in outcome.external_refs


def test_ca00b_generic_business_summary_preserves_multi_operation_lineage() -> None:
    operation_refs = [
        f"EOS:BUSINESS_OPERATION:{BUSINESS_OPERATION_ID}",
        f"EOS:BUSINESS_OPERATION:{SECOND_BUSINESS_OPERATION_ID}",
    ]
    event = _event()
    event["business_result"] = build_work_result_business_projection(
        source_agent_result_hash=AGENT_RESULT_HASH,
        business_object_refs=[
            {"entity_type": "BUSINESS_OBJECT", "entity_id": item}
            for item in operation_refs
        ],
        external_refs=["eos.cost-allocation-batch:batch-1"],
        business_summary=_allocation_summary(),
    )
    event = validate_work_result_event(event)

    outcome = _delegated_result_outcome(_context(event), event)

    assert outcome.state == "SUCCEEDED"
    assert outcome.business_operation_id is None
    assert outcome.result_payload["business_summary"] == _allocation_summary()
    assert set(operation_refs).issubset(outcome.external_refs)
    assert summary_from_step_results(
        ({"result_payload": outcome.result_payload},)
    ) == _allocation_summary()


def test_ca00b_tamper_and_operation_lineage_drift_fail_closed() -> None:
    event = _event()
    event["business_result"]["business_summary"]["summary"]["amount"] = "1.00"
    with pytest.raises(WorkResultEventError, match="projection"):
        validate_work_result_event(event)

    event = _event()
    event["business_result"] = build_work_result_business_projection(
        source_agent_result_hash=AGENT_RESULT_HASH,
        business_object_refs=[
            {
                "entity_type": "BUSINESS_OBJECT",
                "entity_id": "EOS:BUSINESS_OPERATION:other-operation",
            }
        ],
        external_refs=[],
        business_summary=_summary(),
    )
    event = validate_work_result_event(event)
    with pytest.raises(P5StepExecutorError, match="lineage"):
        _delegated_result_outcome(_context(event), event)

    event = _event()
    event["business_result"] = build_work_result_business_projection(
        source_agent_result_hash=AGENT_RESULT_HASH,
        business_object_refs=[],
        external_refs=[],
        business_summary=_summary(),
    )
    event = validate_work_result_event(event)
    with pytest.raises(P5StepExecutorError, match="lacks business operation"):
        _delegated_result_outcome(_context(event), event)


def test_ca00b_reference_only_projection_remains_admissible() -> None:
    event = _event()
    event["business_result"] = build_work_result_business_projection(
        source_agent_result_hash=AGENT_RESULT_HASH,
        business_object_refs=_work_result()["business_object_refs"],
        external_refs=[],
        business_summary=None,
    )
    event = validate_work_result_event(event)
    outcome = _delegated_result_outcome(_context(event), event)
    assert "business_summary" not in outcome.result_payload
    assert outcome.business_operation_id is None


def test_ca00b_legacy_work_result_event_remains_compatible() -> None:
    event = _event()
    event.pop("business_result")
    admitted = validate_work_result_event(event)
    outcome = _delegated_result_outcome(_context(admitted), admitted)
    assert "business_summary" not in outcome.result_payload
    assert outcome.business_operation_id is None
