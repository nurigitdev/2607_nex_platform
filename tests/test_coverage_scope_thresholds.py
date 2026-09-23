from __future__ import annotations

import json

import check_coverage_scopes as scopes


def _coverage() -> dict:
    return {
        "files": {
            "services/nex-cx/nex_cx/alpha.py": {
                "summary": {
                    "num_statements": 10,
                    "covered_lines": 10,
                    "num_branches": 4,
                    "covered_branches": 4,
                }
            },
            "services/nex-cx/nex_cx/beta.py": {
                "summary": {
                    "num_statements": 10,
                    "covered_lines": 9,
                    "num_branches": 4,
                    "covered_branches": 3,
                }
            },
        }
    }


def test_scope_aggregates_files_and_enforces_both_thresholds() -> None:
    result = scopes.evaluate_scope(
        _coverage(),
        scope="services/nex-cx/nex_cx",
        statement_min=95,
        branch_min=85,
    )

    assert result == {
        "scope": "services/nex-cx/nex_cx",
        "file_count": 2,
        "statement_coverage": 95.0,
        "branch_coverage": 87.5,
        "failures": [],
    }


def test_scope_fails_for_low_coverage_and_missing_scope() -> None:
    low = scopes.evaluate_scope(
        _coverage(),
        scope="services/nex-cx/nex_cx/beta.py",
        statement_min=95,
        branch_min=94,
    )
    missing = scopes.evaluate_scope(
        _coverage(),
        scope="services/nex-cx/nex_cx/missing.py",
        statement_min=95,
        branch_min=94,
    )

    assert len(low["failures"]) == 2
    assert "statement coverage" in low["failures"][0]
    assert "branch coverage" in low["failures"][1]
    assert missing["file_count"] == 0
    assert missing["statement_coverage"] == 100.0
    assert missing["branch_coverage"] == 100.0
    assert missing["failures"] == [
        "services/nex-cx/nex_cx/missing.py is absent from the coverage report"
    ]


def test_main_reports_pass_failure_and_usage(tmp_path, capsys) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage()), encoding="utf-8")

    assert scopes.main([]) == 2
    assert "usage:" in capsys.readouterr().err
    assert scopes.main(
        [
            str(coverage_path),
            "95",
            "85",
            "services/nex-cx/nex_cx",
        ]
    ) == 0
    assert "statement=95.00%" in capsys.readouterr().out
    assert scopes.main(
        [
            str(coverage_path),
            "95",
            "94",
            "services/nex-cx/nex_cx/beta.py",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert "coverage scope failure" in captured.err


def test_mapping_and_zero_total_helpers() -> None:
    assert scopes._percent(0, 0) == 100.0
    assert scopes._percent(1, 2) == 50.0
    assert scopes._mapping(None) == {}
    assert scopes._mapping({"ok": True}) == {"ok": True}
