from __future__ import annotations

from pathlib import Path

import run_platform_production_responsibility_matrix as matrix


def test_repository_matrix_assigns_all_production_controls() -> None:
    result = matrix.run_platform_production_responsibility_matrix()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "control_count": 9,
        "owner_count": 6,
        "accountable_owner_count": 6,
        "responsible_owner_count": 6,
        "database_owner_count": 5,
        "target_requirement_count": 7,
    }
    assert len(result["assignments"]) == 9
    assert result["decision"] == {
        "service_data_ownership_changed": False,
        "shared_database_access_allowed": False,
        "platform_coordination_implies_domain_ownership": False,
        "production_connection_required": False,
        "next_slice": "1408",
    }


def test_empty_repository_fails_documented_boundary(tmp_path: Path) -> None:
    result = matrix.run_platform_production_responsibility_matrix(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == [
        "all_assignments_complete",
        "cross_database_reads_forbidden",
        "platform_does_not_own_domain_data",
    ]
    assert result["decision"]["next_slice"] == "blocked"


def test_database_ownership_uses_service_local_environment_names() -> None:
    result = matrix.run_platform_production_responsibility_matrix()

    assert result["database_ownership"] == {
        "nex-oa": {"owner": "OA", "database_env": "NEX_OA_DATABASE_URL"},
        "nex-ag": {"owner": "AG", "database_env": "NEX_AG_DATABASE_URL"},
        "nex-ae-api": {"owner": "AE", "database_env": "NEX_AE_DATABASE_URL"},
        "nex-cx": {"owner": "CX", "database_env": "NEX_CX_DATABASE_URL"},
        "nex-mo": {"owner": "MO", "database_env": "NEX_MO_DATABASE_URL"},
    }


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert matrix._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert matrix._read_text(source) == "value"

    passing = matrix.run_platform_production_responsibility_matrix()
    assert matrix.summary_line(passing) == (
        "platform_production_responsibility_matrix=pass controls=9 owners=6 "
        "databases=5 targets=7 next=1408"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert matrix.summary_line(failing) == (
        "platform_production_responsibility_matrix=fail issues=1"
    )

    monkeypatch.setattr(
        matrix, "run_platform_production_responsibility_matrix", lambda: passing
    )
    assert matrix.main(["--summary"]) == 0
    assert "matrix=pass" in capsys.readouterr().out
    assert matrix.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        matrix,
        "run_platform_production_responsibility_matrix",
        lambda: failing,
    )
    assert matrix.main([]) == 1
