from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
import os
from typing import Any, Protocol

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_ag.platform_alert_repository import (
    NOTIFICATION_STATES,
    PlatformAlertRepositoryError,
    SqlAlchemyPlatformAlertRepository,
)
from nex_ag.platform_alerting import (
    ALERT_STATES,
    AlertRecord,
    PlatformAlertError,
    acknowledge_alert,
    suppress_alert,
)
from nex_ag.platform_slo import SloPolicy, default_platform_slo_policies, evaluate_slo
from nex_ag.service_auth import authorize_ag_service_or_admin_request
from nex_runtime import OperationalEventEmitter, problem_response, trace_id_from_headers

PLATFORM_OBSERVABILITY_DASHBOARD_PATH = "/admin/v1/observability/dashboard"
PLATFORM_OBSERVABILITY_SLO_PATH = "/admin/v1/observability/slos"
PLATFORM_OBSERVABILITY_ALERTS_PATH = "/admin/v1/observability/alerts"
PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH = "/admin/v1/observability/notifications"
PLATFORM_OBSERVABILITY_SCHEMA_VERSION = "ag_platform_observability_dashboard.v1"


class ObservabilitySignalProvider(Protocol):
    def list_signals(
        self, *, policy: SloPolicy, evaluated_at: str
    ) -> Sequence[Any]: ...


class EmptyObservabilitySignalProvider:
    def list_signals(self, *, policy: SloPolicy, evaluated_at: str) -> Sequence[Any]:
        return ()


class InMemoryPlatformAlertOperationsRepository:
    def __init__(self) -> None:
        self.alerts: dict[str, AlertRecord] = {}

    def get_alert(self, alert_id: str) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def list_alerts(
        self,
        *,
        service_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[AlertRecord]:
        if state is not None and state not in ALERT_STATES:
            raise PlatformAlertRepositoryError("alert.filter_invalid", "alert state filter is invalid")
        _bounded_limit(limit, "alert.filter_invalid")
        items = [
            item
            for item in self.alerts.values()
            if (service_id is None or item.service_id == service_id)
            and (state is None or item.state == state)
        ]
        return sorted(items, key=lambda item: (item.last_observed_at, item.alert_id), reverse=True)[:limit]

    def list_notifications(
        self, *, alert_id: str | None = None, state: str | None = None, limit: int = 100
    ) -> list[Any]:
        if state is not None and state not in NOTIFICATION_STATES:
            raise PlatformAlertRepositoryError(
                "alert.notification_filter_invalid", "notification state filter is invalid"
            )
        _bounded_limit(limit, "alert.notification_filter_invalid")
        return []

    def update_alert(self, alert: AlertRecord, *, expected_state_revision: int) -> AlertRecord:
        current = self.alerts.get(alert.alert_id)
        if current is None or current.state_revision != expected_state_revision:
            raise PlatformAlertRepositoryError(
                "alert.revision_conflict", "alert changed or no longer exists"
            )
        self.alerts[alert.alert_id] = alert
        return alert


class PlatformObservabilityOperations:
    def __init__(
        self,
        repository: Any,
        *,
        policies: Sequence[SloPolicy] | None = None,
        signal_provider: ObservabilitySignalProvider | None = None,
        notification_mode: str = "local_only",
    ) -> None:
        if notification_mode not in {
            "local_only",
            "private_network",
            "internet_connected",
        }:
            raise ValueError("notification mode is invalid")
        self.repository = repository
        self.policies = tuple(policies or default_platform_slo_policies())
        self.signal_provider = signal_provider or EmptyObservabilitySignalProvider()
        self.notification_mode = notification_mode

    def list_slo_evaluations(self, *, observed_at: str) -> list[dict[str, Any]]:
        return [
            evaluate_slo(
                policy,
                self.signal_provider.list_signals(
                    policy=policy, evaluated_at=observed_at
                ),
                evaluated_at=observed_at,
            )
            for policy in self.policies
        ]

    def list_alerts(
        self,
        *,
        service_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            alert.to_wire()
            for alert in self.repository.list_alerts(
                service_id=service_id, state=state, limit=limit
            )
        ]

    def list_notifications(
        self,
        *,
        alert_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            {
                **item.__dict__,
                "external_activation": (
                    "LOCAL_ONLY"
                    if item.channel == "LOCAL"
                    else "EXTERNAL_NOT_ACTIVATED"
                ),
                "private_payload_included": False,
            }
            for item in self.repository.list_notifications(
                alert_id=alert_id, state=state, limit=limit
            )
        ]

    def build_dashboard(self, *, observed_at: str) -> dict[str, Any]:
        evaluations = self.list_slo_evaluations(observed_at=observed_at)
        alerts = self.list_alerts(limit=200)
        notifications = self.list_notifications(limit=200)
        alert_counts = _counts(alerts, "state")
        notification_counts = _counts(notifications, "delivery_state")
        unhealthy = sum(
            1 for item in evaluations if item["status"] in {"AT_RISK", "BREACHED", "NO_DATA"}
        )
        active_alerts = sum(
            alert_counts.get(state, 0)
            for state in ("PENDING", "FIRING", "ACKNOWLEDGED", "SUPPRESSED")
        )
        delivery_issues = sum(
            notification_counts.get(state, 0)
            for state in ("RETRY_WAIT", "BLOCKED", "DEAD_LETTER")
        )
        return {
            "schema_version": PLATFORM_OBSERVABILITY_SCHEMA_VERSION,
            "observed_at": _wire_timestamp(_timestamp(observed_at)),
            "status": "DEGRADED" if unhealthy or active_alerts or delivery_issues else "HEALTHY",
            "notification_mode": self.notification_mode,
            "external_activation": (
                "LOCAL_ONLY"
                if self.notification_mode == "local_only"
                else "EXTERNAL_NOT_ACTIVATED"
            ),
            "summary": {
                "slo_policy_count": len(evaluations),
                "unhealthy_slo_count": unhealthy,
                "active_alert_count": active_alerts,
                "delivery_issue_count": delivery_issues,
            },
            "slo_evaluations": evaluations,
            "alerts": alerts,
            "notifications": notifications,
            "alert_state_counts": alert_counts,
            "notification_state_counts": notification_counts,
            "private_payload_included": False,
        }

    def acknowledge(
        self, alert_id: str, *, operator_ref_hash: str, changed_at: str
    ) -> dict[str, Any]:
        current = self._required_alert(alert_id)
        changed = acknowledge_alert(
            current,
            operator_ref_hash=operator_ref_hash,
            acknowledged_at=changed_at,
        )
        return self.repository.update_alert(
            changed, expected_state_revision=current.state_revision
        ).to_wire()

    def suppress(
        self,
        alert_id: str,
        *,
        duration_seconds: int,
        reason_code: str,
        changed_at: str,
    ) -> dict[str, Any]:
        if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 60 <= duration_seconds <= 86_400:
            raise PlatformAlertError(
                "alert.suppression_duration_invalid",
                "suppression duration must be between 60 and 86400 seconds",
            )
        current = self._required_alert(alert_id)
        changed = _timestamp(changed_at)
        suppressed = suppress_alert(
            current,
            suppression_until=_wire_timestamp(changed + timedelta(seconds=duration_seconds)),
            reason_code=reason_code,
            changed_at=_wire_timestamp(changed),
        )
        return self.repository.update_alert(
            suppressed, expected_state_revision=current.state_revision
        ).to_wire()

    def _required_alert(self, alert_id: str):
        alert = self.repository.get_alert(alert_id)
        if alert is None:
            raise PlatformAlertRepositoryError(
                "alert.not_found", "platform alert was not found"
            )
        return alert


def build_platform_observability_operations(
    persistence: Any,
    *,
    notification_mode: str | None = None,
) -> PlatformObservabilityOperations:
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is None:
        if getattr(persistence, "mode", None) != "memory":
            raise RuntimeError("platform observability requires SQL persistence")
        repository: Any = InMemoryPlatformAlertOperationsRepository()
    else:
        repository = SqlAlchemyPlatformAlertRepository(session_factory)
    return PlatformObservabilityOperations(
        repository,
        notification_mode=notification_mode
        or os.environ.get("NEX_NOTIFICATION_MODE", "local_only"),
    )


def register_platform_observability_routes(
    app: FastAPI,
    *,
    operations: PlatformObservabilityOperations,
    audit_event_store: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))
    emitter = (
        OperationalEventEmitter(service_id="nex-ag", store=audit_event_store)
        if audit_event_store is not None
        else None
    )

    @app.get(PLATFORM_OBSERVABILITY_DASHBOARD_PATH, response_model=None)
    def get_dashboard(request: Request, authorization: str | None = Header(default=None)):
        if problem := _authorize(request, authorization):
            return problem
        try:
            payload = operations.build_dashboard(observed_at=_wire_timestamp(selected_clock()))
            return {**payload, "request_trace_id": trace_id_from_headers(request)}
        except Exception as exc:
            return _problem(request, exc)

    @app.get(PLATFORM_OBSERVABILITY_SLO_PATH, response_model=None)
    def get_slos(request: Request, authorization: str | None = Header(default=None)):
        if problem := _authorize(request, authorization):
            return problem
        try:
            return {
                "items": operations.list_slo_evaluations(
                    observed_at=_wire_timestamp(selected_clock())
                ),
                "request_trace_id": trace_id_from_headers(request),
            }
        except Exception as exc:
            return _problem(request, exc)

    @app.get(PLATFORM_OBSERVABILITY_ALERTS_PATH, response_model=None)
    def get_alerts(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = Query(default=None),
        state: str | None = Query(default=None),
        limit: int = Query(default=100),
    ):
        if problem := _authorize(request, authorization):
            return problem
        try:
            return {
                "items": operations.list_alerts(
                    service_id=service_id, state=state, limit=limit
                ),
                "request_trace_id": trace_id_from_headers(request),
            }
        except Exception as exc:
            return _problem(request, exc)

    @app.get(PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH, response_model=None)
    def get_notifications(
        request: Request,
        authorization: str | None = Header(default=None),
        alert_id: str | None = Query(default=None),
        state: str | None = Query(default=None),
        limit: int = Query(default=100),
    ):
        if problem := _authorize(request, authorization):
            return problem
        try:
            return {
                "items": operations.list_notifications(
                    alert_id=alert_id, state=state, limit=limit
                ),
                "request_trace_id": trace_id_from_headers(request),
            }
        except Exception as exc:
            return _problem(request, exc)

    @app.post(PLATFORM_OBSERVABILITY_ALERTS_PATH + "/{alert_id}/acknowledge", response_model=None)
    def post_acknowledge(
        alert_id: str,
        payload: Mapping[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        if problem := _authorize(request, authorization):
            return problem
        try:
            changed_at = _wire_timestamp(selected_clock())
            alert = operations.acknowledge(
                alert_id,
                operator_ref_hash=str(payload.get("operator_ref_hash") or ""),
                changed_at=changed_at,
            )
            _audit(
                emitter,
                "ag.platform_alert.acknowledged",
                alert,
                request=request,
                created_at=changed_at,
            )
            return {"alert": alert, "request_trace_id": trace_id_from_headers(request)}
        except Exception as exc:
            return _problem(request, exc)

    @app.post(PLATFORM_OBSERVABILITY_ALERTS_PATH + "/{alert_id}/suppress", response_model=None)
    def post_suppress(
        alert_id: str,
        payload: Mapping[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        if problem := _authorize(request, authorization):
            return problem
        try:
            changed_at = _wire_timestamp(selected_clock())
            alert = operations.suppress(
                alert_id,
                duration_seconds=payload.get("duration_seconds"),
                reason_code=str(payload.get("reason_code") or ""),
                changed_at=changed_at,
            )
            _audit(
                emitter,
                "ag.platform_alert.suppressed",
                alert,
                request=request,
                created_at=changed_at,
            )
            return {"alert": alert, "request_trace_id": trace_id_from_headers(request)}
        except Exception as exc:
            return _problem(request, exc)


def _audit(
    emitter: OperationalEventEmitter | None,
    event_type: str,
    alert: Mapping[str, Any],
    *,
    request: Request,
    created_at: str,
) -> None:
    if emitter is None:
        return
    emitter.safe_emit(
        event_type=event_type,
        severity="INFO",
        message="Platform alert operator action recorded.",
        trace_id=trace_id_from_headers(request),
        subject_ref={"type": "platform_alert", "id": str(alert["alert_id"])},
        details={"state": alert["state"], "state_revision": alert["state_revision"]},
        created_at=created_at,
    )


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    return authorize_ag_service_or_admin_request(
        request,
        authorization,
        admin_error_code="AG_PLATFORM_OBSERVABILITY_ADMIN_ROLE_REQUIRED",
        admin_error_detail="Platform observability operations require an admin user role.",
    )


def _problem(request: Request, exc: Exception) -> JSONResponse:
    error_code = str(getattr(exc, "error_code", "observability.unavailable"))
    detail = str(getattr(exc, "detail", "platform observability is unavailable"))
    if error_code == "alert.not_found":
        status_code = 404
    elif error_code in {
        "alert.revision_conflict",
        "alert.acknowledge_state_invalid",
        "alert.suppression_state_invalid",
    }:
        status_code = 409
    elif error_code == "alert.persistence_unavailable" or error_code == "observability.unavailable":
        status_code = 503
        detail = "platform observability is unavailable"
    else:
        status_code = 422
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="Platform observability operation failed",
        detail=detail,
        type_uri="https://nex-platform.local/problems/platform-observability-operation-failed",
    )


def _counts(items: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item[field])
        counts[value] = counts.get(value, 0) + 1
    return counts


def _bounded_limit(limit: int, error_code: str) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise PlatformAlertRepositoryError(error_code, "operation limit is invalid")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("observed_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
