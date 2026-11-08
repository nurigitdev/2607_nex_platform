from __future__ import annotations

import json
from pathlib import Path

import check_coverage_thresholds as coverage_check

ROOT = Path(__file__).resolve().parents[1]


def test_calculate_percent_handles_zero_denominator() -> None:
    assert coverage_check.calculate_percent(0, 0) == 100.0


def test_evaluate_thresholds_passes_at_canonical_p8_boundary() -> None:
    result = coverage_check.evaluate_thresholds(
        {
            "covered_lines": 96,
            "num_statements": 100,
            "covered_branches": 94,
            "num_branches": 100,
        },
        statement_min=96,
        branch_min=94,
    )

    assert result["statement_coverage"] == 96
    assert result["branch_coverage"] == 94
    assert result["failures"] == []


def test_evaluate_thresholds_reports_statement_and_branch_failures() -> None:
    result = coverage_check.evaluate_thresholds(
        {
            "covered_lines": 959,
            "num_statements": 1000,
            "covered_branches": 939,
            "num_branches": 1000,
        },
        statement_min=96,
        branch_min=94,
    )

    assert len(result["failures"]) == 2


def test_repository_full_gate_defaults_to_canonical_p8_policy() -> None:
    script = (ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )

    assert 'STATEMENT_COVERAGE_MIN="${STATEMENT_COVERAGE_MIN:-96}"' in script
    assert 'BRANCH_COVERAGE_MIN="${BRANCH_COVERAGE_MIN:-94}"' in script


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

    assert coverage_check.main([str(coverage_json), "96", "94"]) == 0
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

    assert coverage_check.main([str(coverage_json), "96", "94"]) == 1
    assert "coverage failure" in capsys.readouterr().err
