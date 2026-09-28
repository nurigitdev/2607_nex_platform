from copy import deepcopy

import pytest

from nex_ae_api.citation_quality_workflow import (
    AeCitationQualityWorkflowError,
    build_citation_quality_workflow,
    build_grounded_response_quality_contract,
    validate_citation_quality_workflow,
)


def cx_generation_record(
    *,
    quality_status: str = "PASS",
    citation_status: str = "VALIDATED",
    issue_count: int = 0,
    grounding_required: bool = True,
    attempted: bool = False,
) -> dict:
    repair = {
        "repair_schema_version": "cx_citation_repair.v1",
        "attempted": attempted,
        "attempt_count": 1 if attempted else 0,
        "max_attempts": 1,
        "trigger_error_code": "cx.citation_required_missing" if attempted else None,
        "same_retrieval_package": True,
        "original_provider_prompt_package_hash": "a" * 64,
        "effective_provider_prompt_package_hash": (
            "b" * 64 if attempted else "a" * 64
        ),
        "invalid_output_included": False,
    }
    return {
        "cx_generation_id": "cx-generation-001",
        "request_metadata": {
            "grounding_required": grounding_required,
            "retrieval_package_id": "retrieval-001" if grounding_required else None,
            "retrieval_package_hash": "c" * 64 if grounding_required else None,
            "structured_draft_id": "draft-001" if grounding_required else None,
            "draft_validation_status": citation_status,
            "grounded_response_quality_audit_schema_version": (
                "cx_grounded_response_citation_quality_audit.v1"
            ),
            "grounded_response_quality_status": quality_status,
            "grounded_response_quality_issue_count": issue_count,
            "citation_repair": repair,
            "raw_output": "must not escape",
            "evidence_text": "must not escape",
        },
    }


def workflow(**kwargs) -> dict:
    return build_citation_quality_workflow(
        cx_generation_record(**kwargs),
        interaction_id="interaction-001",
    )


def test_workflow_projects_validated_generation_without_private_content() -> None:
    projection = workflow()

    assert projection["workflow_status"] == "VALIDATED"
    assert projection["next_action"] == "PRESENT_RESPONSE"
    assert projection["quality"]["boundary_status"] == "PASS"
    assert projection["repair"]["status"] == "NOT_ATTEMPTED"
    assert projection["operator_remediation"] == {
        "mode": "SEPARATE_HANDOFF",
        "required": False,
        "handoff_included": False,
    }
    assert projection["owner_scope_enforced"] is True
    assert "must not escape" not in str(projection)


def test_workflow_projects_successful_bounded_inline_repair() -> None:
    projection = workflow(attempted=True)

    assert projection["workflow_status"] == "REPAIRED"
    assert projection["next_action"] == "PRESENT_REPAIRED_RESPONSE"
    assert projection["repair"]["mode"] == "BOUNDED_INLINE"
    assert projection["repair"]["status"] == "SUCCEEDED"
    assert projection["repair"]["attempt_count"] == 1
    assert projection["repair"]["same_retrieval_package"] is True


@pytest.mark.parametrize("quality_status", ["WARN", "FAIL", "UNKNOWN"])
def test_workflow_routes_nonpassing_quality_to_separate_remediation(
    quality_status: str,
) -> None:
    projection = workflow(
        quality_status=quality_status,
        citation_status="INVALID",
        issue_count=1,
        attempted=True,
    )

    assert projection["workflow_status"] == "ATTENTION_REQUIRED"
    assert projection["next_action"] == "RETRY_OR_REVIEW_GENERATION"
    assert projection["repair"]["status"] == "ATTENTION_REQUIRED"
    assert projection["operator_remediation"]["required"] is True


def test_workflow_projects_not_required_and_legacy_missing_repair() -> None:
    record = cx_generation_record(
        grounding_required=False,
        quality_status="NOT_REQUIRED",
        citation_status="NOT_REQUIRED",
    )
    record["request_metadata"].pop("citation_repair")
    projection = build_citation_quality_workflow(
        record,
        interaction_id="interaction-legacy",
        cx_generation_id="cx-generation-explicit",
    )

    assert projection["workflow_status"] == "NOT_REQUIRED"
    assert projection["cx_generation_id"] == "cx-generation-explicit"
    assert projection["repair"] == {
        "source_projection_present": False,
        "repair_schema_version": None,
        "mode": "NONE",
        "status": "NOT_ATTEMPTED",
        "attempted": False,
        "attempt_count": 0,
        "max_attempts": 1,
        "trigger_error_code": None,
        "same_retrieval_package": None,
        "original_provider_prompt_package_hash": None,
        "effective_provider_prompt_package_hash": None,
        "invalid_output_included": False,
    }


def test_quality_contract_preserves_sparse_legacy_mapping() -> None:
    quality = build_grounded_response_quality_contract(
        {
            "request_metadata": {
                "grounding_required": True,
                "grounded_response_quality_issue_count": True,
                "retrieval_package_hash": "invalid",
            }
        }
    )
    not_required = build_grounded_response_quality_contract({})

    assert quality["boundary_status"] == "UNKNOWN"
    assert quality["citation_status"] == "UNKNOWN"
    assert quality["issue_count"] == 0
    assert quality["retrieval_package_hash"] is None
    assert quality["recommended_action"] == "proceed_with_caveat"
    assert not_required["boundary_status"] == "NOT_REQUIRED"
    assert not_required["citation_status"] == "NOT_REQUIRED"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("extra",), True),
        (("workflow_schema_version",), "old"),
        (("interaction_id",), " "),
        (("quality", "boundary_status"), "MAYBE"),
        (("quality", "citation_status"), "MAYBE"),
        (("quality", "issue_count"), True),
        (("quality", "grounding_required"), "yes"),
        (("quality", "recommended_action"), "show_error"),
        (("quality", "raw_output_included"), True),
        (("quality", "retrieval_package_hash"), "bad"),
        (("repair", "source_projection_present"), "yes"),
        (("repair", "repair_schema_version"), "old"),
        (("repair", "attempt_count"), 2),
        (("repair", "max_attempts"), 2),
        (("repair", "trigger_error_code"), "bad"),
        (("repair", "same_retrieval_package"), False),
        (("repair", "original_provider_prompt_package_hash"), "bad"),
        (("repair", "invalid_output_included"), True),
        (("operator_remediation", "mode"), "INLINE"),
        (("operator_remediation", "required"), "yes"),
        (("operator_remediation", "handoff_included"), True),
        (("workflow_status",), "REPAIRED"),
        (("next_action",), "PRESENT_REPAIRED_RESPONSE"),
        (("owner_scope_enforced",), False),
        (("content_included",), True),
    ],
)
def test_workflow_validator_rejects_invalid_mutations(
    path: tuple[str, ...], value: object
) -> None:
    candidate = deepcopy(workflow())
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(AeCitationQualityWorkflowError):
        validate_citation_quality_workflow(candidate)


def test_workflow_rejects_invalid_inputs_and_absent_projection_drift() -> None:
    with pytest.raises(AeCitationQualityWorkflowError):
        build_citation_quality_workflow([], interaction_id="interaction")
    with pytest.raises(AeCitationQualityWorkflowError):
        build_citation_quality_workflow({}, interaction_id=" ")
    with pytest.raises(AeCitationQualityWorkflowError):
        build_grounded_response_quality_contract([])

    candidate = workflow(grounding_required=False, quality_status="NOT_REQUIRED")
    candidate["repair"] = {
        **candidate["repair"],
        "source_projection_present": False,
    }
    with pytest.raises(AeCitationQualityWorkflowError):
        validate_citation_quality_workflow(candidate)


def test_workflow_rejects_unattempted_hash_drift() -> None:
    record = cx_generation_record()
    record["request_metadata"]["citation_repair"][
        "effective_provider_prompt_package_hash"
    ] = "d" * 64

    with pytest.raises(AeCitationQualityWorkflowError):
        build_citation_quality_workflow(record, interaction_id="interaction")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repair", "status"), "SUCCEEDED"),
        (("operator_remediation", "required"), True),
        (("quality",), {}),
        (("quality", "contract_schema_version"), "old"),
        (("quality", "source_audit_schema_version"), " "),
        (("repair",), {}),
        (("operator_remediation",), {}),
    ],
)
def test_workflow_validator_covers_nested_contract_failures(
    path: tuple[str, ...], value: object
) -> None:
    candidate = deepcopy(workflow())
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(AeCitationQualityWorkflowError):
        validate_citation_quality_workflow(candidate)


def test_workflow_rejects_nonmapping_cx_repair_and_exposes_stable_error() -> None:
    record = cx_generation_record()
    record["request_metadata"]["citation_repair"] = []

    with pytest.raises(AeCitationQualityWorkflowError) as captured:
        build_citation_quality_workflow(record, interaction_id="interaction")

    assert captured.value.error_code == "ae.citation_quality_workflow.invalid"
    assert str(captured.value) == captured.value.detail
