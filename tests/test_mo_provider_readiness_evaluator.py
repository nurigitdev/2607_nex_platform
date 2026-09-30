from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

import nex_mo.provider_readiness_evaluator as evaluator
from nex_mo.provider_readiness_evaluator import evaluate_provider_readiness_plan
from nex_mo.provider_readiness_plan import build_provider_readiness_probe_plan
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES
import run_mo_provider_readiness_evaluator as runner


CHECKED_AT = "2026-09-30T00:00:00Z"


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:9111",
    }


def test_mock_evaluation_is_ready_without_network() -> None:
    def forbidden_requester(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("mock mode must not use the network")

    snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan({}),
        checked_at=CHECKED_AT,
        requester=forbidden_requester,
    )

    assert snapshot.readiness_status == "READY"
    assert all(route.status == "READY" for route in snapshot.routes)
    assert all(route.source == "mock_registry" for route in snapshot.routes)
    assert all(route.latency_ms == 0 for route in snapshot.routes)


def test_live_evaluation_runs_three_active_probes_and_records_latency() -> None:
    calls: list[tuple[str, str]] = []
    clock_values = iter((1.0, 1.005, 2.0, 2.01, 3.0, 3.015))

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append((method, url))
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(200, json={"results": [{"score": 0.9}]})
        return httpx.Response(200, json={"data": [{"id": "Qwen3.5-4B"}]})

    snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan(live_env()),
        checked_at=CHECKED_AT,
        requester=requester,
        clock=lambda: next(clock_values),
    )

    assert snapshot.readiness_status == "READY"
    assert [method for method, _ in calls] == ["POST", "POST", "GET"]
    assert [route.latency_ms for route in snapshot.routes] == [5, 10, 15]
    assert all(route.source == "active_preflight" for route in snapshot.routes)


@pytest.mark.parametrize(
    ("failure_code", "expected"),
    [
        ("endpoint_not_configured", ("UNAVAILABLE", False, False)),
        ("expected_model_missing", ("UNAVAILABLE", False, False)),
        ("http_status_400", ("UNAVAILABLE", False, False)),
        ("http_status_429", ("DEGRADED", True, True)),
        ("http_status_503", ("DEGRADED", True, True)),
        ("ConnectError", ("DEGRADED", True, True)),
        ("response_not_json_object", ("DEGRADED", True, True)),
        ("unexpected_code", ("UNKNOWN", False, False)),
        ("http_status_bad", ("UNKNOWN", False, False)),
    ],
)
def test_preflight_failure_classification(
    failure_code: str,
    expected: tuple[str, bool, bool],
) -> None:
    status, retryable, degraded, observed_code = evaluator._preflight_health_decision(
        {"status": "FAIL", "failure_code": failure_code}
    )

    assert (status, retryable, degraded) == expected
    assert observed_code == failure_code


def test_preflight_pass_and_unsafe_failure_code_are_normalized() -> None:
    assert evaluator._preflight_health_decision({"status": "PASS"}) == (
        "READY",
        False,
        False,
        None,
    )
    assert evaluator._preflight_health_decision(
        {"status": "FAIL", "failure_code": "private endpoint: http://secret"}
    ) == ("UNKNOWN", False, False, "provider_preflight_failed")
    assert evaluator._preflight_health_decision(
        {"status": "FAIL", "failure_code": None}
    ) == ("UNKNOWN", False, False, "provider_preflight_failed")


def test_unconfigured_live_endpoint_is_unavailable_and_fails_readiness() -> None:
    snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan({"NEX_MO_PROVIDER_MODE": "live"}),
        checked_at=CHECKED_AT,
        requester=lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )

    assert snapshot.readiness_status == "NOT_READY"
    assert all(route.status == "UNAVAILABLE" for route in snapshot.routes)
    assert all(route.failure_code == "endpoint_not_configured" for route in snapshot.routes)


def test_registry_unavailable_and_missing_preflight_config_fail_closed() -> None:
    unavailable_route = replace(DEFAULT_PROVIDER_ROUTES[0], status="NOT_READY")
    mock_plan = build_provider_readiness_probe_plan(
        {}, routes=(unavailable_route, *DEFAULT_PROVIDER_ROUTES[1:])
    )
    mock_snapshot = evaluate_provider_readiness_plan(mock_plan, checked_at=CHECKED_AT)
    assert mock_snapshot.routes[0].status == "UNAVAILABLE"
    assert mock_snapshot.routes[0].failure_code == "provider_route_not_ready"

    live_plan = build_provider_readiness_probe_plan(live_env())
    missing_config_target = replace(live_plan.targets[0], preflight_config=None)
    incomplete_plan = replace(
        live_plan,
        targets=(missing_config_target, *live_plan.targets[1:]),
    )
    snapshot = evaluate_provider_readiness_plan(
        incomplete_plan,
        checked_at=CHECKED_AT,
        requester=lambda *args, **kwargs: httpx.Response(200, json={}),
    )
    assert snapshot.routes[0].status == "UNKNOWN"
    assert snapshot.routes[0].failure_code == "provider_preflight_config_missing"


def test_unexpected_evaluator_exception_is_redacted_and_fails_closed() -> None:
    snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan(live_env()),
        checked_at=CHECKED_AT,
        requester=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("http://private.local secret-key")
        ),
        clock=lambda: 1.0,
    )

    assert snapshot.readiness_status == "NOT_READY"
    assert all(route.status == "UNKNOWN" for route in snapshot.routes)
    assert all(
        route.failure_code == "provider_preflight_evaluation_failed"
        for route in snapshot.routes
    )


def test_evaluator_uses_current_time_when_not_injected(monkeypatch) -> None:
    monkeypatch.setattr(evaluator, "utc_now", lambda: CHECKED_AT)
    snapshot = evaluate_provider_readiness_plan(build_provider_readiness_probe_plan({}))
    assert snapshot.checked_at == CHECKED_AT


def test_evaluator_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_evaluator()
    assert "readiness_evaluator=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_readiness_evaluator", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "probes=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_evaluator",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
