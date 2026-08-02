from __future__ import annotations

import json

import pytest

import run_traceable_mock_flow as smoke


def test_run_traceable_mock_flow_links_trace_across_services() -> None:
    evidence = smoke.run_traceable_mock_flow()

    assert evidence["assertions"] == {
        "ae_trace": True,
        "cx_trace": True,
        "mo_trace": True,
        "ag_trace": True,
    }
    assert evidence["ae"]["cx_generation_id"] == evidence["cx"]["cx_generation_id"]
    assert evidence["cx"]["mo_generation_id"] == evidence["mo"]["mo_generation_id"]
    assert evidence["ag"]["summary"]["total"] == 5


def test_assert_trace_evidence_reports_mismatch() -> None:
    evidence = smoke.run_traceable_mock_flow()
    evidence["ag"]["trace_id"] = "0" * 32

    with pytest.raises(AssertionError):
        smoke.assert_trace_evidence(evidence)


def test_main_prints_summary(capsys) -> None:
    assert smoke.main(["--summary"]) == 0

    assert "traceable_mock_flow=pass" in capsys.readouterr().out


def test_main_writes_evidence_file(tmp_path) -> None:
    output = tmp_path / "trace-smoke.json"

    assert smoke.main(["--output", str(output)]) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["trace_id"] == smoke.TRACE_ID
