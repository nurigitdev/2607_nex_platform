from __future__ import annotations

from pathlib import Path

from nex_mo.contract_api_drift_audit import (
    _has_security_declaration,
    _has_success_response_schema,
    _indexed_schemas,
    _openapi_operations,
    _read_json,
    _read_yaml,
    _runtime_operations,
    build_mo_contract_api_drift_audit,
)
import run_mo_contract_api_drift_audit as runner


def test_repository_contract_and_api_drift_is_quantified() -> None:
    result = build_mo_contract_api_drift_audit()

    assert result["status"] == "PASS"
    assert result["contract_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "runtime_operation_count": 19,
        "openapi_operation_count": 15,
        "missing_openapi_operation_count": 4,
        "stale_mock_operation_count": 0,
        "missing_request_body_count": 0,
        "missing_success_schema_count": 0,
        "missing_security_count": 0,
        "schema_count": 17,
        "positive_fixture_covered_count": 17,
        "negative_fixture_covered_count": 17,
        "drift_count": 4,
    }
    assert "GET /api/v1/provider-telemetry" not in result["missing_openapi_operations"]
    assert result["extra_openapi_operations"] == []
    assert len(result["ordered_remediation"]) == 4


def test_audit_fails_closed_when_contract_tree_is_missing(tmp_path: Path) -> None:
    result = build_mo_contract_api_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["contract_readiness"] == "BLOCKED"
    assert result["checks"]["openapi_document_readable"] is False
    assert result["summary"]["openapi_operation_count"] == 0
    assert result["summary"]["missing_openapi_operation_count"] == 19
    assert result["checks"]["schema_negative_fixtures_complete"] is True


def test_contract_helpers_cover_present_invalid_and_missing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "openapi.yaml"
    json_path = tmp_path / "index.json"
    invalid_yaml = tmp_path / "invalid.yaml"
    yaml_path.write_text("paths:\n  /health:\n    get:\n      responses: {}\n", encoding="utf-8")
    json_path.write_text(
        '{"examples": [{"schema": "schemas/service/nex_mo/test.json"}]}',
        encoding="utf-8",
    )
    invalid_yaml.write_text("paths: [", encoding="utf-8")

    document = _read_yaml(yaml_path)
    assert _openapi_operations(document) == {"GET /health"}
    assert _read_yaml(invalid_yaml) == {}
    assert _read_yaml(tmp_path / "missing.yaml") == {}
    assert _read_json(tmp_path / "missing.json") == {}
    assert _indexed_schemas(json_path, "examples") == {
        "schemas/service/nex_mo/test.json"
    }
    assert _runtime_operations() >= {"GET /health", "POST /api/v1/generations"}
    assert _has_success_response_schema(
        {"get": {"responses": {"200": {"content": {"application/json": {}}}}}}
    ) is True
    assert _has_success_response_schema({"get": {"responses": {}}}) is False
    assert _has_security_declaration({"get": {"security": []}}) is True
    assert _has_security_declaration({"get": {}}) is False


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_contract_api_drift_audit()

    assert "drift_audit=pass" in runner.summary_line(passing)
    assert "operations=15/19" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_contract_api_drift_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "negative=17/17" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_contract_api_drift_audit", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "drift_audit=fail" in capsys.readouterr().out
