from __future__ import annotations

from pathlib import Path

import run_platform_deployment_packaging_boundary as boundary


def test_repository_boundary_freezes_s142_packaging_topology() -> None:
    result = boundary.run_platform_deployment_packaging_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "artifact_count": 6,
        "process_count": 13,
        "source_command_count": 13,
        "environment_class_count": 4,
        "runtime_profile_count": 5,
        "gap_count": 8,
        "missing_path_count": 0,
    }
    assert result["decision"] == {
        "packaging_format": "OCI",
        "single_platform_image_allowed": False,
        "production_connection_required": False,
        "production_deployment_approved": False,
        "new_table_required": False,
        "next_slice": "1413",
    }


def test_artifact_and_environment_boundaries_are_exact() -> None:
    result = boundary.run_platform_deployment_packaging_boundary()

    assert [item["artifact_id"] for item in result["artifact_boundaries"]] == [
        "nex-oa-runtime",
        "nex-ae-runtime",
        "nex-cx-runtime",
        "nex-mo-runtime",
        "nex-ag-runtime",
        "nex-ae-web",
    ]
    assert result["environment_profile_map"] == {
        "development": ["local_mock", "local_live"],
        "test": ["test"],
        "staging": ["staging_live"],
        "production": ["production"],
    }
    assert result["packaging_gaps"] == list(boundary.EXPECTED_GAPS)


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_deployment_packaging_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["issues"]
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"


def test_text_helpers_and_summary_branches(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("one\n  two", encoding="utf-8")
    assert boundary._read_text(source) == "one\n  two"
    assert boundary._normalized_text(source) == "one two"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = boundary.run_platform_deployment_packaging_boundary()
    assert boundary.summary_line(passing) == (
        "platform_deployment_packaging_boundary=pass "
        "artifacts=6 processes=13 source_commands=13 environments=4 gaps=8 "
        "next=1413"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_deployment_packaging_boundary=fail issues=1"
    )


def test_main_outputs_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_platform_deployment_packaging_boundary()
    monkeypatch.setattr(
        boundary, "run_platform_deployment_packaging_boundary", lambda: passing
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_platform_deployment_packaging_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1

