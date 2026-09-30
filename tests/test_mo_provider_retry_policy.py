from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from nex_mo.provider_retry import (
    ProviderRetryPolicy,
    build_provider_retry_policy,
    decide_provider_retry,
)
from nex_mo.provider_transport import (
    RemoteProviderFailureDecision,
    classify_remote_provider_exception,
)
import run_mo_provider_retry_policy as runner


def _failure(*, kind: str = "connection_error", retryable: bool = True):
    return RemoteProviderFailureDecision(
        failure_kind=kind,
        error_code="mo.remote_provider_unavailable",
        status_code=503,
        detail="Remote provider unavailable.",
        retryable=retryable,
        degraded=retryable,
    )


def test_default_and_environment_retry_policies_are_bounded() -> None:
    assert build_provider_retry_policy("embedding").max_attempts == 3
    assert build_provider_retry_policy("reranking").max_attempts == 3
    assert build_provider_retry_policy("generation").max_attempts == 2

    policy = build_provider_retry_policy(
        "generation",
        {
            "NEX_MO_GENERATION_MAX_ATTEMPTS": "4",
            "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0.5",
            "NEX_MO_RETRY_MAX_DELAY_SECONDS": "3",
            "NEX_MO_RETRY_AFTER_MAX_SECONDS": "4",
        },
    )
    assert policy.to_safe_summary() == {
        "capability": "generation",
        "max_attempts": 4,
        "base_delay_seconds": 0.5,
        "max_delay_seconds": 3.0,
        "retry_after_max_seconds": 4.0,
        "generation_ambiguous_replay_blocked": True,
    }


@pytest.mark.parametrize(
    "exception,failure_kind",
    [
        (httpx.ConnectTimeout("connect"), "connect_timeout"),
        (httpx.ReadTimeout("read"), "read_timeout"),
        (httpx.WriteTimeout("write"), "write_timeout"),
        (httpx.PoolTimeout("pool"), "pool_timeout"),
        (httpx.TimeoutException("generic"), "timeout"),
    ],
)
def test_timeout_failure_taxonomy_is_precise(exception, failure_kind) -> None:
    decision = classify_remote_provider_exception(
        exception,
        error_code_prefix="mo.remote_generation",
    )

    assert decision.failure_kind == failure_kind
    assert decision.error_code == "mo.remote_generation_timeout"
    assert decision.retryable is True
    assert "connect" not in decision.to_safe_summary()


def test_retry_decision_honors_failure_budget_and_generation_safety() -> None:
    embedding = build_provider_retry_policy("embedding")
    generation = build_provider_retry_policy("generation")

    assert decide_provider_retry(embedding, _failure(), attempt_number=1).retry
    assert not decide_provider_retry(
        embedding, _failure(retryable=False), attempt_number=1
    ).retry
    exhausted = decide_provider_retry(embedding, _failure(), attempt_number=3)
    assert exhausted.reason == "attempt_budget_exhausted"
    ambiguous = decide_provider_retry(
        generation,
        _failure(kind="read_timeout"),
        attempt_number=1,
    )
    assert ambiguous.to_safe_summary()["reason"] == (
        "generation_ambiguous_replay_blocked"
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: build_provider_retry_policy("unknown"),
        lambda: build_provider_retry_policy(
            "embedding", {"NEX_MO_EMBEDDING_MAX_ATTEMPTS": "0"}
        ),
        lambda: build_provider_retry_policy(
            "embedding", {"NEX_MO_RETRY_BASE_DELAY_SECONDS": "-1"}
        ),
        lambda: ProviderRetryPolicy("embedding", 2, -1.0, 1.0, 1.0),
        lambda: ProviderRetryPolicy("embedding", 2, 2.0, 1.0, 1.0),
        lambda: ProviderRetryPolicy("embedding", 2, 0.0, 1.0, -1.0),
    ],
)
def test_invalid_retry_policy_configuration_fails_closed(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_invalid_attempt_number_fails_closed() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        decide_provider_retry(
            build_provider_retry_policy("embedding"),
            _failure(),
            attempt_number=0,
        )


def test_policy_validates_direct_capability_and_attempt_limit() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        ProviderRetryPolicy("unknown", 1, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="max_attempts"):
        replace(build_provider_retry_policy("embedding"), max_attempts=6)


def test_retry_policy_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_policy()
    assert passing["status"] == "PASS"
    assert "policies=3" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_retry_policy", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=4/4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_policy",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
