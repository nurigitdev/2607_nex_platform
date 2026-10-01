from __future__ import annotations

from pathlib import Path

from nex_oa.identity_lifecycle_audit import (
    RequiredEvidence,
    _control,
    _inspect_evidence,
    _read_text,
    build_oa_identity_lifecycle_audit,
)
import run_oa_identity_lifecycle_audit as runner


def test_repository_identity_lifecycle_audit_quantifies_current_gaps() -> None:
    result = build_oa_identity_lifecycle_audit()

    assert result["status"] == "PASS"
    assert result["lifecycle_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "control_count": 8,
        "implemented_count": 6,
        "gap_count": 2,
        "stale_projection_count": 0,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["new_table_required_now"] is False
    assert result["decision"]["stale_projection_refactor_target_slice"] == "1209"
    assert result["decision"]["stale_projection_refactor_status"] == "REPAIRED"
    assert result["decision"]["direct_lifecycle_hardening_status"] == "HARDENED"


def test_audit_exposes_lifecycle_and_projection_observations() -> None:
    result = build_oa_identity_lifecycle_audit()

    assert set(result["observations"].values()) == {False, True}
    controls = {item["control_id"]: item for item in result["controls"]}
    assert controls["stable_subject_refs"]["status"] == "IMPLEMENTED"
    assert controls["group_identity_lifecycle"]["status"] == "GAP"
    assert controls["capability_projection_freshness"]["status"] == "IMPLEMENTED"
    assert all(
        item["status"] == "IMPLEMENTED" or item["gap"]
        for item in controls.values()
    )


def test_audit_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = build_oa_identity_lifecycle_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["lifecycle_readiness"] == "BLOCKED"
    assert result["checks"]["required_evidence_present"] is False
    assert result["checks"]["current_lifecycle_classification_observed"] is False
    assert len(result["issues"]) == 11
    assert {item["category"] for item in result["issues"]} == {
        "evidence_missing",
        "lifecycle_classification_drift",
    }


def test_audit_reports_classification_drift(tmp_path: Path) -> None:
    subject = tmp_path / "services/nex-oa/nex_oa/subjects.py"
    membership = tmp_path / "services/nex-oa/nex_oa/memberships.py"
    sessions = tmp_path / "services/nex-oa/nex_oa/sessions.py"
    subject.parent.mkdir(parents=True)
    subject.write_text(
        "def update_subject_status(): pass\n"
        "class OaGroup: pass\n"
        "password_login = True\n"
        "identity:bootstrap\n",
        encoding="utf-8",
    )
    membership.write_text(
        "def update_membership_status(): pass\n"
        '"oa_session_issuance": True\n'
        '"password_login": True\n',
        encoding="utf-8",
    )
    sessions.write_text("def revoke_sessions_for_subject(): pass\n", encoding="utf-8")
    (subject.parent / "identity_lifecycle_service.py").write_text(
        "def transition_subject(): pass\n"
        "def transition_membership(): pass\n"
        'subject_path = "/subjects/{subject_id}/lifecycle"\n'
        'membership_path = "/memberships/{subject_id}/lifecycle"\n',
        encoding="utf-8",
    )
    (subject.parent / "identity_lifecycle_repository.py").write_text(
        "def _revoke_sql_sessions(): pass\n"
        "table = 'oa_user_sessions'\n",
        encoding="utf-8",
    )
    migration = tmp_path / "database/nex-oa/migrations/0001.sql"
    migration.parent.mkdir(parents=True)
    migration.write_text("CREATE TABLE oa_groups ();\n", encoding="utf-8")

    result = build_oa_identity_lifecycle_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["current_lifecycle_classification_observed"] is False
    assert result["issues"][-1] == {"category": "lifecycle_classification_drift"}


def test_helpers_cover_present_missing_and_control_shapes(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("token\n", encoding="utf-8")
    ref = RequiredEvidence("sample", "evidence.txt", "token")

    assert _inspect_evidence(tmp_path, ref)["present"] is True
    assert _read_text(path) == "token\n"
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _control("sample", "GAP", "reason") == {
        "control_id": "sample",
        "status": "GAP",
        "gap": "reason",
    }


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_identity_lifecycle_audit()

    assert "lifecycle_audit=pass" in runner.summary_line(passing)
    assert "controls=8" in runner.summary_line(passing)
    assert "gaps=2" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_oa_identity_lifecycle_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "stale=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_oa_identity_lifecycle_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
