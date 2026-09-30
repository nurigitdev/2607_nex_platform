from __future__ import annotations

import pytest

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.provider_retry import (
    build_provider_retry_policy,
    compute_retry_delay,
    execute_with_provider_retry,
)
import run_mo_provider_retry_executor as runner


def _route_error(
    *,
    retryable: bool = True,
    kind: str = "connection_error",
) -> ProviderRouteError:
    return ProviderRouteError(
        503,
        "mo.remote_provider_unavailable",
        "Remote provider unavailable.",
        retryable=retryable,
        degraded=retryable,
        failure_kind=kind,
    )


def test_executor_returns_first_attempt_success_without_sleep() -> None:
    delays: list[float] = []

    result = execute_with_provider_retry(
        lambda: "ok",
        policy=build_provider_retry_policy("embedding"),
        sleeper=delays.append,
    )

    assert result.value == "ok"
    assert result.attempt_count == 1
    assert result.retry_count == 0
    assert delays == []


def test_executor_retries_transient_failures_with_injected_backoff() -> None:
    attempts = 0
    delays: list[float] = []
    events = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _route_error()
        return "ok"

    result = execute_with_provider_retry(
        operation,
        policy=build_provider_retry_policy("embedding"),
        sleeper=delays.append,
        jitter=lambda: 1.0,
        on_retry=events.append,
    )

    assert result.value == "ok"
    assert result.attempt_count == 3
    assert result.retry_count == 2
    assert delays == [0.25, 0.5]
    assert [event.next_attempt_number for event in events] == [2, 3]
    assert events[0].to_safe_summary()["failure_kind"] == "connection_error"


def test_executor_raises_last_failure_when_budget_is_exhausted() -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise _route_error()

    with pytest.raises(ProviderRouteError) as exc_info:
        execute_with_provider_retry(
            operation,
            policy=build_provider_retry_policy("generation"),
            sleeper=delays.append,
            jitter=lambda: 0.0,
        )

    assert attempts == 2
    assert delays == [0.0]
    assert exc_info.value.error_code == "mo.remote_provider_unavailable"


def test_executor_does_not_retry_non_retryable_or_ambiguous_generation() -> None:
    for failure in (
        _route_error(retryable=False),
        _route_error(kind="read_timeout"),
        _route_error(kind="malformed_response"),
    ):
        attempts = 0

        def operation() -> None:
            nonlocal attempts
            attempts += 1
            raise failure

        with pytest.raises(ProviderRouteError):
            execute_with_provider_retry(
                operation,
                policy=build_provider_retry_policy("generation"),
                sleeper=lambda _: pytest.fail("unexpected sleep"),
            )
        assert attempts == 1


def test_retry_delay_honors_caps_and_retry_after() -> None:
    policy = build_provider_retry_policy("embedding")

    assert compute_retry_delay(
        policy, attempt_number=8, jitter=lambda: 1.0
    ) == 2.0
    assert compute_retry_delay(
        policy,
        attempt_number=1,
        retry_after_seconds=20.0,
        jitter=lambda: pytest.fail("unexpected jitter"),
    ) == 5.0
    assert compute_retry_delay(
        policy,
        attempt_number=1,
        retry_after_seconds=-1.0,
        jitter=lambda: 0.5,
    ) == 0.125


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempt_number": 0, "jitter": lambda: 0.5},
        {"attempt_number": 1, "jitter": lambda: -0.1},
        {"attempt_number": 1, "jitter": lambda: 1.1},
    ],
)
def test_retry_delay_rejects_invalid_inputs(kwargs) -> None:
    with pytest.raises(ValueError):
        compute_retry_delay(build_provider_retry_policy("embedding"), **kwargs)


def test_executor_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_executor()
    assert passing["status"] == "PASS"
    assert "attempts=3" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_retry_executor", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=5/5" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_executor",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
