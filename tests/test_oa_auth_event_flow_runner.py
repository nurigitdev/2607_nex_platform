import run_oa_auth_event_flow as runner


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_auth_event_flow()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.main(["--summary"]) == 0
    assert "checks=7/7" in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_auth_event_flow", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1
