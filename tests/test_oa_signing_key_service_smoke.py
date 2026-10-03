from __future__ import annotations

import json

import run_oa_signing_key_service as runner


def test_signing_key_service_smoke_passes() -> None:
    result = runner.run_oa_signing_key_service()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())


def test_signing_key_service_smoke_cli_paths(monkeypatch, capsys) -> None:
    assert runner.main(["--summary"]) == 0
    assert "service=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        runner,
        "run_oa_signing_key_service",
        lambda: {"status": "FAIL", "next_slice": "blocked"},
    )
    assert runner.main([]) == 1
