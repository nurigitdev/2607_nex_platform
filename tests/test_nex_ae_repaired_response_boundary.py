from __future__ import annotations

import pytest

from nex_ae_api.repaired_response_boundary import (
    AE_HANDOFF_OWNER_SERVICE,
    AE_REPAIRED_RESPONSE_RUNTIME_BOUNDARY_DECISION_VERSION,
    AE_WEB_RESULT_SURFACE_OWNER_SERVICE,
    AG_REMEDIATION_ORCHESTRATION_OWNER_SERVICE,
    CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REMEDIATION_LINEAGE_OWNER_SERVICE,
    CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
    FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS,
    RAW_CONTENT_POLICY,
    REPAIRED_RESPONSE_HANDOFF_ROUTES,
    RepairedResponseRuntimeBoundaryError,
    assert_repaired_response_runtime_boundary_redaction_safe,
    build_repaired_response_runtime_boundary_decision,
    find_sensitive_repaired_response_runtime_boundary_keys,
    validate_repaired_response_runtime_boundary_decision,
)


def test_repaired_response_runtime_boundary_assigns_owner_services() -> None:
    decision = validate_repaired_response_runtime_boundary_decision(
        build_repaired_response_runtime_boundary_decision()
    )

    assert decision["decision_schema_version"] == (
        AE_REPAIRED_RESPONSE_RUNTIME_BOUNDARY_DECISION_VERSION
    )
    assert decision["owner_services"] == {
        "repaired_response_handoff": AE_HANDOFF_OWNER_SERVICE,
        "user_visible_result_surface": AE_WEB_RESULT_SURFACE_OWNER_SERVICE,
        "remediation_lineage_source": CX_REMEDIATION_LINEAGE_OWNER_SERVICE,
        "remediation_task_orchestration": AG_REMEDIATION_ORCHESTRATION_OWNER_SERVICE,
    }
    assert decision["route_scope"] == {
        "routes": REPAIRED_RESPONSE_HANDOFF_ROUTES,
        "runtime_route_wiring_status": "deferred_to_0384",
        "client_adapter_status": "deferred_to_0382",
        "persistence_status": "deferred_to_0383",
    }


def test_repaired_response_runtime_boundary_freezes_source_contract() -> None:
    decision = validate_repaired_response_runtime_boundary_decision(
        build_repaired_response_runtime_boundary_decision()
    )

    assert decision["source_contract"] == {
        "required_cx_detail_schema_version": (
            CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
        ),
        "required_lineage_schema_version": (
            CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION
        ),
        "required_generation_record_schema_version": (
            CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION
        ),
        "required_execution_status": "SUCCEEDED",
        "required_lineage_status": "LINKED",
        "required_repaired_generation_status": "COMPLETED",
        "parent_generation_mutated": False,
        "lineage_consistent": True,
    }


def test_repaired_response_runtime_boundary_freezes_storage_policy() -> None:
    decision = validate_repaired_response_runtime_boundary_decision(
        build_repaired_response_runtime_boundary_decision()
    )
    storage = decision["storage_contract"]

    assert storage["system_of_record"] == "nex-ae-api"
    assert storage["table_candidate"] == "ae_repaired_response_handoffs"
    assert "output_hash" in storage["safe_fields"]
    assert "output_preview" in storage["safe_fields"]
    assert "raw_generation_output" not in storage["safe_fields"]
    assert tuple(storage["forbidden_fields"]) == (
        FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
    )
    assert storage["raw_content_policy"] == RAW_CONTENT_POLICY


def test_repaired_response_runtime_boundary_error_string_is_detail() -> None:
    error = RepairedResponseRuntimeBoundaryError(
        error_code="ae.repaired_response_boundary.test",
        detail="Readable repaired response boundary failure.",
    )

    assert str(error) == "Readable repaired response boundary failure."


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"decision_schema_version": "bad"},
            "ae.repaired_response_boundary.schema_version_invalid",
        ),
        (
            {"owner_services": {"repaired_response_handoff": "nex-cx"}},
            "ae.repaired_response_boundary.owner_services_invalid",
        ),
        (
            {
                "route_scope": {
                    "routes": {"create": "/wrong"},
                    "runtime_route_wiring_status": "deferred_to_0384",
                }
            },
            "ae.repaired_response_boundary.route_scope_invalid",
        ),
        (
            {
                "source_contract": {
                    "required_cx_detail_schema_version": "bad",
                    "parent_generation_mutated": False,
                    "lineage_consistent": True,
                }
            },
            "ae.repaired_response_boundary.source_contract_invalid",
        ),
        (
            {
                "storage_contract": {
                    "handoff_contract_version": "ae_repaired_response_handoff.v1",
                    "system_of_record": "nex-cx",
                    "safe_fields": ["output_hash"],
                    "forbidden_fields": list(
                        FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
                    ),
                    "raw_content_policy": RAW_CONTENT_POLICY,
                }
            },
            "ae.repaired_response_boundary.storage_contract_invalid",
        ),
        (
            {
                "storage_contract": {
                    "handoff_contract_version": "bad",
                    "system_of_record": "nex-ae-api",
                    "safe_fields": ["output_hash"],
                    "forbidden_fields": list(
                        FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
                    ),
                    "raw_content_policy": RAW_CONTENT_POLICY,
                }
            },
            "ae.repaired_response_boundary.storage_contract_invalid",
        ),
        (
            {
                "storage_contract": {
                    "handoff_contract_version": "ae_repaired_response_handoff.v1",
                    "system_of_record": "nex-ae-api",
                    "safe_fields": ["output_hash", "raw_output"],
                    "forbidden_fields": list(
                        FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
                    ),
                    "raw_content_policy": RAW_CONTENT_POLICY,
                }
            },
            "ae.repaired_response_boundary.safe_field_sensitive",
        ),
        (
            {
                "storage_contract": {
                    "handoff_contract_version": "ae_repaired_response_handoff.v1",
                    "system_of_record": "nex-ae-api",
                    "safe_fields": ["output_hash"],
                    "forbidden_fields": list(
                        FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
                    ),
                    "raw_content_policy": {
                        **RAW_CONTENT_POLICY,
                        "raw_generation_output_stored": True,
                    },
                }
            },
            "ae.repaired_response_boundary.raw_content_policy_invalid",
        ),
        (
            {
                "storage_contract": {
                    "handoff_contract_version": "ae_repaired_response_handoff.v1",
                    "system_of_record": "nex-ae-api",
                    "safe_fields": ["output_hash"],
                    "forbidden_fields": ["raw_prompt"],
                    "raw_content_policy": RAW_CONTENT_POLICY,
                }
            },
            "ae.repaired_response_boundary.forbidden_fields_incomplete",
        ),
        (
            {
                "mutation_policy": {
                    "original_chat_interaction_mutated": True,
                    "original_cx_generation_record_mutated": False,
                }
            },
            "ae.repaired_response_boundary.mutation_policy_invalid",
        ),
        (
            {
                "refactoring_checkpoint": {
                    "external_api_changed": True,
                    "database_schema_changed": False,
                    "remote_provider_required": False,
                    "postgres_smoke_required": False,
                    "runtime_route_changed": False,
                }
            },
            "ae.repaired_response_boundary.refactoring_checkpoint_invalid",
        ),
        (
            {"next_slices": {"0382": "only one slice"}},
            "ae.repaired_response_boundary.next_slices_invalid",
        ),
    ],
)
def test_repaired_response_runtime_boundary_rejects_invalid_shapes(
    override: dict[str, object],
    error_code: str,
) -> None:
    decision = build_repaired_response_runtime_boundary_decision()
    decision.update(override)

    with pytest.raises(RepairedResponseRuntimeBoundaryError) as exc_info:
        validate_repaired_response_runtime_boundary_decision(decision)

    assert exc_info.value.error_code == error_code


def test_repaired_response_runtime_boundary_rejects_bad_route_status() -> None:
    decision = build_repaired_response_runtime_boundary_decision()
    decision["route_scope"]["runtime_route_wiring_status"] = "enabled_now"

    with pytest.raises(RepairedResponseRuntimeBoundaryError) as exc_info:
        validate_repaired_response_runtime_boundary_decision(decision)

    assert exc_info.value.error_code == (
        "ae.repaired_response_boundary.route_scope_invalid"
    )


def test_repaired_response_runtime_boundary_rejects_bad_free_text_policy() -> None:
    decision = build_repaired_response_runtime_boundary_decision()
    decision["storage_contract"]["raw_content_policy"] = {
        **RAW_CONTENT_POLICY,
        "free_text_storage": "store_full_text",
    }

    with pytest.raises(RepairedResponseRuntimeBoundaryError) as exc_info:
        validate_repaired_response_runtime_boundary_decision(decision)

    assert exc_info.value.error_code == (
        "ae.repaired_response_boundary.raw_content_policy_invalid"
    )


def test_repaired_response_runtime_boundary_redaction_guard_accepts_safe_flags() -> None:
    payload = {
        "output_hash": "a" * 64,
        "output_preview": "Repaired response preview.",
        "redaction_summary": {
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "provider_endpoint_stored": False,
            "credential_material_stored": False,
            "local_storage_path_stored": False,
        },
    }

    assert find_sensitive_repaired_response_runtime_boundary_keys(payload) == []
    assert_repaired_response_runtime_boundary_redaction_safe(payload)


def test_repaired_response_runtime_boundary_redaction_guard_reports_nested_keys() -> None:
    payload = {
        "metadata": {
            "raw_prompt_stored": False,
            "raw_prompt": "do not store",
            "provider": {"provider_url": "http://provider.local"},
        },
        "events": [{"storage_path": "/data/nex-platform/cx/source-files/a.bin"}],
    }

    assert find_sensitive_repaired_response_runtime_boundary_keys(payload) == [
        "metadata.raw_prompt",
        "metadata.provider.provider_url",
        "events[0].storage_path",
    ]
    with pytest.raises(RepairedResponseRuntimeBoundaryError) as exc_info:
        assert_repaired_response_runtime_boundary_redaction_safe(payload)

    assert exc_info.value.error_code == (
        "ae.repaired_response_runtime_boundary_payload.sensitive_key"
    )


def test_repaired_response_runtime_boundary_redaction_guard_rejects_true_flag() -> None:
    payload = {
        "output_hash": "a" * 64,
        "redaction_summary": {"raw_generation_output_stored": True},
    }

    assert find_sensitive_repaired_response_runtime_boundary_keys(payload) == [
        "redaction_summary.raw_generation_output_stored"
    ]
    with pytest.raises(RepairedResponseRuntimeBoundaryError) as exc_info:
        assert_repaired_response_runtime_boundary_redaction_safe(payload)

    assert exc_info.value.error_code == (
        "ae.repaired_response_runtime_boundary_payload.sensitive_key"
    )
