import run_oa_effective_authorization_session as runner


def test_effective_authorization_session_evidence_passes() -> None:
    result = runner.run_oa_effective_authorization_session()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 6,
        "passed_check_count": 6,
        "claim_role_count": 2,
        "claim_scope_count": 1,
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    assert runner.main(["--summary"]) == 0
    assert "session=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_effective_authorization_session",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
