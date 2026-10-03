from __future__ import annotations

import json

import run_oa_signed_token_repository as runner


def test_repository_smoke_passes() -> None:
    result = runner.run_oa_signed_token_repository()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["cleanup_residue_count"] == 0


def test_repository_smoke_cli_paths(monkeypatch, capsys) -> None:
    assert runner.main(["--summary"]) == 0
    assert "repository=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        runner,
        "run_oa_signed_token_repository",
        lambda: {"status": "FAIL", "next_slice": "blocked"},
    )
    assert runner.main([]) == 1
