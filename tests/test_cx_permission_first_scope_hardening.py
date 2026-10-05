from __future__ import annotations

from pathlib import Path

import run_cx_permission_first_scope_hardening as hardening


def test_repository_scope_hardening_passes() -> None:
    result = hardening.run_cx_permission_first_scope_hardening()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["decision"] == {
        "denial_status_code": 404,
        "denial_retryable": False,
        "denied_identifier_exposed": False,
        "downstream_calls_after_denial": 0,
        "next_slice": "1354",
    }


def test_scope_hardening_fails_closed_without_sources(tmp_path: Path) -> None:
    result = hardening.run_cx_permission_first_scope_hardening(tmp_path)
    assert result["status"] == "FAIL"
    assert len(result["issues"]) == len(hardening.REQUIRED_TOKENS)


def test_summary_main_and_read_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.py"
    source.write_text("value", encoding="utf-8")
    assert hardening._read_text(source) == "value"
    assert hardening._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "checks": {"a": True},
        "decision": {"denial_status_code": 404, "next_slice": "1354"},
    }
    assert hardening.summary_line(passing) == (
        "cx_permission_first_scope_hardening=pass checks=1 denial=404 next=1354"
    )
    assert hardening.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_permission_first_scope_hardening=fail issues=1"
    )
    monkeypatch.setattr(hardening, "run_cx_permission_first_scope_hardening", lambda: passing)
    assert hardening.main(["--summary"]) == 0
    assert "next=1354" in capsys.readouterr().out
    assert hardening.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        hardening,
        "run_cx_permission_first_scope_hardening",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert hardening.main([]) == 1
