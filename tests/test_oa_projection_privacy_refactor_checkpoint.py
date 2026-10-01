from __future__ import annotations

from pathlib import Path

from nex_oa.projection_privacy_checkpoint import (
    RequiredEvidence,
    _contract_projection_aligned,
    _inspect_evidence,
    _read_text,
    build_oa_projection_privacy_checkpoint,
)
import run_oa_projection_privacy_refactor_checkpoint as runner


def test_repository_checkpoint_confirms_projection_and_privacy_repairs() -> None:
    result = build_oa_projection_privacy_checkpoint()

    assert result["status"] == "PASS"
    assert result["refactor_readiness"] == (
        "PRIVACY_AND_PROJECTION_BOUNDARY_REPAIRED"
    )
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "repair_count": 5,
        "forbidden_stale_count": 0,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["database_schema_changed"] is False
    assert result["decision"]["auth_enforcement_changed"] is False
    assert result["decision"]["production_trust_gaps_remain"] is True
    assert result["next_slice"] == "1210"


def test_checkpoint_exposes_repaired_surfaces_and_safe_findings() -> None:
    result = build_oa_projection_privacy_checkpoint()

    assert result["repaired_surfaces"] == [
        "subject_capability_projection",
        "membership_capability_projection",
        "auth_authority_current_state",
        "session_delegation_metadata",
        "resolver_transport_error_privacy",
    ]
    assert all(item["present"] is False for item in result["stale_findings"])
    assert all(item["present"] is True for item in result["evidence"])


def test_checkpoint_fails_closed_without_repository(tmp_path: Path) -> None:
    result = build_oa_projection_privacy_checkpoint(tmp_path)

    assert result["status"] == "FAIL"
    assert result["refactor_readiness"] == "BLOCKED"
    assert result["checks"]["required_evidence_present"] is False
    assert result["checks"]["contract_projection_aligned"] is False
    assert result["summary"]["evidence_issue_count"] == 10
    assert result["issues"][-1] == {
        "category": "subject_contract_projection_drift"
    }


def test_checkpoint_detects_stale_projection_token(tmp_path: Path) -> None:
    source = tmp_path / "services/nex-oa/nex_oa/subjects.py"
    source.parent.mkdir(parents=True)
    source.write_text('"password_login": False\n', encoding="utf-8")

    result = build_oa_projection_privacy_checkpoint(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["forbidden_stale_count"] == 1
    assert {
        "category": "stale_projection_present",
        "name": "subject_login_reported_deferred",
        "path": "services/nex-oa/nex_oa/subjects.py",
    } in result["issues"]


def test_helpers_cover_present_missing_and_contract_alignment(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("token\n", encoding="utf-8")
    ref = RequiredEvidence("sample", "evidence.txt", "token")

    assert _inspect_evidence(tmp_path, ref)["present"] is True
    assert _read_text(path) == "token\n"
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _contract_projection_aligned(tmp_path) is False


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_projection_privacy_checkpoint()

    assert "projection_privacy_checkpoint=pass" in runner.summary_line(passing)
    assert "repairs=5" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_oa_projection_privacy_checkpoint",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "stale=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_oa_projection_privacy_checkpoint",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
