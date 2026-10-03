import run_oa_authorization_repository as runner


def test_repository_evidence_passes() -> None:
    result = runner.run_oa_authorization_repository()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 6,
        "passed_check_count": 6,
        "record_count": 4,
        "event_count": 4,
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    assert runner.main(["--summary"]) == 0
    assert "repository=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_authorization_repository",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
