from __future__ import annotations

import pytest

from nex_ag.resilience_performance import (
    AG_RESILIENCE_PERFORMANCE_POLICY_ID,
    AG_RESILIENCE_PERFORMANCE_POLICY_SCHEMA_VERSION,
    AgResiliencePerformancePolicyError,
    build_ag_resilience_performance_policy,
)


def test_default_policy_uses_existing_pool_and_bounded_defaults() -> None:
    policy = build_ag_resilience_performance_policy({})

    assert policy["policy_schema_version"] == (
        AG_RESILIENCE_PERFORMANCE_POLICY_SCHEMA_VERSION
    )
    assert policy["policy_id"] == AG_RESILIENCE_PERFORMANCE_POLICY_ID
    assert policy["query"] == {
        "default_page_size": 50,
        "max_page_size": 500,
        "hard_max_page_size": 500,
        "stable_ordering_required": True,
        "slow_operation_ms": 1000,
    }
    assert policy["admission"] == {
        "max_in_flight": 8,
        "wait_timeout_ms": 100,
        "overflow_action": "reject_retryable_503",
    }
    assert policy["source_isolation"]["timeout_ms"] == 2000
    assert policy["database"]["api"]["capacity"] == 15
    assert policy["database"]["worker"]["capacity"] == 6
    assert policy["bounded_smoke"] == {
        "request_count": 25,
        "concurrency": 4,
        "p95_budget_ms": 1500,
        "destructive": False,
    }


def test_policy_accepts_safe_environment_overrides() -> None:
    policy = build_ag_resilience_performance_policy(
        {
            "NEX_AG_DB_POOL_SIZE": "4",
            "NEX_AG_DB_MAX_OVERFLOW": "4",
            "NEX_AG_DB_WORKER_POOL_SIZE": "2",
            "NEX_AG_DB_WORKER_MAX_OVERFLOW": "1",
            "NEX_AG_PERF_DEFAULT_PAGE_SIZE": "20",
            "NEX_AG_PERF_MAX_PAGE_SIZE": "200",
            "NEX_AG_PERF_MAX_IN_FLIGHT": "6",
            "NEX_AG_PERF_ADMISSION_WAIT_MS": "75",
            "NEX_AG_PERF_SOURCE_TIMEOUT_MS": "3000",
            "NEX_AG_PERF_SLOW_OPERATION_MS": "1500",
            "NEX_AG_PERF_SMOKE_REQUEST_COUNT": "12",
            "NEX_AG_PERF_SMOKE_CONCURRENCY": "3",
            "NEX_AG_PERF_SMOKE_P95_BUDGET_MS": "2500",
        }
    )

    assert policy["query"]["default_page_size"] == 20
    assert policy["query"]["max_page_size"] == 200
    assert policy["admission"]["max_in_flight"] == 6
    assert policy["admission"]["wait_timeout_ms"] == 75
    assert policy["database"]["api"]["capacity"] == 8
    assert policy["database"]["worker"]["capacity"] == 3
    assert policy["bounded_smoke"]["request_count"] == 12


@pytest.mark.parametrize(
    ("environ", "error_code"),
    [
        (
            {"NEX_AG_PERF_DEFAULT_PAGE_SIZE": "501"},
            "ag.resilience.page_size_order_invalid",
        ),
        (
            {"NEX_AG_PERF_MAX_PAGE_SIZE": "501"},
            "ag.resilience.page_size_cap_exceeded",
        ),
        (
            {"NEX_AG_PERF_MAX_IN_FLIGHT": "16"},
            "ag.resilience.admission_exceeds_pool_capacity",
        ),
        (
            {"NEX_AG_PERF_SMOKE_CONCURRENCY": "9"},
            "ag.resilience.smoke_concurrency_exceeds_admission",
        ),
        (
            {
                "NEX_AG_PERF_SMOKE_REQUEST_COUNT": "3",
                "NEX_AG_PERF_SMOKE_CONCURRENCY": "4",
            },
            "ag.resilience.smoke_request_count_too_small",
        ),
        (
            {"NEX_AG_PERF_SLOW_OPERATION_MS": "2001"},
            "ag.resilience.slow_threshold_exceeds_timeout",
        ),
        (
            {"NEX_AG_PERF_SOURCE_TIMEOUT_MS": "30000"},
            "ag.resilience.source_timeout_exceeds_statement_timeout",
        ),
    ],
)
def test_policy_rejects_inconsistent_relationships(
    environ: dict[str, str],
    error_code: str,
) -> None:
    with pytest.raises(AgResiliencePerformancePolicyError) as exc_info:
        build_ag_resilience_performance_policy(environ)

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value) == exc_info.value.detail


@pytest.mark.parametrize("raw_value", ["invalid", "0", "-1"])
def test_policy_rejects_invalid_positive_integer(raw_value: str) -> None:
    with pytest.raises(AgResiliencePerformancePolicyError) as exc_info:
        build_ag_resilience_performance_policy(
            {"NEX_AG_PERF_MAX_IN_FLIGHT": raw_value}
        )

    assert exc_info.value.error_code == (
        "ag.resilience.performance_value_invalid"
    )


def test_empty_override_uses_default_and_small_pool_bounds_default_admission() -> None:
    policy = build_ag_resilience_performance_policy(
        {
            "NEX_AG_DB_POOL_SIZE": "2",
            "NEX_AG_DB_MAX_OVERFLOW": "1",
            "NEX_AG_PERF_MAX_IN_FLIGHT": "",
        }
    )

    assert policy["database"]["api"]["capacity"] == 3
    assert policy["admission"]["max_in_flight"] == 3


def test_disabled_statement_timeout_allows_larger_source_timeout() -> None:
    policy = build_ag_resilience_performance_policy(
        {
            "NEX_AG_DB_STATEMENT_TIMEOUT_MS": "0",
            "NEX_AG_PERF_SOURCE_TIMEOUT_MS": "60000",
            "NEX_AG_PERF_SLOW_OPERATION_MS": "5000",
        }
    )

    assert policy["database"]["api"]["statement_timeout_ms"] == 0
    assert policy["source_isolation"]["timeout_ms"] == 60000


def test_invalid_database_pool_config_is_normalized() -> None:
    with pytest.raises(AgResiliencePerformancePolicyError) as exc_info:
        build_ag_resilience_performance_policy({"NEX_AG_DB_POOL_SIZE": "bad"})

    assert exc_info.value.error_code == "ag.resilience.pool_config_invalid"
    assert "NEX_AG_DB_POOL_SIZE" in exc_info.value.detail
