from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from nex_ag.audit_evidence_api import register_audit_evidence_routes
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_ag.resilience_performance import (
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_resilience_performance_policy,
)
from nex_ag.resilience_performance_operations import (
    AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH,
    AG_RESILIENCE_PERFORMANCE_OPERATIONS_SCHEMA_VERSION,
    build_ag_resilience_performance_operations_projection,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


class _Pool:
    def __init__(
        self,
        *,
        checked_out: int,
        checked_in: int,
        overflow: int,
    ) -> None:
        self._checked_out = checked_out
        self._checked_in = checked_in
        self._overflow = overflow

    def checkedout(self) -> int:
        return self._checked_out

    def checkedin(self) -> int:
        return self._checked_in

    def overflow(self) -> int:
        return self._overflow


def _engine(
    *,
    checked_out: int,
    checked_in: int,
    overflow: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        pool=_Pool(
            checked_out=checked_out,
            checked_in=checked_in,
            overflow=overflow,
        )
    )


def _projection(
    *,
    api_engine: object | None,
    worker_engine: object | None,
    admission: dict[str, object] | None = None,
    source: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_ag_resilience_performance_operations_projection(
        policy=build_ag_resilience_performance_policy({}),
        admission_snapshot=admission
        or {
            "rejected_total": 0,
            "in_flight": 0,
        },
        source_snapshot=source
        or {
            "timed_out_total": 0,
            "failed_total": 0,
            "slow_total": 0,
        },
        api_engine=api_engine,
        worker_engine=worker_engine,
        request_trace_id="a" * 32,
        checked_at="2026-09-20T09:00:00Z",
    )


def _headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{'b' * 32}-00f067aa0ba902b7-01",
    }


def test_projection_reports_ready_safe_pool_metrics_and_budget() -> None:
    projection = _projection(
        api_engine=_engine(checked_out=3, checked_in=2, overflow=-2),
        worker_engine=_engine(checked_out=1, checked_in=1),
    )

    assert projection["projection_schema_version"] == (
        AG_RESILIENCE_PERFORMANCE_OPERATIONS_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["policy_id"] == "ag-resilience-performance-v1"
    assert projection["request_trace_id"] == "a" * 32
    pools = projection["runtime"]["database_pools"]
    assert pools["api"] == {
        "status": "READY",
        "workload": "api",
        "configured_pool_size": 5,
        "configured_max_overflow": 10,
        "configured_capacity": 15,
        "checked_out": 3,
        "checked_in": 2,
        "overflow_in_use": 0,
        "available_capacity": 12,
        "utilization_percent": 20.0,
    }
    assert projection["attention_reasons"] == []
    assert projection["privacy"] == {
        "database_url_included": False,
        "credentials_included": False,
        "sql_included": False,
        "raw_errors_included": False,
    }
    assert "nuri1004" not in str(projection)


def test_projection_reports_attention_for_saturation_and_runtime_counters() -> None:
    projection = _projection(
        api_engine=_engine(checked_out=15, checked_in=0, overflow=10),
        worker_engine=None,
        admission={"rejected_total": 2},
        source={
            "timed_out_total": 1,
            "failed_total": 1,
            "slow_total": 3,
        },
    )

    assert projection["projection_status"] == "ATTENTION"
    assert projection["runtime"]["database_pools"]["api"]["status"] == (
        "ATTENTION"
    )
    assert projection["attention_reasons"] == [
        "DATABASE_API_POOL_SATURATED",
        "ADMISSION_REJECTIONS",
        "SOURCE_TIMEOUTS",
        "SOURCE_FAILURES",
        "SOURCE_SLOW_OPERATIONS",
    ]


def test_projection_distinguishes_not_configured_and_unavailable_metrics() -> None:
    not_configured = _projection(api_engine=None, worker_engine=None)
    unavailable = _projection(
        api_engine=SimpleNamespace(pool=SimpleNamespace()),
        worker_engine=_engine(checked_out=-1, checked_in=0),
    )

    assert not_configured["projection_status"] == "NOT_CONFIGURED"
    assert unavailable["projection_status"] == "DEGRADED"
    assert unavailable["attention_reasons"] == [
        "DATABASE_API_POOL_METRICS_UNAVAILABLE",
        "DATABASE_WORKER_POOL_METRICS_UNAVAILABLE",
    ]
    assert "checkedout" not in str(unavailable)


def test_projection_rejects_non_integer_or_invalid_pool_capacity_safely() -> None:
    boolean_metric = _projection(
        api_engine=_engine(checked_out=True, checked_in=0),
        worker_engine=_engine(checked_out=0, checked_in=0),
    )
    policy = build_ag_resilience_performance_policy({})
    policy["database"]["api"]["capacity"] = 0
    invalid_capacity = build_ag_resilience_performance_operations_projection(
        policy=policy,
        admission_snapshot={"rejected_total": 0},
        source_snapshot={},
        api_engine=_engine(checked_out=0, checked_in=0),
        worker_engine=None,
    )

    assert boolean_metric["projection_status"] == "DEGRADED"
    assert invalid_capacity["projection_status"] == "DEGRADED"


def test_protected_route_remains_available_while_admission_is_saturated() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    guard = AgConcurrencyAdmissionGuard(max_in_flight=1, wait_timeout_ms=1)
    executor = AgSourceIsolationExecutor(
        timeout_ms=10,
        slow_operation_ms=5,
        max_workers=1,
    )
    runtime = SimpleNamespace(
        api_engine=_engine(checked_out=1, checked_in=4),
        worker_engine=_engine(checked_out=0, checked_in=2),
    )
    register_audit_evidence_routes(
        app,
        event_store=InMemoryOperationalEventStore(),
        export_store=OperatorEvidenceExportStore(),
        admission_guard=guard,
        source_executor=executor,
        persistence_runtime=runtime,
    )
    client = TestClient(app)
    try:
        unauthorized = client.get(AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH)
        with guard.admit("held_for_diagnostics"):
            response = client.get(
                AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH,
                headers=_headers(),
            )
    finally:
        executor.close()

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["projection_status"] == "READY"
    assert response.json()["runtime"]["admission"]["in_flight"] == 1
    assert response.json()["request_trace_id"] == "b" * 32
