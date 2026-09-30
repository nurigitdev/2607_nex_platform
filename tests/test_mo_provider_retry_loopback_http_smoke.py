from __future__ import annotations

import json

import pytest

import run_mo_provider_retry_loopback_http_smoke as runner


def test_loopback_http_smoke_executes_real_transport_retries() -> None:
    evidence = runner.run_mo_provider_retry_loopback_http_smoke()

    assert evidence["status"] == "PASS"
    assert evidence["observations"]["attempt_counts"] == {
        "embedding": 2,
        "generation": 2,
        "reranking": 2,
    }
    assert evidence["observations"]["retry_counts"] == {
        "embedding": 1,
        "generation": 1,
        "reranking": 1,
    }
    assert "private-loopback-key" not in json.dumps(evidence)


def test_loopback_helper_rejects_unknown_path_and_redaction() -> None:
    with pytest.raises(ValueError, match="unexpected loopback"):
        runner._capability_for_path("/unexpected")
    with pytest.raises(ValueError, match="leaked"):
        runner._assert_redacted({"value": "private-loopback-key"}, 12345)


def test_loopback_http_smoke_cli_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_loopback_http_smoke()
    assert "requests=6" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_loopback_http_smoke",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "checks=6/6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_loopback_http_smoke",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
