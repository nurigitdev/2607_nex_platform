from __future__ import annotations

from pathlib import Path

from nex_oa.credential_session_security_audit import (
    RequiredEvidence,
    _control,
    _inspect_evidence,
    _read_text,
    build_oa_credential_session_security_audit,
)
import run_oa_credential_session_security_audit as runner


def test_repository_security_audit_quantifies_strengths_and_gaps() -> None:
    result = build_oa_credential_session_security_audit()

    assert result["status"] == "PASS"
    assert result["security_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "control_count": 8,
        "implemented_count": 5,
        "partial_count": 0,
        "gap_count": 3,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["raw_credentials_or_session_ids_in_evidence"] is False


def test_security_observations_distinguish_strengths_from_gaps() -> None:
    observations = build_oa_credential_session_security_audit()["observations"]

    assert all(
        observations[name]
        for name in (
            "pbkdf2_salted_hashing_present",
            "constant_time_password_compare_present",
            "private_payload_rejection_present",
            "bounded_session_ttl_present",
            "session_introspection_revocation_present",
        )
    )
    assert all(
        observations[name] is False
        for name in (
            "credential_rotation_present",
            "random_session_identifier_present",
            "auth_event_emission_present",
        )
    )
    assert observations["failed_attempt_mutation_present"] is True
    assert observations["adaptive_rehash_present"] is True


def test_security_audit_fails_closed_without_repository(tmp_path: Path) -> None:
    result = build_oa_credential_session_security_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["security_readiness"] == "BLOCKED"
    assert result["checks"]["required_evidence_present"] is False
    assert result["checks"]["implemented_security_strengths_observed"] is False
    assert result["checks"]["security_gaps_observed"] is True
    assert result["issues"][-1] == {"category": "security_classification_drift"}


def test_security_audit_reports_gap_classification_drift(tmp_path: Path) -> None:
    credential = tmp_path / "services/nex-oa/nex_oa/credentials.py"
    session = tmp_path / "services/nex-oa/nex_oa/sessions.py"
    login = tmp_path / "services/nex-oa/nex_oa/user_login.py"
    credential.parent.mkdir(parents=True)
    credential.write_text(
        "failed_attempt_count = failed_attempt_count + 1\n"
        "def change_password(): pass\n"
        "argon2 rehash\n",
        encoding="utf-8",
    )
    session.write_text(
        "uuid4()\nOperationalEventEmitter\n",
        encoding="utf-8",
    )
    login.write_text("OperationalEventEmitter\n", encoding="utf-8")

    result = build_oa_credential_session_security_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["security_gaps_observed"] is False
    assert result["issues"][-1] == {"category": "security_classification_drift"}


def test_helpers_cover_present_missing_and_control_shapes(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("token\n", encoding="utf-8")
    ref = RequiredEvidence("sample", "evidence.txt", "token")

    assert _inspect_evidence(tmp_path, ref)["present"] is True
    assert _read_text(path) == "token\n"
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _control("sample", "PARTIAL", "reason")["gap"] == "reason"


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_credential_session_security_audit()

    assert "security_audit=pass" in runner.summary_line(passing)
    assert "controls=8" in runner.summary_line(passing)
    assert "gaps=3" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_oa_credential_session_security_audit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "partial=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_oa_credential_session_security_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
