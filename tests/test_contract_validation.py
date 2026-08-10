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
