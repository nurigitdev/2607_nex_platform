from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import validate_contracts


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def minimal_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }


def minimal_openapi() -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "0.0.0"},
        "paths": {},
    }


def build_contract_fixture(root: Path) -> None:
    write_json(root / "schemas" / "common" / "sample.v1.schema.json", minimal_schema())
    write_json(root / "examples" / "sample.json", {"name": "valid"})
    write_json(
        root / "examples" / "index.json",
        {
            "examples": [
                {
                    "name": "sample",
                    "path": "examples/sample.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )
    write_json(root / "tests" / "negative" / "sample.invalid.json", {})
    write_json(
        root / "tests" / "negative" / "index.json",
        {
            "negative_examples": [
                {
                    "name": "sample_invalid",
                    "path": "tests/negative/sample.invalid.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )
    write_yaml(root / "openapi" / "sample.openapi.yaml", minimal_openapi())


def test_validate_contract_tree_accepts_valid_contract_package(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert summary.ok
    assert summary.schema_count == 1
    assert summary.example_count == 1
    assert summary.negative_example_count == 1
    assert summary.openapi_count == 1


def test_validate_contract_tree_reports_invalid_example(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "sample.json", {"unexpected": "value"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert summary.example_count == 0
    assert "examples/sample.json" in summary.failures[0]


def test_validate_contract_tree_reports_bad_example_index(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "index.json", {"examples": "not-a-list"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "examples/index.json" in summary.failures[0]


def test_validate_contract_tree_reports_missing_index_keys(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "index.json", {"examples": [{"path": "x"}]})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "missing key" in summary.failures[0]


def test_validate_contract_tree_reports_invalid_openapi(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_yaml(tmp_path / "openapi" / "sample.openapi.yaml", {"openapi": "3.1.0"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "invalid OpenAPI spec" in summary.failures[0]


def test_validate_contract_tree_reports_negative_fixture_that_validates(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "tests" / "negative" / "sample.invalid.json", {"name": "valid"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "negative example validated" in summary.failures[0]


def test_validate_contract_tree_reports_bad_negative_index(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {"negative_examples": "not-a-list"},
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "tests/negative/index.json" in summary.failures[0]


def test_validate_contract_tree_reports_missing_negative_index_keys(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {"negative_examples": [{"path": "x"}]},
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "missing key" in summary.failures[0]


def test_validate_contract_tree_reports_unreadable_negative_fixture(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {
            "negative_examples": [
                {
                    "name": "missing",
                    "path": "tests/negative/missing.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "tests/negative/missing.json" in summary.failures[0]


def test_iter_openapi_files_handles_missing_directory(tmp_path: Path) -> None:
    assert validate_contracts.iter_openapi_files(tmp_path) == []


def test_nex_ag_operations_contract_includes_cx_processing_projections() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "service"
        / "nex_ag"
        / "operations_projection.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    projection_versions = schema["properties"]["projection_schema_version"]["enum"]
    run_def = schema["$defs"]["cx_processing_run_operation"]
    step_def = schema["$defs"]["cx_processing_step_operation"]

    assert "ag_cx_processing_run_operations_projection.v1" in projection_versions
    assert "ag_cx_processing_run_detail_projection.v1" in projection_versions
    assert schema["properties"]["processing_runs"]["items"]["$ref"] == (
        "#/$defs/cx_processing_run_operation"
    )
    assert schema["properties"]["processing_run"]["$ref"] == (
        "#/$defs/cx_processing_run_operation"
    )
    assert run_def["additionalProperties"] is False
    assert step_def["additionalProperties"] is False
    assert {"error_detail"} in [
        set(rule["required"])
        for rule in step_def["not"]["anyOf"]
        if "required" in rule
    ]


def test_nex_ag_operations_contract_hardens_retrieval_threshold_decisions() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "service"
        / "nex_ag"
        / "operations_projection.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    projection_versions = schema["properties"]["projection_schema_version"]["enum"]
    required_by_projection = {
        clause["if"]["properties"]["projection_schema_version"]["const"]: set(
            clause["then"]["required"]
        )
        for clause in schema["allOf"]
        if "const" in clause.get("if", {})
        .get("properties", {})
        .get("projection_schema_version", {})
    }
    decision_def = schema["$defs"]["retrieval_threshold_decision_operation"]
    decision_properties = decision_def["properties"]
    operator_review_def = schema["$defs"]["retrieval_threshold_operator_review"]
    closure_def = schema["$defs"]["retrieval_threshold_calibration_closure"]

    assert "ag_retrieval_score_calibration_rollup_projection.v1" in projection_versions
    assert "ag_retrieval_threshold_decision_projection.v1" in projection_versions
    assert required_by_projection[
        "ag_retrieval_score_calibration_rollup_projection.v1"
    ] == {
        "projection_status",
        "filters",
        "calibration_samples",
        "summary",
        "source_statuses",
        "pagination",
    }
    assert required_by_projection[
        "ag_retrieval_threshold_decision_projection.v1"
    ] == {
        "projection_status",
        "filters",
        "threshold_decisions",
        "summary",
        "closure",
        "source_statuses",
    }
    assert schema["$defs"]["dashboard_retrieval_threshold_decisions"]["properties"][
        "summary"
    ]["$ref"] == "#/$defs/retrieval_threshold_decision_summary"
    assert schema["$defs"]["retrieval_score_calibration_summary"]["properties"][
        "score_margin_to_default_threshold"
    ]["$ref"] == "#/$defs/score_margin_range"
    assert decision_properties["policy_status"]["enum"] == [
        "ACTIVE",
        "CANDIDATE",
        "RETIRED",
    ]
    assert decision_properties["decision_status"]["enum"] == [
        "UNSPECIFIED",
        "OBSERVE",
        "ADOPT",
        "REJECT",
    ]
    assert decision_properties["recommended_operator_action"]["enum"] == [
        "repair_retrieval_operations_source",
        "register_threshold_decision",
        "collect_live_score_samples",
        "review_threshold_override_samples",
        "review_low_confidence_samples",
        "prepare_threshold_policy_review",
    ]
    assert "operator_review" in decision_def["required"]
    assert decision_properties["operator_review"]["$ref"] == (
        "#/$defs/retrieval_threshold_operator_review"
    )
    assert operator_review_def["additionalProperties"] is False
    assert operator_review_def["properties"]["review_schema_version"]["const"] == (
        "ag_retrieval_threshold_operator_review.v1"
    )
    assert operator_review_def["properties"]["review_status"]["enum"] == [
        "BLOCKED_SOURCE",
        "MISSING_CHECKPOINT",
        "COLLECTING_SAMPLES",
        "REVIEW_REQUIRED",
        "READY_FOR_POLICY_REVIEW",
        "UNKNOWN_ACTION",
    ]
    assert schema["properties"]["closure"]["$ref"] == (
        "#/$defs/retrieval_threshold_calibration_closure"
    )
    assert closure_def["additionalProperties"] is False
    assert closure_def["properties"]["closure_schema_version"]["const"] == (
        "ag_retrieval_threshold_calibration_closure.v1"
    )
    assert closure_def["properties"]["closure_status"]["enum"] == [
        "NO_DECISIONS",
        "BLOCKED",
        "COLLECTING_SAMPLES",
        "OPERATOR_REVIEW_REQUIRED",
        "READY_FOR_POLICY_REVIEW",
    ]
    assert schema["$defs"]["dashboard_retrieval_threshold_decisions"]["properties"][
        "closure"
    ]["$ref"] == "#/$defs/retrieval_threshold_calibration_closure"


def test_nex_ag_openapi_includes_worker_and_service_log_contracts() -> None:
    openapi_path = (
        Path(__file__).parents[1] / "contracts" / "openapi" / "nex-ag.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    worker_detail = spec["paths"]["/admin/v1/operations/workers/{service_id}/{worker_id}"]["get"]
    service_logs = spec["paths"]["/admin/v1/operations/logs"]["get"]
    service_log_policy = spec["paths"]["/admin/v1/operations/logs/policy"]["get"]
    service_log_retention = spec["paths"][
        "/admin/v1/operations/logs/retention/dry-run"
    ]["get"]
    service_log_retention_purge = spec["paths"][
        "/admin/v1/operations/logs/retention/{service_id}/purge"
    ]["post"]
    service_log_detail = spec["paths"]["/admin/v1/operations/logs/{log_id}"]["get"]
    processing_runs = spec["paths"]["/admin/v1/operations/cx-processing-runs"]["get"]
    processing_run_detail = spec["paths"][
        "/admin/v1/operations/cx-processing-runs/{pipeline_run_id}"
    ]["get"]
    parameter_names = {parameter["name"] for parameter in worker_detail["parameters"]}
    parameters = spec["components"]["parameters"]
    service_log_query_names = {
        parameters[parameter["$ref"].rsplit("/", 1)[-1]]["name"]
        if "$ref" in parameter
        else parameter["name"]
        for parameter in service_logs["parameters"]
    }
    processing_run_query_names = {
        parameters[parameter["$ref"].rsplit("/", 1)[-1]]["name"]
        if "$ref" in parameter
        else parameter["name"]
        for parameter in processing_runs["parameters"]
    }
    projection_versions = spec["components"]["schemas"]["AgOperationsProjection"][
        "properties"
    ]["projection_schema_version"]["enum"]

    assert worker_detail["operationId"] == "getAgWorkerDetailProjection"
    assert parameter_names == {
        "service_id",
        "worker_id",
        "stale_after_seconds",
        "event_limit",
    }
    assert "ag_worker_runtime_projection.v1" in projection_versions
    assert "ag_worker_detail_projection.v1" in projection_versions
    assert service_logs["operationId"] == "getAgServiceLogProjection"
    assert (
        service_log_policy["operationId"]
        == "getAgServiceLogQueryPolicyProjection"
    )
    assert (
        service_log_retention["operationId"]
        == "getAgServiceLogRetentionDryRunProjection"
    )
    assert (
        service_log_retention_purge["operationId"]
        == "purgeAgServiceLogRetention"
    )
    assert service_log_detail["operationId"] == "getAgServiceLogDetailProjection"
    assert {
        "service_id",
        "severity",
        "logger_name",
        "trace_id",
        "request_id",
        "job_id",
        "subject_type",
        "subject_id",
        "q",
        "since",
        "until",
        "sort",
        "cursor",
        "limit",
    } == service_log_query_names
    assert "ag_service_log_projection.v1" in projection_versions
    assert "ag_service_log_detail_projection.v1" in projection_versions
    assert "ag_service_log_query_policy_projection.v1" in projection_versions
    assert "ag_service_log_retention_dry_run_projection.v1" in projection_versions
    assert "ag_service_log_retention_dispatch.v1" in projection_versions
    assert (
        processing_runs["operationId"]
        == "getAgCxProcessingRunOperationsProjection"
    )
    assert (
        processing_run_detail["operationId"]
        == "getAgCxProcessingRunDetailProjection"
    )
    assert {
        "service_id",
        "document_id",
        "status",
        "trace_id",
        "request_id",
        "job_id",
        "include_steps",
        "since",
        "until",
        "sort",
        "cursor",
        "limit",
    } == processing_run_query_names
    assert "ag_cx_processing_run_operations_projection.v1" in projection_versions
    assert "ag_cx_processing_run_detail_projection.v1" in projection_versions


def test_nex_ag_openapi_includes_retrieval_calibration_and_decision_contracts() -> None:
    openapi_path = (
        Path(__file__).parents[1] / "contracts" / "openapi" / "nex-ag.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    parameters = spec["components"]["parameters"]

    score_calibration = spec["paths"][
        "/admin/v1/operations/retrieval-score-calibration"
    ]["get"]
    threshold_decisions = spec["paths"][
        "/admin/v1/operations/retrieval-threshold-decisions"
    ]["get"]
    calibration_query_names = {
        parameters[parameter["$ref"].rsplit("/", 1)[-1]]["name"]
        if "$ref" in parameter
        else parameter["name"]
        for parameter in score_calibration["parameters"]
    }
    threshold_query_names = {
        parameters[parameter["$ref"].rsplit("/", 1)[-1]]["name"]
        if "$ref" in parameter
        else parameter["name"]
        for parameter in threshold_decisions["parameters"]
    }
    projection_versions = spec["components"]["schemas"]["AgOperationsProjection"][
        "properties"
    ]["projection_schema_version"]["enum"]

    assert (
        score_calibration["operationId"]
        == "getAgRetrievalScoreCalibrationRollupProjection"
    )
    assert (
        threshold_decisions["operationId"]
        == "getAgRetrievalThresholdDecisionProjection"
    )
    assert calibration_query_names == {
        "service_id",
        "status",
        "trace_id",
        "request_id",
        "retrieval_policy_id",
        "calibration_action",
        "default_confidence_bucket",
        "threshold_override",
        "since",
        "until",
        "sort",
        "cursor",
        "limit",
    }
    assert threshold_query_names == {
        "service_id",
        "retrieval_policy_id",
        "since",
        "until",
        "sort",
        "cursor",
        "limit",
    }
    assert "ag_retrieval_score_calibration_rollup_projection.v1" in projection_versions
    assert "ag_retrieval_threshold_decision_projection.v1" in projection_versions


def test_nex_ag_openapi_includes_generation_quality_issue_detail_contract() -> None:
    openapi_path = (
        Path(__file__).parents[1] / "contracts" / "openapi" / "nex-ag.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    operation = spec["paths"][
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-issue-detail"
    ]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    component = spec["components"]["schemas"][
        "AgGenerationQualityIssueDetailProjection"
    ]

    assert operation["operationId"] == "getAgGenerationQualityIssueDetailProjection"
    assert set(parameters) == {
        "cx_generation_id",
        "artifact_handoff_id",
        "recovery_request_id",
    }
    assert parameters["cx_generation_id"]["required"] is True
    assert response_schema["$ref"] == (
        "#/components/schemas/AgGenerationQualityIssueDetailProjection"
    )
    assert component["properties"]["projection_schema_version"]["const"] == (
        "ag_generation_quality_issue_detail_projection.v1"
    )
    assert {"quality", "runbook", "debug_paths", "redaction_summary"}.issubset(
        set(component["required"])
    )


def test_ag_generation_quality_observability_closure_artifacts_are_linked() -> None:
    root = Path(__file__).parents[1]
    docs_readme = (root / "docs" / "README.md").read_text(encoding="utf-8")
    expected_slice_docs = {
        "0321": "0321_ag_generation_audit_grounded_quality_gap_audit.md",
        "0322": "0322_ag_generation_audit_quality_projection_wiring.md",
        "0323": "0323_ag_generation_audit_quality_contract_schema_hardening.md",
        "0324": "0324_ag_generation_audit_quality_dashboard_surface.md",
        "0325": "0325_ag_generation_audit_quality_postgresql_smoke_evidence.md",
        "0326": "0326_ag_generation_quality_issue_detail_runbook_projection.md",
        "0327": "0327_ag_generation_quality_issue_detail_api_wiring.md",
        "0328": "0328_ag_generation_quality_issue_detail_contract_schema_hardening.md",
        "0329": "0329_ag_generation_quality_issue_detail_postgresql_smoke_evidence.md",
    }

    for slice_id, filename in expected_slice_docs.items():
        assert f"Slice {slice_id}" in docs_readme
        assert f"slices/{filename}" in docs_readme
        assert (root / "docs" / "slices" / filename).exists()

    assert (
        root
        / "contracts"
        / "schemas"
        / "generation"
        / "ag_generation_audit_grounded_response_quality_projection.v1.schema.json"
    ).exists()
    assert (
        root
        / "contracts"
        / "schemas"
        / "generation"
        / "ag_generation_quality_issue_detail_projection.v1.schema.json"
    ).exists()
    smoke_text = (
        root / "scripts" / "smoke" / "run_ag_generation_quality_postgres_smoke.py"
    ).read_text(encoding="utf-8")
    assert "issue_detail_contract_valid" in smoke_text
    assert "issue_detail_runbook_surfaces_metadata_gap" in smoke_text
    assert "NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE" in smoke_text


def test_nex_cx_openapi_includes_service_log_retention_control() -> None:
    openapi_path = (
        Path(__file__).parents[1] / "contracts" / "openapi" / "nex-cx.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    retention_purge = spec["paths"][
        "/internal/v1/service-logs/retention/purge"
    ]["post"]

    assert retention_purge["operationId"] == "purgeCxServiceLogRetention"
    assert retention_purge["requestBody"]["content"]["application/json"]["schema"][
        "required"
    ] == ["retention_cutoff"]
    assert retention_purge["responses"]["200"]["content"]["application/json"]["schema"][
        "properties"
    ]["retention_execution_schema_version"]["const"] == (
        "service_log_retention_execution.v1"
    )


def test_nex_cx_openapi_hardens_document_detail_contract() -> None:
    openapi_path = (
        Path(__file__).parents[1] / "contracts" / "openapi" / "nex-cx.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    operation = spec["paths"]["/api/v1/documents/{document_id}"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    document_schema = schema["properties"]["document"]
    source_lineage_schema = document_schema["properties"]["source_lineage"]
    upload_schema = document_schema["properties"]["upload"]

    assert operation["operationId"] == "getCxDocumentDetail"
    assert parameters["tenant_id"]["required"] is True
    assert parameters["owner_user_id"]["required"] is True
    assert schema["additionalProperties"] is False
    assert schema["properties"]["projection_schema_version"]["const"] == (
        "cx_document_detail_projection.v1"
    )
    assert document_schema["additionalProperties"] is False
    assert {"tenant_ref", "owner_subject_ref", "uploaded_by_subject_ref"}.issubset(
        set(document_schema["required"])
    )
    assert source_lineage_schema["additionalProperties"] is False
    assert source_lineage_schema["properties"]["storage_path_included"]["const"] is False
    assert upload_schema["properties"]["source_content_in_record"]["const"] is False
    assert schema["properties"]["metadata"]["properties"]["owner_scoped"]["const"] is True


def test_nex_cx_text_extraction_contract_hardens_normalized_markdown_metadata() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "service"
        / "nex_cx"
        / "text_extraction.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    normalization_schema = schema["properties"]["extracted_markdown_normalization"]
    source_reader_schema = schema["properties"]["source_reader"]
    extractor_schema = schema["properties"]["extractor"]

    assert "extracted_markdown_normalization" in schema["required"]
    assert "source_reader" in schema["required"]
    assert "warnings" in schema["required"]
    assert normalization_schema["additionalProperties"] is False
    assert normalization_schema["properties"]["line_endings"]["const"] == "lf"
    assert normalization_schema["properties"]["final_newline"]["const"] is True
    assert normalization_schema["properties"]["trailing_whitespace_present"][
        "const"
    ] is False
    assert normalization_schema["properties"]["contract_status"]["const"] == "valid"
    assert extractor_schema["properties"]["source_format"]["enum"] == [
        "markdown",
        "plain_text",
        "pdf",
        "docx",
        "pptx",
        "xlsx",
    ]
    assert source_reader_schema["properties"]["raw_source_included"]["const"] is False
    assert source_reader_schema["properties"]["local_storage_path_included"][
        "const"
    ] is False


def test_nex_cx_remediation_execution_contracts_preserve_cx_boundary() -> None:
    root = Path(__file__).parents[1]
    request_schema = json.loads(
        (
            root
            / "contracts"
            / "schemas"
            / "generation"
            / "cx_remediation_execution_request.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    result_schema = json.loads(
        (
            root
            / "contracts"
            / "schemas"
            / "generation"
            / "cx_remediation_execution_result.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    spec = yaml.safe_load(
        (root / "contracts" / "openapi" / "nex-cx.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )

    request_action_enum = request_schema["$defs"]["cxExecutableActionType"]["enum"]
    request_policy = request_schema["$defs"]["executionPolicy"]["properties"]
    request_metadata = request_schema["$defs"]["rawSafeMetadata"]["properties"]
    result_ref = result_schema["$defs"]["resultRef"]["properties"]
    redaction_summary = result_schema["$defs"]["redactionSummary"]["properties"]
    operation = spec["paths"][
        "/api/v1/generations/{cx_generation_id}/remediation-executions"
    ]["post"]
    response_schema = operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ]

    assert request_action_enum == [
        "retry_generation",
        "retrieval_repair",
        "citation_repair",
    ]
    assert "prompt_policy_review" not in request_action_enum
    assert "mark_accepted" not in request_action_enum
    assert request_policy["parent_generation_mutation_allowed"]["const"] is False
    assert request_policy["provider_boundary"]["const"] == "cx_to_mo_service_api_only"
    assert request_metadata["raw_prompt_stored"]["const"] is False
    assert request_metadata["raw_generation_output_stored"]["const"] is False
    assert result_ref["source_service"]["const"] == "nex-cx"
    assert result_ref["ref_type"]["const"] == "repair_execution"
    assert result_ref["relation"]["const"] == "result_of"
    assert redaction_summary["provider_detail_included"]["const"] is False
    assert operation["operationId"] == "createCxRemediationExecution"
    assert response_schema["properties"]["result_schema_version"]["const"] == (
        "cx_remediation_execution_result.v1"
    )


def test_nex_ae_openapi_hardens_document_detail_contract() -> None:
    openapi_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "openapi"
        / "nex-ae-api.openapi.yaml"
    )
    spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    operation = spec["paths"]["/api/v1/documents/{document_id}"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    document_schema = schema["properties"]["document"]
    source_lineage_schema = document_schema["properties"]["source_lineage"]
    document_metadata_schema = document_schema["properties"]["metadata"]
    root_metadata_schema = schema["properties"]["metadata"]

    assert operation["operationId"] == "getAeDocumentDetail"
    assert parameters["document_id"]["required"] is True
    assert schema["additionalProperties"] is False
    assert schema["properties"]["projection_schema_version"]["const"] == (
        "ae_document_detail_projection.v1"
    )
    assert document_schema["additionalProperties"] is False
    assert document_schema["properties"]["document_detail_schema_version"]["const"] == (
        "ae_document_detail_item.v1"
    )
    assert source_lineage_schema["additionalProperties"] is False
    assert source_lineage_schema["properties"]["storage_key_included"]["const"] is False
    assert source_lineage_schema["properties"]["storage_uri_included"]["const"] is False
    assert source_lineage_schema["properties"]["storage_path_included"]["const"] is False
    assert document_metadata_schema["properties"]["raw_summary_stored_in_ae"][
        "const"
    ] is False
    assert document_metadata_schema["properties"]["embedding_vector_stored_in_ae"][
        "const"
    ] is False
    assert root_metadata_schema["properties"]["cx_detail_passthrough"]["const"] is False


def test_load_structured_file_rejects_unsupported_suffix(tmp_path: Path) -> None:
    unsupported = tmp_path / "payload.txt"
    unsupported.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError):
        validate_contracts.load_structured_file(unsupported)


def test_main_returns_success_for_valid_package(tmp_path: Path, capsys) -> None:
    build_contract_fixture(tmp_path)

    assert validate_contracts.main([str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "contract_validation=pass" in output
    assert "negative_examples=1" in output


def test_main_returns_failure_for_invalid_package(tmp_path: Path, capsys) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "sample.json", {"unexpected": "value"})

    assert validate_contracts.main([str(tmp_path)]) == 1
    assert "contract validation failure" in capsys.readouterr().out
