from pathlib import Path

import run_oa_credential_session_security_boundary as boundary


def test_repository_boundary_passes() -> None:
    result = boundary.run_oa_credential_session_security_boundary()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["decision"]["password_hash"] == {
        "default": "argon2id.v1",
        "legacy_read": "pbkdf2_sha256.v1",
        "login_time_rehash": True,
    }
    assert result["quality_cadence"]["full_gate"] == "1231"


def test_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = boundary.run_oa_credential_session_security_boundary(tmp_path)
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_credential_session_boundary_failed"
    assert len(result["issues"]) == len(boundary.REQUIRED_EVIDENCE)


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = boundary.run_oa_credential_session_security_boundary()
    assert "hash=argon2id.v1" in boundary.summary_line(passing)
    assert "lockout=5/900" in boundary.summary_line(passing)
    assert "boundary=fail" in boundary.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        boundary,
        "run_oa_credential_session_security_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        boundary,
        "run_oa_credential_session_security_boundary",
        lambda: {"status": "FAIL"},
    )
    assert boundary.main([]) == 1

