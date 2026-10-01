import run_oa_credential_rotation as runner


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_credential_rotation()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.main(["--summary"]) == 0
    assert "checks=7/7" in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_credential_rotation", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1
