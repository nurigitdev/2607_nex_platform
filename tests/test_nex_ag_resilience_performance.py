from __future__ import annotations

import base64
import json

import pytest

from nex_ag.resilience_performance import (
    AG_RESILIENCE_PERFORMANCE_POLICY_ID,
    AG_RESILIENCE_PERFORMANCE_POLICY_SCHEMA_VERSION,
    AgResiliencePerformancePolicyError,
    AgStablePaginationError,
    build_ag_resilience_performance_policy,
    build_stable_keyset_page,
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


def _record(identity: str, timestamp: str) -> dict[str, str]:
    return {"event_id": identity, "created_at": timestamp}


def _cursor(payload: object) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def test_stable_descending_keyset_pagination_ignores_newer_insert() -> None:
    records = [
        _record("event-a", "2026-09-20T01:00:00Z"),
        _record("event-b", "2026-09-20T02:00:00Z"),
        _record("event-c", "2026-09-20T03:00:00Z"),
        _record("event-d", "2026-09-20T04:00:00Z"),
    ]

    first = build_stable_keyset_page(
        records,
        limit=2,
        cursor=None,
        timestamp_field="created_at",
        identity_field="event_id",
    )
    second = build_stable_keyset_page(
        records + [_record("event-new", "2026-09-20T05:00:00Z")],
        limit=2,
        cursor=first["pagination"]["next_cursor"],
        timestamp_field="created_at",
        identity_field="event_id",
    )

    assert [item["event_id"] for item in first["items"]] == [
        "event-d",
        "event-c",
    ]
    assert first["pagination"]["has_more"] is True
    assert [item["event_id"] for item in second["items"]] == [
        "event-b",
        "event-a",
    ]
    assert second["pagination"]["has_more"] is False
    assert second["pagination"]["next_cursor"] is None


def test_stable_ascending_pagination_and_tie_breaker() -> None:
    records = [
        _record("event-b", "2026-09-20T01:00:00Z"),
        _record("event-a", "2026-09-20T01:00:00Z"),
        _record("event-c", "2026-09-20T02:00:00Z"),
    ]

    first = build_stable_keyset_page(
        records,
        limit=1,
        cursor=" ",
        timestamp_field="created_at",
        identity_field="event_id",
        sort=" ASC ",
    )
    second = build_stable_keyset_page(
        records,
        limit=2,
        cursor=first["pagination"]["next_cursor"],
        timestamp_field="created_at",
        identity_field="event_id",
        sort="asc",
    )

    assert [item["event_id"] for item in first["items"]] == ["event-a"]
    assert [item["event_id"] for item in second["items"]] == [
        "event-b",
        "event-c",
    ]


def test_stable_page_omits_malformed_records_and_reports_count() -> None:
    page = build_stable_keyset_page(
        [
            _record("event-valid", "2026-09-20T01:00:00Z"),
            {"event_id": "", "created_at": "2026-09-20T02:00:00Z"},
            {"event_id": "event-no-time", "created_at": None},
            {"event_id": 1, "created_at": "2026-09-20T03:00:00Z"},
        ],
        limit=10,
        cursor=None,
        timestamp_field="created_at",
        identity_field="event_id",
    )

    assert page["items"] == [
        _record("event-valid", "2026-09-20T01:00:00Z")
    ]
    assert page["pagination"]["invalid_record_count"] == 3
    assert page["pagination"]["stable_ordering"] == [
        "created_at",
        "event_id",
    ]


@pytest.mark.parametrize("limit", [True, "1", 0, 501])
def test_stable_page_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(AgStablePaginationError) as exc_info:
        build_stable_keyset_page(
            [],
            limit=limit,  # type: ignore[arg-type]
            cursor=None,
            timestamp_field="created_at",
            identity_field="event_id",
        )

    assert exc_info.value.error_code == "ag.resilience.pagination_limit_invalid"
    assert exc_info.value.status_code == 400
    assert str(exc_info.value) == exc_info.value.detail


def test_stable_page_rejects_invalid_max_limit_and_sort() -> None:
    with pytest.raises(AgStablePaginationError):
        build_stable_keyset_page(
            [],
            limit=1,
            cursor=None,
            timestamp_field="created_at",
            identity_field="event_id",
            max_limit=0,
        )
    with pytest.raises(AgStablePaginationError) as exc_info:
        build_stable_keyset_page(
            [],
            limit=1,
            cursor=None,
            timestamp_field="created_at",
            identity_field="event_id",
            sort="sideways",
        )
    assert exc_info.value.error_code == "ag.resilience.pagination_sort_invalid"


@pytest.mark.parametrize(
    "cursor",
    [
        "x" * 1025,
        "not!base64",
        _cursor(["not", "a", "mapping"]),
        _cursor({"version": 1}),
        _cursor(
            {
                "version": 2,
                "sort": "desc",
                "timestamp": "2026-09-20T01:00:00Z",
                "identity": "event-a",
            }
        ),
        _cursor(
            {
                "version": 1,
                "sort": "asc",
                "timestamp": "2026-09-20T01:00:00Z",
                "identity": "event-a",
            }
        ),
        _cursor(
            {
                "version": 1,
                "sort": "desc",
                "timestamp": "",
                "identity": "event-a",
            }
        ),
        _cursor(
            {
                "version": 1,
                "sort": "desc",
                "timestamp": "2026-09-20T01:00:00Z",
                "identity": 1,
            }
        ),
    ],
)
def test_stable_page_rejects_invalid_or_incompatible_cursor(cursor: str) -> None:
    with pytest.raises(AgStablePaginationError) as exc_info:
        build_stable_keyset_page(
            [],
            limit=1,
            cursor=cursor,
            timestamp_field="created_at",
            identity_field="event_id",
        )

    assert exc_info.value.error_code == "ag.resilience.pagination_cursor_invalid"
    assert "not!base64" not in exc_info.value.detail
