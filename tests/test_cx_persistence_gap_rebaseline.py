from __future__ import annotations

import run_cx_persistence_gap_rebaseline as runner


def test_rebaseline_closes_metadata_and_separates_private_payloads() -> None:
    result = runner.run_cx_persistence_gap_rebaseline()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["failure_code"] is None
    assert result["summary"]["durable_metadata_surface_count"] == 10
    assert result["summary"]["durable_metadata_gap_count"] == 0
    assert result["summary"]["private_payload_boundary_count"] == 6
    assert result["summary"]["deferred_schema_decision_count"] == 2
    assert result["gap_classification"] == {
        "durable_public_metadata": "CLOSED",
        "private_payload_durability": "BOUNDARY_FROZEN_IMPLEMENTATION_PENDING",
        "optional_zero_item_index_headers": "DEFERRED_OPTIMIZATION",
    }


def test_summary_line_reports_counts_and_failure() -> None:
    passing = runner.run_cx_persistence_gap_rebaseline()
    failing = {
        "status": "FAIL",
        "summary": {
            "durable_metadata_surface_count": 9,
            "durable_metadata_gap_count": 1,
            "private_payload_boundary_count": 6,
            "deferred_schema_decision_count": 2,
        },
    }

    assert "rebaseline=pass" in runner.summary_line(passing)
    assert "metadata_closed=10" in runner.summary_line(passing)
    assert "rebaseline=fail" in runner.summary_line(failing)
    assert "metadata_gaps=1" in runner.summary_line(failing)
    assert "private_boundaries=0" in runner.summary_line({"status": "FAIL"})


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = runner.run_cx_persistence_gap_rebaseline()
    monkeypatch.setattr(
        runner,
        "run_cx_persistence_gap_rebaseline",
        lambda: passing,
    )

    assert runner.main(["--summary"]) == 0
    assert "rebaseline=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        runner,
        "run_cx_persistence_gap_rebaseline",
        lambda: failing,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
