from pathlib import Path

import run_oa_group_role_authorization_boundary as boundary


def test_repository_boundary_passes() -> None:
    result = boundary.run_oa_group_role_authorization_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["decision"]["grant_model"] == {
        "composition": "set_union",
        "sources": (
            "direct_membership_roles_and_scopes",
            "group_assigned_roles",
            "role_defined_scopes",
        ),
        "explicit_deny_supported": False,
        "unknown_role_fails_closed": True,
        "nested_groups_supported": False,
    }
    assert result["quality_cadence"]["checkpoint_gate"] == "1236"
    assert result["quality_cadence"]["full_gate"] == "1241"


def test_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = boundary.run_oa_group_role_authorization_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_group_role_authorization_boundary_failed"
    assert len(result["issues"]) == len(boundary.REQUIRED_EVIDENCE)


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = boundary.run_oa_group_role_authorization_boundary()
    assert "grant=set_union" in boundary.summary_line(passing)
    assert "admin=authorization:admin" in boundary.summary_line(passing)
    assert "boundary=fail" in boundary.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        boundary,
        "run_oa_group_role_authorization_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        boundary,
        "run_oa_group_role_authorization_boundary",
        lambda: {"status": "FAIL"},
    )
    assert boundary.main([]) == 1
