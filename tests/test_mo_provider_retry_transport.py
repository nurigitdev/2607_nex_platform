from __future__ import annotations

import httpx
import pytest

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.provider_retry import build_provider_retry_policy
from nex_mo.provider_retry_after import parse_retry_after_seconds
from nex_mo.provider_retry_transport import execute_remote_json_request_with_retry
from nex_mo.provider_transport import (
    RemoteProviderFailureDecision,
    execute_remote_json_request,
)
from nex_mo.remote_provider import (
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
)
import run_mo_provider_retry_transport as runner


def _embedding_config():
    return build_remote_embedding_execution_config(
        {"NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings"}
    )


def test_transport_retries_transient_status_and_honors_retry_after() -> None:
    calls = 0
    delays: list[float] = []
    events = []

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1.5"})
        return httpx.Response(200, json={"ok": True})

    result = execute_remote_json_request_with_retry(
        _embedding_config(),
        json_payload={},
        requester=requester,
        error_code_prefix="mo.remote_embedding",
        retry_policy=build_provider_retry_policy("embedding"),
        sleeper=delays.append,
        jitter=lambda: pytest.fail("Retry-After should bypass jitter"),
        on_retry=events.append,
    )

    assert result == {"ok": True}
    assert calls == 2
    assert delays == [1.5]
    assert events[0].failure_kind == "throttled"


def test_retry_transport_uses_default_execution_sources_on_first_success() -> None:
    result = execute_remote_json_request_with_retry(
        _embedding_config(),
        json_payload={},
        requester=lambda *args, **kwargs: httpx.Response(200, json={"ok": True}),
        error_code_prefix="mo.remote_embedding",
        retry_policy=build_provider_retry_policy("embedding"),
    )

    assert result == {"ok": True}


def test_transport_preserves_single_attempt_when_policy_is_absent() -> None:
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(ProviderRouteError):
        execute_remote_json_request(
            _embedding_config(),
            json_payload={},
            requester=requester,
            error_code_prefix="mo.remote_embedding",
        )
    assert calls == 1


def test_transport_does_not_retry_non_retryable_status() -> None:
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(400)

    with pytest.raises(ProviderRouteError) as exc_info:
        execute_remote_json_request_with_retry(
            _embedding_config(),
            json_payload={},
            requester=requester,
            error_code_prefix="mo.remote_embedding",
            retry_policy=build_provider_retry_policy("embedding"),
            sleeper=lambda _: pytest.fail("unexpected sleep"),
        )
    assert calls == 1
    assert exc_info.value.retryable is False


def test_generation_read_timeout_remains_single_attempt() -> None:
    config = build_remote_generation_execution_config(
        {"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://provider.invalid/chat"}
    )
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("ambiguous")

    with pytest.raises(ProviderRouteError) as exc_info:
        execute_remote_json_request_with_retry(
            config,
            json_payload={},
            requester=requester,
            error_code_prefix="mo.remote_generation",
            retry_policy=build_provider_retry_policy("generation"),
            sleeper=lambda _: pytest.fail("unexpected sleep"),
        )
    assert calls == 1
    assert exc_info.value.failure_kind == "read_timeout"


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        (" 2.5 ", 2.5),
        ("-1", None),
        ("tomorrow", None),
    ],
)
def test_retry_after_parser_accepts_only_non_negative_delta_seconds(
    value, expected
) -> None:
    assert parse_retry_after_seconds(value) == expected


def test_failure_decision_projects_safe_retry_after_hint() -> None:
    decision = RemoteProviderFailureDecision(
        "throttled",
        "mo.remote_embedding_throttled",
        429,
        "Remote provider throttled the request.",
        True,
        True,
        upstream_status_code=429,
        retry_after_seconds=3.0,
    )

    assert decision.to_route_error().retry_after_seconds == 3.0
    assert decision.to_safe_summary()["retry_after_seconds"] == 3.0


def test_retry_transport_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_transport()
    assert passing["status"] == "PASS"
    assert "requests=2" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_retry_transport", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=4/4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_transport",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
