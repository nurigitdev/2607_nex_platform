from __future__ import annotations

import pytest

from nex_ag.remediation_runtime_audit import (
    AG_OWNER_SERVICE,
    AG_REMEDIATION_RUNTIME_OPERATIONS_GAP_AUDIT_VERSION,
    CX_OWNER_SERVICE,
    RemediationRuntimeAuditError,
    build_remediation_runtime_operations_gap_audit,
    find_sensitive_remediation_runtime_audit_keys,
    validate_remediation_runtime_operations_gap_audit,
)


def test_remediation_runtime_audit_freezes_next_operations_gaps() -> None:
    audit = build_remediation_runtime_operations_gap_audit()

    assert audit["audit_schema_version"] == (
        AG_REMEDIATION_RUNTIME_OPERATIONS_GAP_AUDIT_VERSION
    )
    assert audit["slice_id"] == "0371"
    assert [gap["target_slice"] for gap in audit["operations_gaps"]] == [
        "0372",
        "0373",
        "0374",
        "0375",
        "0376",
        "0377",
    ]
    assert audit["operations_gaps"][0] == {
        "gap_id": "ag_remediation_execution_operations_projection",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0372",
        "decision": "required_before_operations_api",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    }
    assert audit["operations_gaps"][-1]["postgres_smoke_required"] is True
    assert audit["boundary_policy"] == {
        "ag_runtime_role": "owns_operator_state_operations_and_status_sync",
        "cx_runtime_role": "owns_execution_attempts_and_repair_lineage",
        "ae_runtime_role": "owns_user_visible_repaired_response_surface",
        "mo_runtime_role": "owns_model_provider_execution",
        "ag_may_update_task_state": True,
        "ag_may_mutate_cx_execution_records": False,
        "cx_may_mutate_ag_task_records": False,
        "ag_operations_projection_is_read_only": True,
        "remote_provider_required_for_slices_0371_0377": False,
    }
    assert [item["slice_id"] for item in audit["recommended_slices"]] == [
        "0372",
        "0373",
        "0374",
        "0375",
        "0376",
        "0377",
    ]
    assert audit["redaction_summary"] == {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "raw_evidence_included": False,
    }


def test_remediation_runtime_audit_accepts_safe_redaction_false_keys() -> None:
    audit = build_remediation_runtime_operations_gap_audit(
        include_deferred_scope=False
    )

    assert "deferred_scope" not in audit
    assert find_sensitive_remediation_runtime_audit_keys(audit) == []


def test_remediation_runtime_audit_records_s37_prerequisites() -> None:
    audit = build_remediation_runtime_operations_gap_audit()
    closed_by_slice = {
        item["evidence_slice"]: item for item in audit["closed_capabilities"]
    }

    assert closed_by_slice["0354"]["owner_service"] == CX_OWNER_SERVICE
    assert closed_by_slice["0364"]["owner_service"] == AG_OWNER_SERVICE
    assert closed_by_slice["0369"]["capability_id"] == (
        "ag_remediation_execution_status_sync_api"
    )
    assert closed_by_slice["0370"]["runtime_surface"] == (
        "run_s37_remediation_runtime_integration_closure"
    )


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"audit_schema_version": "bad"},
            "ag.remediation_runtime_audit.schema_version_invalid",
        ),
        (
            {"status": "draft"},
            "ag.remediation_runtime_audit.status_invalid",
        ),
        (
            {
                "operations_gaps": [
                    {
                        "gap_id": "bad",
                        "owner_service": AG_OWNER_SERVICE,
                        "target_slice": "0372",
                        "decision": "bad",
                    }
                ]
            },
            "ag.remediation_runtime_audit.next_slices_invalid",
        ),
        (
            {
                "operations_gaps": [
                    {
                        "gap_id": f"gap-{number}",
                        "owner_service": CX_OWNER_SERVICE if number == 377 else AG_OWNER_SERVICE,
                        "target_slice": f"{number:04d}",
                        "decision": "bad",
                    }
                    for number in range(372, 378)
                ]
            },
            "ag.remediation_runtime_audit.gap_owner_invalid",
        ),
        (
            {
                "recommended_slices": [
                    {
                        "slice_id": "0372",
                        "gap_id": "wrong",
                        "decision": "wrong",
                    }
                ]
            },
            "ag.remediation_runtime_audit.recommended_slices_invalid",
        ),
        (
            {
                "boundary_policy": {
                    "ag_runtime_role": "owns_operator_state_operations_and_status_sync"
                }
            },
            "ag.remediation_runtime_audit.boundary_policy_invalid",
        ),
        (
            {"safe_debug_contract": {"raw_content_included": True}},
            "ag.remediation_runtime_audit.raw_content_policy_invalid",
        ),
        (
            {
                "safe_debug_contract": {
                    "raw_content_included": False,
                    "credential_material_included": True,
                }
            },
            "ag.remediation_runtime_audit.credential_policy_invalid",
        ),
        (
            {"closed_capabilities": []},
            "ag.remediation_runtime_audit.closed_capabilities_invalid",
        ),
        (
            {"redaction_summary": {"raw_prompt_included": True}},
            "ag.remediation_runtime_audit.redaction_summary_invalid",
        ),
    ],
)
def test_remediation_runtime_audit_rejects_invalid_shapes(
    override: dict[str, object],
    error_code: str,
) -> None:
    audit = build_remediation_runtime_operations_gap_audit()
    audit.update(override)

    with pytest.raises(RemediationRuntimeAuditError) as exc_info:
        validate_remediation_runtime_operations_gap_audit(audit)

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_remediation_runtime_audit_rejects_redaction_summary_truthy_after_safe_keys() -> None:
    audit = build_remediation_runtime_operations_gap_audit()
    audit["redaction_summary"] = {"safe_flag": True}

    with pytest.raises(RemediationRuntimeAuditError) as exc_info:
        validate_remediation_runtime_operations_gap_audit(audit)

    assert exc_info.value.error_code == (
        "ag.remediation_runtime_audit.redaction_summary_invalid"
    )


def test_remediation_runtime_audit_rejects_non_sequence_gaps() -> None:
    audit = build_remediation_runtime_operations_gap_audit()
    audit["operations_gaps"] = "bad"

    with pytest.raises(RemediationRuntimeAuditError) as exc_info:
        validate_remediation_runtime_operations_gap_audit(audit)

    assert exc_info.value.error_code == (
        "ag.remediation_runtime_audit.next_slices_invalid"
    )


def test_remediation_runtime_audit_rejects_sensitive_debug_payload_after_policy_checks() -> None:
    audit = build_remediation_runtime_operations_gap_audit()
    audit["debug"] = {"provider_api_key": "do-not-store"}

    with pytest.raises(RemediationRuntimeAuditError) as exc_info:
        validate_remediation_runtime_operations_gap_audit(audit)

    assert exc_info.value.error_code == "ag.remediation_runtime_audit.sensitive_payload"


def test_remediation_runtime_audit_detects_nested_sensitive_payload_values() -> None:
    payload = {
        "safe": {"raw_prompt_included": False},
        "debug": [{"provider_api_key": "do-not-store"}],
        "nested": {"database_url": "postgresql://example"},
    }

    assert find_sensitive_remediation_runtime_audit_keys(payload) == [
        "debug[0].provider_api_key",
        "nested.database_url",
    ]
