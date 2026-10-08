from __future__ import annotations

import json
from pathlib import Path

import run_platform_contract_trace_privacy_e2e_gap_audit as audit


def test_repository_contract_trace_privacy_audit_tracks_named_e2e_execution() -> None:
    result = audit.run_platform_contract_trace_privacy_e2e_gap_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["contract_counts"] == {
        "schemas": 174,
        "examples": 236,
        "negative_examples": 204,
        "openapi": 7,
    }
    assert result["findings"]["golden_scenario_contract_count"] == 10
    assert result["findings"]["executable_named_golden_scenario_count"] == 10
    assert result["findings"]["executable_named_golden_scenario_ids"] == [
        f"GEN-E2E-{index:03d}" for index in range(1, 11)
    ]
    assert result["findings"]["named_generation_e2e_suite_present"] is True
    assert result["findings"]["trace_propagating_http_client_count"] == 13
    assert result["findings"]["single_trace_vertical_spine_evidence_present"] is False
    assert len(result["scenario_handoff"]) == 10
    assert result["decision"]["distributed_component_tests_equal_named_e2e_acceptance"] is False
    assert result["decision"]["next_slice"] == "1311"


def test_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_platform_contract_trace_privacy_e2e_gap_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"]
    assert result["contract_counts"] == {
        "schemas": 0,
        "examples": 0,
        "negative_examples": 0,
        "openapi": 0,
    }


def test_executable_inventory_and_index_helpers(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    scripts = tmp_path / "scripts"
    tests.mkdir()
    scripts.mkdir()
    first = "GEN-E2E-" + "001"
    last = "GEN-E2E-" + "010"
    (tests / "test_flow.py").write_text(f"{first} {last}", encoding="utf-8")
    (scripts / "ignored.txt").write_text(first, encoding="utf-8")
    (scripts / "flow.sh").write_text(first, encoding="utf-8")

    assert audit._executable_e2e_ids(tmp_path) == [first, last]

    index = tmp_path / "index.json"
    index.write_text(json.dumps({"items": [{}, {}]}), encoding="utf-8")
    assert audit._index_count(index, "items") == 2
    assert audit._index_count(index, "missing") == 0
    index.write_text("not-json", encoding="utf-8")
    assert audit._index_count(index, "items") == 0
    assert audit._index_count(tmp_path / "missing.json", "items") == 0


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "contract_counts": {
            "schemas": 159,
            "examples": 217,
            "negative_examples": 187,
            "openapi": 7,
        },
        "findings": {
            "trace_propagating_http_client_count": 13,
            "executable_named_golden_scenario_count": 0,
        },
        "decision": {"next_slice": "1311"},
    }
    assert audit.summary_line(passing) == (
        "platform_contract_trace_privacy_e2e_gap=pass "
        "contracts=159/217/187/7 trace_clients=13 named_e2e=0/10 next=1311"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_contract_trace_privacy_e2e_gap=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "contract_counts": {},
        "findings": {},
        "decision": {"next_slice": "1311"},
    }
    monkeypatch.setattr(
        audit,
        "run_platform_contract_trace_privacy_e2e_gap_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "e2e_gap=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_contract_trace_privacy_e2e_gap_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
