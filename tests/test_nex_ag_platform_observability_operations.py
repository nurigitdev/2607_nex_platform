from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ag.platform_alert_repository import (
    PlatformAlertRepositoryError,
    SqlAlchemyPlatformAlertRepository,
)
from nex_ag.platform_alerting import AlertRecord
from nex_ag.platform_observability_operations import (
    PLATFORM_OBSERVABILITY_ALERTS_PATH,
    PLATFORM_OBSERVABILITY_DASHBOARD_PATH,
    PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH,
    PLATFORM_OBSERVABILITY_SLO_PATH,
    InMemoryPlatformAlertOperationsRepository,
    PlatformObservabilityOperations,
    _timestamp,
    _wire_timestamp,
    build_platform_observability_operations,
    register_platform_observability_routes,
)
from nex_ag.platform_slo import SloPolicy
from nex_runtime import (
    InMemoryOperationalEventStore,
    ObservabilitySignal,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)
from run_s148_alert_persistence_restart import SQLITE_SCHEMA

NOW = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
TRACE_ID = "a" * 32
OPERATOR_HASH = "sha256:" + "e" * 64


@pytest.fixture
def repository() -> SqlAlchemyPlatformAlertRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return SqlAlchemyPlatformAlertRepository(factory)


def _alert(suffix: str = "a", *, state: str = "FIRING") -> AlertRecord:
    return AlertRecord(
        alert_id=f"alert:{suffix}",
        dedup_key="sha256:" + suffix * 64,
        rule_id=f"rule:{suffix}",
        policy_id=f"slo:{suffix}",
        service_id="nex-cx" if suffix != "b" else "nex-ag",
        state=state,
        severity="CRITICAL",
        reason_code="SLO_CRITICAL_BURN",
        occurrence_count=1,
        first_observed_at="2026-10-08T02:59:00Z",
        last_observed_at="2026-10-08T02:59:00Z",
        accountable_owner="platform-operations",
        runbook_ref="runbook:nex-cx:index",
    )


def _intent(channel: str, suffix: str) -> dict[str, str]:
    return {
        "channel": channel,
        "route_alias": f"route-{suffix}",
        "idempotency_key_hash": "sha256:" + suffix * 64,
        "payload_hash": "sha256:" + "f" * 64,
    }


def _seed(repository: SqlAlchemyPlatformAlertRepository) -> None:
    repository.insert_alert_with_notifications(
        _alert("a"),
        [_intent("LOCAL", "a"), _intent("EXTERNAL_WEBHOOK", "c")],
        created_at="2026-10-08T02:59:00Z",
    )
    repository.insert_alert_with_notifications(
        _alert("b"), [], created_at="2026-10-08T02:59:01Z"
    )


def _admin_headers() -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _client(repository, *, event_store=None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_platform_observability_routes(
        app,
        operations=PlatformObservabilityOperations(
            repository, notification_mode="internet_connected"
        ),
        audit_event_store=event_store,
        clock=lambda: NOW,
    )
    return TestClient(app)


def test_repository_lists_alerts_with_bounded_filters(repository) -> None:
    _seed(repository)
    assert [item.alert_id for item in repository.list_alerts()] == ["alert:a", "alert:b"]
    assert [item.alert_id for item in repository.list_alerts(service_id="nex-cx")] == ["alert:a"]
    assert len(repository.list_alerts(state="FIRING", limit=1)) == 1
    for kwargs in ({"state": "BAD"}, {"limit": 0}, {"limit": True}):
        with pytest.raises(PlatformAlertRepositoryError) as exc_info:
            repository.list_alerts(**kwargs)
        assert exc_info.value.error_code == "alert.filter_invalid"
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.list_alerts(service_id="bad value")
    assert exc_info.value.error_code == "alert.identifier_invalid"


def test_dashboard_is_metadata_only_and_exposes_no_data(repository) -> None:
    _seed(repository)
    operations = PlatformObservabilityOperations(
        repository, notification_mode="internet_connected"
    )
    dashboard = operations.build_dashboard(observed_at="2026-10-08T03:00:00Z")
    assert dashboard["status"] == "DEGRADED"
    assert dashboard["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert dashboard["summary"] == {
        "slo_policy_count": 5,
        "unhealthy_slo_count": 5,
        "active_alert_count": 2,
        "delivery_issue_count": 0,
    }
    assert {item["status"] for item in dashboard["slo_evaluations"]} == {"NO_DATA"}
    assert dashboard["alert_state_counts"] == {"FIRING": 2}
    assert dashboard["notification_state_counts"] == {"PENDING": 2}
    assert dashboard["private_payload_included"] is False
    assert operations.list_notifications(state="PENDING")[1]["external_activation"] in {
        "LOCAL_ONLY",
        "EXTERNAL_NOT_ACTIVATED",
    }


def test_operations_acknowledge_suppress_and_not_found(repository) -> None:
    _seed(repository)
    operations = PlatformObservabilityOperations(repository)
    acknowledged = operations.acknowledge(
        "alert:a", operator_ref_hash=OPERATOR_HASH, changed_at="2026-10-08T03:00:00Z"
    )
    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["state_revision"] == 2
    suppressed = operations.suppress(
        "alert:b",
        duration_seconds=300,
        reason_code="MAINTENANCE_WINDOW",
        changed_at="2026-10-08T03:00:00Z",
    )
    assert suppressed["state"] == "SUPPRESSED"
    assert suppressed["suppression_until"] == "2026-10-08T03:05:00Z"
    for invalid in (0, True, 86_401):
        with pytest.raises(Exception) as exc_info:
            operations.suppress(
                "alert:a",
                duration_seconds=invalid,
                reason_code="MAINTENANCE_WINDOW",
                changed_at="2026-10-08T03:00:00Z",
            )
        assert getattr(exc_info.value, "error_code") == "alert.suppression_duration_invalid"
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        operations.acknowledge(
            "alert:missing", operator_ref_hash=OPERATOR_HASH, changed_at="2026-10-08T03:00:00Z"
        )
    assert exc_info.value.error_code == "alert.not_found"


def test_protected_api_reads_dashboard_lists_and_slos(repository) -> None:
    _seed(repository)
    client = _client(repository)
    dashboard = client.get(
        PLATFORM_OBSERVABILITY_DASHBOARD_PATH, headers=_admin_headers()
    )
    alerts = client.get(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "?service_id=nex-cx&state=FIRING&limit=10",
        headers=_admin_headers(),
    )
    notifications = client.get(
        PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH + "?state=PENDING",
        headers=_admin_headers(),
    )
    slos = client.get(PLATFORM_OBSERVABILITY_SLO_PATH, headers=_admin_headers())
    assert dashboard.status_code == alerts.status_code == notifications.status_code == slos.status_code == 200
    assert dashboard.json()["request_trace_id"] == TRACE_ID
    assert len(alerts.json()["items"]) == 1
    assert len(notifications.json()["items"]) == 2
    assert len(slos.json()["items"]) == 5


def test_protected_api_operator_actions_emit_trace_linked_audit(repository) -> None:
    _seed(repository)
    events = InMemoryOperationalEventStore()
    client = _client(repository, event_store=events)
    acknowledged = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge",
        headers=_admin_headers(),
        json={"operator_ref_hash": OPERATOR_HASH},
    )
    suppressed = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:b/suppress",
        headers=_admin_headers(),
        json={"duration_seconds": 300, "reason_code": "MAINTENANCE_WINDOW"},
    )
    assert acknowledged.status_code == suppressed.status_code == 200
    assert acknowledged.json()["alert"]["state"] == "ACKNOWLEDGED"
    assert suppressed.json()["alert"]["state"] == "SUPPRESSED"
    recorded = events.list_events(trace_id=TRACE_ID)
    assert {item["event_type"] for item in recorded} == {
        "ag.platform_alert.acknowledged",
        "ag.platform_alert.suppressed",
    }
    assert all(item["subject_ref"]["type"] == "platform_alert" for item in recorded)


def test_api_auth_validation_conflict_and_not_found(repository) -> None:
    _seed(repository)
    client = _client(repository)
    viewer = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    ).access_token
    assert client.get(PLATFORM_OBSERVABILITY_DASHBOARD_PATH).status_code == 401
    assert client.get(
        PLATFORM_OBSERVABILITY_DASHBOARD_PATH,
        headers={"Authorization": f"Bearer {viewer}"},
    ).status_code == 403
    service = issue_mock_service_token(service_id="nex-oa", audience="nex-ag").access_token
    assert client.get(
        PLATFORM_OBSERVABILITY_DASHBOARD_PATH,
        headers={"Authorization": f"Bearer {service}"},
    ).status_code == 200
    assert client.get(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "?state=BAD", headers=_admin_headers()
    ).status_code == 422
    assert client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:missing/acknowledge",
        headers=_admin_headers(),
        json={"operator_ref_hash": OPERATOR_HASH},
    ).status_code == 404
    first = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge",
        headers=_admin_headers(),
        json={"operator_ref_hash": OPERATOR_HASH},
    )
    second = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge",
        headers=_admin_headers(),
        json={"operator_ref_hash": OPERATOR_HASH},
    )
    assert first.status_code == 200 and second.status_code == 409


def test_api_redacts_persistence_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyPlatformAlertRepository(sessionmaker(bind=engine))
    response = _client(repository).get(
        PLATFORM_OBSERVABILITY_DASHBOARD_PATH, headers=_admin_headers()
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "platform observability is unavailable"
    assert "SQL" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", PLATFORM_OBSERVABILITY_SLO_PATH, None),
        ("get", PLATFORM_OBSERVABILITY_ALERTS_PATH, None),
        ("get", PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH, None),
        ("post", PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge", {"operator_ref_hash": OPERATOR_HASH}),
        ("post", PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/suppress", {"duration_seconds": 300, "reason_code": "MAINTENANCE_WINDOW"}),
    ],
)
def test_each_observability_route_rejects_missing_auth(
    repository, method: str, path: str, payload
) -> None:
    client = _client(repository)
    response = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
    assert response.status_code == 401


class _FailingOperations:
    def build_dashboard(self, **kwargs):
        raise RuntimeError("private dashboard failure")

    def list_slo_evaluations(self, **kwargs):
        raise RuntimeError("private SLO failure")

    def list_alerts(self, **kwargs):
        raise RuntimeError("private alert failure")

    def list_notifications(self, **kwargs):
        raise RuntimeError("private notification failure")

    def acknowledge(self, *args, **kwargs):
        raise RuntimeError("private acknowledge failure")

    def suppress(self, *args, **kwargs):
        raise RuntimeError("private suppress failure")


def test_all_api_failures_are_redacted() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_platform_observability_routes(
        app, operations=_FailingOperations(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    client = TestClient(app)
    cases = (
        ("get", PLATFORM_OBSERVABILITY_DASHBOARD_PATH, None),
        ("get", PLATFORM_OBSERVABILITY_SLO_PATH, None),
        ("get", PLATFORM_OBSERVABILITY_ALERTS_PATH, None),
        ("get", PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH, None),
        ("post", PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge", {}),
        ("post", PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/suppress", {}),
    )
    for method, path, payload in cases:
        response = (
            getattr(client, method)(path, headers=_admin_headers(), json=payload)
            if payload is not None
            else getattr(client, method)(path, headers=_admin_headers())
        )
        assert response.status_code == 503
        assert "private" not in response.text


class _HealthySignalProvider:
    def list_signals(self, *, policy: SloPolicy, evaluated_at: str):
        return tuple(
            ObservabilitySignal(
                signal_id=f"signal:nex-ag:delivery:{index}",
                service_id="nex-ag",
                signal_kind="METRIC",
                signal_name="ag.notification.delivery",
                observed_at=f"2026-10-08T02:59:{index:02d}Z",
                severity="INFO",
                status="HEALTHY",
                correlation_key="ag:notification",
                trace_id=None,
                request_id=None,
                resource_type="notification",
                resource_id="local",
                measurements={"success_ratio": 1.0},
                reason_codes=("DELIVERY_HEALTHY",),
                safe_attributes={"state": "READY"},
            )
            for index in (1, 2, 3)
        )


def test_healthy_local_dashboard_projection(repository) -> None:
    policy = SloPolicy(
        "slo:nex-ag:notification",
        1,
        "nex-ag",
        "ag.notification",
        "ag.notification.delivery",
        "success_ratio",
        "GTE",
        1.0,
        0.99,
        1.0,
        5.0,
        300,
        3,
        60,
        "platform-ops",
        "runbook:nex-ag:notification",
    )
    operations = PlatformObservabilityOperations(
        repository,
        policies=(policy,),
        signal_provider=_HealthySignalProvider(),
        notification_mode="local_only",
    )
    dashboard = operations.build_dashboard(observed_at="2026-10-08T03:00:00Z")
    assert dashboard["status"] == "HEALTHY"
    assert dashboard["external_activation"] == "LOCAL_ONLY"
    assert dashboard["summary"]["unhealthy_slo_count"] == 0


@dataclass
class _Persistence:
    api_session_factory: object | None
    mode: str | None = None


def test_factory_mode_and_time_validation(repository, monkeypatch) -> None:
    with pytest.raises(RuntimeError):
        build_platform_observability_operations(_Persistence(None))
    memory = build_platform_observability_operations(_Persistence(None, "memory"))
    assert isinstance(memory.repository, InMemoryPlatformAlertOperationsRepository)
    built = build_platform_observability_operations(
        _Persistence(repository._session_factory), notification_mode="private_network"
    )
    assert built.notification_mode == "private_network"
    monkeypatch.setenv("NEX_NOTIFICATION_MODE", "internet_connected")
    assert build_platform_observability_operations(
        _Persistence(repository._session_factory)
    ).notification_mode == "internet_connected"
    with pytest.raises(ValueError):
        PlatformObservabilityOperations(repository, notification_mode="automatic")
    for value in ("bad", "2026-10-08T03:00:00", None):
        with pytest.raises(ValueError):
            _timestamp(value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _wire_timestamp(datetime(2026, 10, 8, 3, 0))


def test_memory_profile_repository_is_bounded_and_optimistic() -> None:
    repository = InMemoryPlatformAlertOperationsRepository()
    alert = _alert()
    repository.alerts[alert.alert_id] = alert
    assert repository.get_alert(alert.alert_id) == alert
    assert repository.get_alert("alert:missing") is None
    assert repository.list_alerts(service_id="nex-cx", state="FIRING") == [alert]
    assert repository.list_alerts(service_id="nex-ag") == []
    assert repository.list_notifications() == []
    changed = AlertRecord(**{**alert.__dict__, "state": "ACKNOWLEDGED", "state_revision": 2})
    assert repository.update_alert(changed, expected_state_revision=1) == changed
    with pytest.raises(PlatformAlertRepositoryError):
        repository.update_alert(changed, expected_state_revision=1)
    for kwargs in ({"state": "BAD"}, {"limit": 0}):
        with pytest.raises(PlatformAlertRepositoryError):
            repository.list_alerts(**kwargs)
    for kwargs in ({"state": "BAD"}, {"limit": True}):
        with pytest.raises(PlatformAlertRepositoryError):
            repository.list_notifications(**kwargs)
