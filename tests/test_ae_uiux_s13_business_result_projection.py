from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from nex_ae_api.business_result_summary import (
    BusinessResultSummaryError,
    admit_business_result_summary,
    build_voucher_draft_summary,
    summary_from_step_results,
)
from nex_ae_api.plan_finalization import build_plan_agent_result, verify_plan_completion
from nex_ae_api.product_controlled_skill import _controlled_write_outcome
from nex_ae_api.step_results import build_step_result
from nex_ae_api.workspace_result_publication import (
    WorkspaceResultPublicationError,
    _interaction_result_projection,
)
from test_nex_ae_executable_plans import _compiled
from test_nex_ae_plan_finalization import EXECUTION_ID, NOW, _execution, _step_results

ROOT = Path(__file__).resolve().parents[1]


def _voucher_summary(**overrides: object) -> dict[str, object]:
    values = {
        "commit_state": "COMMITTED",
        "verification_status": "VERIFIED",
        "approval_state": "APPROVED",
        "business_operation_id": "operation-1",
        "voucher_number": "voucher-1",
        "amount": "12500",
        "currency": "krw",
        "account_codes": ("TRAVEL", "CASH"),
        "project_code": "NVT",
    }
    values.update(overrides)
    return build_voucher_draft_summary(**values)  # type: ignore[arg-type]


def _projection_row(summary: object) -> dict[str, object]:
    envelope = {
        "structured_result_contract_ref": (
            "contract://nex/eos/create-voucher-draft-result/v1"
        ),
        "structured_result": {
            "external_refs": ["eos.voucher_draft:voucher-1"],
            "business_summary": summary,
        },
        "business_refs": ["EOS:BUSINESS_OPERATION:operation-1"],
        "artifact_refs": [],
        "warnings": [],
    }
    return {
        "result_id": "result-1",
        "result_envelope_json": json.dumps(envelope),
        "result_hash": "sha256:" + "a" * 64,
        "result_status": "SUCCEEDED",
        "delivery_id": "delivery-1",
        "delivery_state": "ACKNOWLEDGED",
        "external_delivery_ref": "AE:WORKSPACE_ACTIVITY:activity-1",
        "legacy_interaction_id": "interaction-1",
        "workspace_id": "workspace-1",
        "agent_execution_id": "execution-1",
        "execution_state": "SUCCEEDED",
        "execution_phase": "FINALIZE",
        "updated_at": "2026-11-08T01:00:00Z",
        "completed_at": "2026-11-08T01:00:00Z",
    }


def test_voucher_summary_is_typed_bounded_and_redacted() -> None:
    projected = _voucher_summary()

    schema = json.loads(
        (
            ROOT
            / "contracts/schemas/service/nex_ae_api/business_result_summary.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(projected)

    assert projected["result_type"] == "FINANCE.VOUCHER_DRAFT"
    assert projected["summary_schema_version"] == "ae_business_result_summary.v1"
    assert projected["summary"] == {
        "outcome": "COMMITTED",
        "verification_status": "VERIFIED",
        "approval_state": "APPROVED",
        "business_operation_id": "operation-1",
        "voucher_number": "voucher-1",
        "amount": "12500.00",
        "currency": "KRW",
        "account_codes": ["TRAVEL", "CASH"],
        "project_code": "NVT",
        "business_object_link": None,
    }
    encoded = json.dumps(projected)
    for private in ("tenant_id", "principal_id", "prompt", "raw_output"):
        assert private not in encoded


def test_unknown_type_is_generic_but_known_malformed_type_fails_closed() -> None:
    assert (
        admit_business_result_summary(
            {
                "result_type": "UNKNOWN.RESULT",
                "summary_schema_version": "unknown.v1",
                "summary": {"raw": "must-not-leak"},
            }
        )
        is None
    )
    malformed = _voucher_summary()
    malformed["summary"] = {**malformed["summary"], "prompt": "private"}  # type: ignore[index]
    with pytest.raises(BusinessResultSummaryError, match="fields"):
        admit_business_result_summary(malformed)


def test_optional_voucher_number_is_allowed_but_link_is_not_invented() -> None:
    summary = _voucher_summary(voucher_number=None, commit_state="NOT_COMMITTED")

    assert summary["summary"]["voucher_number"] is None  # type: ignore[index]
    assert summary["summary"]["business_object_link"] is None  # type: ignore[index]


def test_step_result_projection_rejects_conflicting_typed_summaries() -> None:
    first = {"result_payload": {"business_summary": _voucher_summary()}}
    second = {
        "result_payload": {
            "business_summary": _voucher_summary(project_code="OTHER")
        }
    }

    assert summary_from_step_results((first,)) == _voucher_summary()
    with pytest.raises(BusinessResultSummaryError, match="conflicting"):
        summary_from_step_results((first, second))


def test_plan_finalization_carries_only_admitted_business_summary() -> None:
    plan = _compiled()
    results = _step_results(plan=plan)
    terminal = plan["steps"][1]
    results[1] = build_step_result(
        step_result_id=results[1]["step_result_id"],
        execution_id=EXECUTION_ID,
        executable_plan_id=plan["executable_plan_id"],
        executable_step_id=terminal["executable_step_id"],
        compiled_step_key=terminal["compiled_step_key"],
        logical_step_ref=terminal["logical_step_ref"],
        attempt_no=1,
        status="SUCCEEDED",
        result_contract_ref=terminal["output_contract_ref"],
        result_payload={"business_summary": _voucher_summary()},
        started_at=NOW,
        completed_at=NOW,
    )
    verification = verify_plan_completion(
        executable_plan=plan,
        step_results=results,
    )

    result = build_plan_agent_result(
        execution=_execution(),
        executable_plan=plan,
        step_results=results,
        verification=verification,
        result_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
        created_at=NOW,
    )

    assert result["structured_result"]["business_summary"] == _voucher_summary()
    assert "result_payload" not in json.dumps(result)


def test_product_write_outcome_carries_source_backed_voucher_summary() -> None:
    result = SimpleNamespace(
        outcome=SimpleNamespace(
            commit_state=SimpleNamespace(value="COMMITTED"),
            result=SimpleNamespace(
                business_reference="eos.voucher_draft:voucher-2026-001"
            ),
        ),
        verification=SimpleNamespace(status=SimpleNamespace(value="VERIFIED")),
        write_request=SimpleNamespace(idempotency_key="idem-1"),
    )

    outcome = _controlled_write_outcome(
        result,
        business_operation_id="operation-1",
        business_result_seed={
            "amount": "12500.00",
            "currency": "KRW",
            "account_codes": ["TRAVEL", "CASH"],
            "project_code": "NVT",
        },
    )

    assert outcome.result_payload["business_summary"]["summary"] == {
        **_voucher_summary(voucher_number="voucher-2026-001")["summary"],
        "voucher_number": "voucher-2026-001",
    }


def test_owner_projection_exposes_only_admitted_summary() -> None:
    projected = _interaction_result_projection(_projection_row(_voucher_summary()))

    assert projected["result"]["business_summary"] == _voucher_summary()
    assert projected["metadata"] == {
        "owner_scope_authority": "claim",
        "raw_result_included": False,
        "prompt_included": False,
    }
    assert "result_envelope_json" not in json.dumps(projected)


def test_owner_projection_omits_unknown_type_and_rejects_tampered_known_type() -> None:
    unknown = _interaction_result_projection(
        _projection_row(
            {
                "result_type": "UNKNOWN.RESULT",
                "summary_schema_version": "unknown.v1",
                "summary": {"private": "hidden"},
            }
        )
    )
    assert unknown["result"]["business_summary"] is None

    malformed = _voucher_summary()
    malformed["summary"] = {"amount": "1.00"}
    with pytest.raises(WorkspaceResultPublicationError) as caught:
        _interaction_result_projection(_projection_row(malformed))
    assert caught.value.error_code == "ae.interaction_agent_result_record_invalid"
