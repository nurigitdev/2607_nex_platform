from __future__ import annotations

import json
from pathlib import Path

import check_coverage_thresholds as coverage_check


def test_calculate_percent_handles_zero_denominator() -> None:
    assert coverage_check.calculate_percent(0, 0) == 100.0


def test_evaluate_thresholds_passes_when_coverage_is_high() -> None:
    result = coverage_check.evaluate_thresholds(
        {
            "covered_lines": 95,
            "num_statements": 100,
            "covered_branches": 85,
            "num_branches": 100,
        },
        statement_min=95,
        branch_min=85,
    )

    assert result["statement_coverage"] == 95
    assert result["branch_coverage"] == 85
    assert result["failures"] == []


def test_evaluate_thresholds_reports_statement_and_branch_failures() -> None:
    result = coverage_check.evaluate_thresholds(
        {
            "covered_lines": 94,
            "num_statements": 100,
            "covered_branches": 84,
            "num_branches": 100,
        },
        statement_min=95,
        branch_min=85,
    )

    assert len(result["failures"]) == 2


def test_main_loads_json_and_returns_success(
    tmp_path: Path,
    capsys,
) -> None:
    coverage_json = tmp_path / "coverage.json"
    coverage_json.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 10,
                    "num_statements": 10,
                    "covered_branches": 5,
                    "num_branches": 5,
                }
            }
        ),
        encoding="utf-8",
    )

    assert coverage_check.main([str(coverage_json), "95", "85"]) == 0
    assert "statement_coverage=100.00%" in capsys.readouterr().out


def test_main_returns_usage_error_for_bad_args(capsys) -> None:
    assert coverage_check.main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_returns_failure_when_thresholds_miss(
    tmp_path: Path,
    capsys,
) -> None:
    coverage_json = tmp_path / "coverage.json"
    coverage_json.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 1,
                    "num_statements": 2,
                    "covered_branches": 0,
                    "num_branches": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    assert coverage_check.main([str(coverage_json), "95", "85"]) == 1
    assert "coverage failure" in capsys.readouterr().err
