from __future__ import annotations

import httpx
import pytest

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.remote_provider import (
    _execute_remote_request_with_retry,
    build_remote_embedding_execution_config,
    execute_remote_embedding_request,
)
import run_mo_provider_retry_wiring as runner


def test_embedding_execution_retries_transient_transport_failure() -> None:
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    result = execute_remote_embedding_request(
        {"inputs": ["hello"]},
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings",
            "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0",
        },
        requester=requester,
    )

    assert calls == 2
    assert result["data"][0]["embedding"] == [0.1]


def test_execution_honors_capability_attempt_override() -> None:
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderRouteError):
        execute_remote_embedding_request(
            {"inputs": ["hello"]},
            environ={
                "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings",
                "NEX_MO_EMBEDDING_MAX_ATTEMPTS": "2",
                "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0",
            },
            requester=requester,
        )
    assert calls == 2


def test_retry_helper_uses_production_defaults_without_custom_requester(
    monkeypatch,
) -> None:
    config = build_remote_embedding_execution_config(
        {"NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings"}
    )
    captured = {}

    def fake_executor(*args, **kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "nex_mo.remote_provider.execute_remote_json_request_with_retry",
        fake_executor,
    )
    assert _execute_remote_request_with_retry(
        config,
        json_payload={},
        requester=None,
        error_code_prefix="mo.remote_embedding",
        environ={},
    ) == {"ok": True}
    assert "sleeper" not in captured
    assert captured["retry_policy"].capability == "embedding"


def test_retry_wiring_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_wiring()
    assert passing["status"] == "PASS"
    assert "capabilities=3" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_retry_wiring", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=4/4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_wiring",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
