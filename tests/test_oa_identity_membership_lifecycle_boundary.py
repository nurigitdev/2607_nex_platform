from __future__ import annotations

from pathlib import Path

import run_oa_identity_membership_lifecycle_boundary as boundary


def test_repository_boundary_passes_and_freezes_decisions() -> None:
    result = boundary.run_oa_identity_membership_lifecycle_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["subject_states"] == ["ACTIVE", "DISABLED", "DELETED"]
    assert result["decision"]["membership_states"] == ["ACTIVE", "DISABLED"]
    assert result["decision"]["lifecycle_write_scope"] == "identity:lifecycle:write"
    assert result["decision"]["group_registry_deferred"] is True
    assert result["quality_cadence"] == {
        "slice_gate": "every_slice",
        "checkpoint_gate": "1216",
        "full_gate": "1221",
    }
    assert len(result["slice_plan"]) == 10


def test_boundary_fails_closed_when_evidence_is_missing(tmp_path: Path) -> None:
    result = boundary.run_oa_identity_membership_lifecycle_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "required_evidence_present": False,
        "direct_identity_states_reusable": False,
        "durable_records_reusable": False,
        "s121_handoff_ready": False,
    }
    assert len(result["issues"]) == len(boundary.REQUIRED_EVIDENCE)


def test_helpers_and_summary_cover_pass_and_failure(tmp_path: Path) -> None:
    item = tmp_path / "item.txt"
    item.write_text("ready", encoding="utf-8")
    entries = [{"name": "ready", "present": True}]

    assert boundary._read_text(item) == "ready"
    assert boundary._read_text(tmp_path / "missing.txt") == ""
    assert boundary._present(entries, "ready") is True
    assert boundary._present(entries, "missing") is False
    assert "boundary=pass" in boundary.summary_line(
        boundary.run_oa_identity_membership_lifecycle_boundary()
    )
    assert "issues=1" in boundary.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_oa_identity_membership_lifecycle_boundary()
    monkeypatch.setattr(
        boundary,
        "run_oa_identity_membership_lifecycle_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_oa_identity_membership_lifecycle_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
