from __future__ import annotations

from pathlib import Path

from nex_cx.contract_api_drift_audit import (
    _index_entries,
    _load_mapping,
    _openapi_operations,
    _runtime_operations,
    build_cx_contract_api_drift_audit,
)
import run_cx_contract_api_drift_audit as runner


def test_repository_contract_api_audit_confirms_known_drift() -> None:
    result = build_cx_contract_api_drift_audit()

    assert result["status"] == "PASS"
    assert result["contract_readiness"] == "HARDENED"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "runtime_operation_count": 36,
        "openapi_operation_count": 52,
        "runtime_openapi_covered_count": 36,
        "missing_openapi_operation_count": 0,
        "shared_openapi_operation_count": 5,
        "cx_schema_count": 16,
        "cx_positive_fixture_covered_count": 16,
        "cx_negative_fixture_covered_count": 16,
        "generation_schema_count": 7,
        "drift_count": 0,
        "audit_issue_count": 0,
    }
    assert result["openapi_version"] == "0.96.0"
    assert result["missing_negative_fixtures"] == []
    assert result["missing_openapi_operations"] == []


def test_contract_api_audit_fails_closed_without_inputs(tmp_path: Path) -> None:
    result = build_cx_contract_api_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["contract_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["audit_issue_count"] == 4
    assert result["checks"]["audit_inputs_present"] is False


def test_contract_parsers_cover_valid_invalid_and_dynamic_routes(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "valid.py").write_text(
        '@app.get("/api/v1/items")\ndef items():\n    pass\n'
        '@app.get(prefix + "/dynamic")\ndef dynamic():\n    pass\n',
        encoding="utf-8",
    )
    (source_root / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    assert _runtime_operations(source_root) == {("GET", "/api/v1/items")}
    assert _runtime_operations(tmp_path / "missing") == set()

    yaml_path = tmp_path / "openapi.yaml"
    yaml_path.write_text("paths:\n  /x:\n    get: {}\n    parameters: []\n", encoding="utf-8")
    loaded = _load_mapping(yaml_path)
    assert _openapi_operations(loaded) == {("GET", "/x")}
    assert _openapi_operations({"paths": {1: {"get": {}}}}) == set()
    yaml_path.write_text("paths: [\n", encoding="utf-8")
    assert _load_mapping(yaml_path) == {}
    assert _load_mapping(tmp_path / "missing.yaml") == {}

    index_path = tmp_path / "index.json"
    index_path.write_text('{"examples":[{"schema":"a"},"bad"]}', encoding="utf-8")
    assert _index_entries(index_path, "examples") == [{"schema": "a"}]
    index_path.write_text("{bad", encoding="utf-8")
    assert _index_entries(index_path, "examples") == []
    assert _index_entries(tmp_path / "missing.json", "examples") == []


def test_summary_line_and_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_cx_contract_api_drift_audit()

    assert runner.summary_line(passing) == (
        "cx_contract_api_drift_audit=pass readiness=HARDENED "
        "runtime_routes=36 openapi_missing=0 schema_negative=16/16 drift=0"
    )
    assert "readiness=UNKNOWN" in runner.summary_line({"status": "FAIL"})
    monkeypatch.setattr(runner, "run_cx_contract_api_drift_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "drift=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_contract_api_drift_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
