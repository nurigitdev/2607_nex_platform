from __future__ import annotations

import json

import pytest
import report_coverage_hotspots as report


def _coverage() -> dict:
    return {
        "files": {
            "services/nex-ae-api/nex_ae_api/runtime.py": {
                "summary": {
                    "num_statements": 100,
                    "covered_lines": 96,
                    "num_branches": 20,
                    "covered_branches": 19,
                }
            },
            "providers/nex-compatible-provider/nex_compatible_provider/app.py": {
                "summary": {
                    "num_statements": 20,
                    "covered_lines": 19,
                    "num_branches": 4,
                    "covered_branches": 3,
                }
            },
            "scripts/smoke/run_runtime.py": {
                "summary": {
                    "num_statements": 50,
                    "covered_lines": 40,
                    "num_branches": 10,
                    "covered_branches": 7,
                }
            },
            "scripts/quality/check_runtime.py": {
                "summary": {
                    "num_statements": 10,
                    "covered_lines": 10,
                    "num_branches": 2,
                    "covered_branches": 2,
                }
            },
            "scripts/deployment/run_runtime.py": {
                "summary": {
                    "num_statements": 20,
                    "covered_lines": 15,
                    "num_branches": 4,
                    "covered_branches": 2,
                }
            },
        },
        "totals": {
            "num_statements": 200,
            "covered_lines": 180,
            "num_branches": 40,
            "covered_branches": 33,
        },
    }


def test_report_separates_product_harness_and_other_hotspots() -> None:
    value = report.build_hotspot_report(_coverage(), top_n=1)

    assert value["thresholds_changed"] is False
    assert value["totals"]["statement_coverage"] == 90.0
    assert value["totals"]["branch_coverage"] == 82.5
    assert value["totals"]["additional_existing_statements_for_targets"] == {
        "96.25": 13,
        "96.30": 13,
    }
    assert value["ownership_scopes"]["product_code"]["file_count"] == 2
    assert value["ownership_scopes"]["smoke_test_harness"]["file_count"] == 2
    assert value["ownership_scopes"]["other_runtime_tooling"]["file_count"] == 1
    assert value["hotspots"]["product_code"][0]["path"].startswith("services/")
    assert value["hotspots"]["smoke_test_harness"][0]["missing_statements"] == 10
    assert value["hotspots"]["other_runtime_tooling"][0]["missing_branches"] == 2
    assert report.summary_line(value) == (
        "coverage_hotspots=pass total=90.00/82.50 "
        "product=95.83/91.67 harness=83.33/75.00"
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.pop("files"), "files and totals"),
        (lambda value: value["files"].update({"bad.py": []}), "file entry"),
        (
            lambda value: value["files"][
                "services/nex-ae-api/nex_ae_api/runtime.py"
            ].pop("summary"),
            "summary",
        ),
        (
            lambda value: value["totals"].update({"num_statements": -1}),
            "non-negative integer",
        ),
    ),
)
def test_report_rejects_malformed_coverage(mutation, message: str) -> None:
    value = _coverage()
    mutation(value)
    with pytest.raises((TypeError, ValueError), match=message):
        report.build_hotspot_report(value)


def test_report_rejects_invalid_top_and_handles_zero_statement_file() -> None:
    value = _coverage()
    value["files"]["scripts/quality/empty.py"] = {
        "summary": {
            "num_statements": 0,
            "covered_lines": 0,
            "num_branches": 0,
            "covered_branches": 0,
        }
    }
    built = report.build_hotspot_report(value)
    assert built["ownership_scopes"]["smoke_test_harness"]["file_count"] == 3
    with pytest.raises(ValueError, match="positive"):
        report.build_hotspot_report(value, top_n=0)


def test_main_writes_report_and_fails_closed(tmp_path, capsys) -> None:
    source = tmp_path / "coverage.json"
    output = tmp_path / "nested" / "hotspots.json"
    source.write_text(json.dumps(_coverage()), encoding="utf-8")

    assert report.main([str(source), "--output", str(output), "--summary"]) == 0
    assert "coverage_hotspots=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        report.REPORT_SCHEMA_VERSION
    )

    source.write_text("{", encoding="utf-8")
    assert report.main([str(source), "--summary"]) == 1
    assert "coverage_hotspots=fail" in capsys.readouterr().out
