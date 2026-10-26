from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.approvals import SqlAlchemyApprovalWorkItemRepository


class ApprovalEventDeliveryError(RuntimeError):
    def __init__(self, detail: str, *, retryable: bool = True) -> None:
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


class SqlAlchemyApprovalEventDeliveryStore:
    """Transport adapter over the existing WC approval tables."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._approvals = SqlAlchemyApprovalWorkItemRepository(session_factory)

    def list_pending(self, *, limit: int = 32) -> list[dict[str, Any]]:
        events = self._approvals.list_pending_approval_events(limit=limit)
        deliveries: list[dict[str, Any]] = []
        for outbox in events:
            tenant_id = str(outbox["tenant_id"])
            work_item_id = str(outbox["approval_work_item_id"])
            work_item = self._approvals.get(
                tenant_id=tenant_id,
                approval_work_item_id=work_item_id,
            )
            decision = self._approvals.get_decision(
                tenant_id=tenant_id,
                approval_work_item_id=work_item_id,
            )
            if work_item is None or decision is None:
                raise ApprovalEventDeliveryError(
                    "WC approval outbox lineage is incomplete.", retryable=False
                )
            deliveries.append(
                {
                    "schema_version": "wc_approval_delivery.v1",
                    "outbox_id": str(outbox["outbox_id"]),
                    "work_item": dict(work_item),
                    "decision": dict(decision),
                    "event": dict(outbox["event_payload"]),
                }
            )
        return deliveries

    def mark_delivered(self, delivery: Mapping[str, Any]) -> None:
        event = _mapping(delivery.get("event"), "event")
        work_item = _mapping(delivery.get("work_item"), "work_item")
        params = {
            "tenant_id": _required(event.get("tenant_id"), "tenant_id"),
            "outbox_id": _required(delivery.get("outbox_id"), "outbox_id"),
            "event_id": _required(event.get("event_id"), "event_id"),
            "approval_work_item_id": _required(
                work_item.get("approval_work_item_id"), "approval_work_item_id"
            ),
            "updated_at": datetime.now(UTC),
        }
        try:
            with self._session_factory() as session:
                updated = session.execute(text(_MARK_DELIVERED_SQL), params)
                if int(updated.rowcount or 0) != 1:
                    state = session.execute(
                        text(_DELIVERY_STATE_SQL), params
                    ).scalar_one_or_none()
                    if state != "DELIVERED":
                        raise ApprovalEventDeliveryError(
                            "WC approval delivery state changed concurrently."
                        )
                session.commit()
        except ApprovalEventDeliveryError:
            raise
        except SQLAlchemyError as exc:
            raise ApprovalEventDeliveryError(
                "WC approval delivery persistence is unavailable."
            ) from exc


class HttpAeApprovalEventClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ApprovalEventDeliveryError(
                "AE API base URL is required.", retryable=False
            )
        if not isinstance(service_token, str) or not service_token.strip():
            raise ApprovalEventDeliveryError(
                "WC to AE service token is required.", retryable=False
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
        ):
            raise ApprovalEventDeliveryError(
                "Approval delivery timeout is invalid.", retryable=False
            )
        self._url = f"{base_url.rstrip('/')}/internal/v1/approval-decision-events"
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def deliver(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(delivery)
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            problem = _http_problem(exc)
            diagnostic = ": ".join(
                str(problem[name])
                for name in ("error_code", "detail")
                if problem.get(name)
            )
            raise ApprovalEventDeliveryError(
                f"AE approval event delivery failed with HTTP {exc.code}"
                f"{f' ({diagnostic})' if diagnostic else ''}.",
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ApprovalEventDeliveryError(
                "AE approval event delivery is unavailable."
            ) from exc
        event = _mapping(payload.get("event"), "event")
        if (
            not isinstance(result, Mapping)
            or result.get("event_id") != event.get("event_id")
            or result.get("outbox_id") != payload.get("outbox_id")
        ):
            raise ApprovalEventDeliveryError(
                "AE approval event receipt binding is invalid.", retryable=False
            )
        return dict(result)


def deliver_pending_approval_events(
    *,
    store: SqlAlchemyApprovalEventDeliveryStore,
    client: HttpAeApprovalEventClient,
    limit: int = 32,
) -> dict[str, int]:
    pending = store.list_pending(limit=limit)
    delivered = 0
    for item in pending:
        client.deliver(item)
        store.mark_delivered(item)
        delivered += 1
    return {"pending_count": len(pending), "delivered_count": delivered}


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApprovalEventDeliveryError(
            f"WC approval delivery {field} is invalid.", retryable=False
        )
    return value


def _http_problem(exc: HTTPError) -> dict[str, str]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    return {
        name: value[:512]
        for name in ("error_code", "detail")
        if isinstance((value := payload.get(name)), str)
    }


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalEventDeliveryError(
            f"WC approval delivery {field} is invalid.", retryable=False
        )
    return value.strip()


_MARK_DELIVERED_SQL = """
UPDATE wc_approval_outbox
SET delivery_state = 'DELIVERED', updated_at = :updated_at
WHERE tenant_id = :tenant_id AND outbox_id = :outbox_id
  AND event_id = :event_id
  AND approval_work_item_id = :approval_work_item_id
  AND delivery_state = 'PENDING'
"""

_DELIVERY_STATE_SQL = """
SELECT delivery_state FROM wc_approval_outbox
WHERE tenant_id = :tenant_id AND outbox_id = :outbox_id
  AND event_id = :event_id
  AND approval_work_item_id = :approval_work_item_id
"""
