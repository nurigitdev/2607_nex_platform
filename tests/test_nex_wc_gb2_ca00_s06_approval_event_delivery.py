from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from nex_wc.approval_event_delivery import (
    ApprovalEventDeliveryError,
    HttpAeApprovalEventClient,
    SqlAlchemyApprovalEventDeliveryStore,
    deliver_pending_approval_events,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


class _ApprovalRepository:
    def __init__(self, *, work_item=True, decision=True) -> None:
        self._work_item = work_item
        self._decision = decision

    def list_pending_approval_events(self, *, limit: int):
        assert limit == 7
        return [
            {
                "tenant_id": "VO00",
                "approval_work_item_id": "approval-1",
                "outbox_id": "outbox-1",
                "event_payload": {
                    "tenant_id": "VO00",
                    "event_id": "event-1",
                },
            }
        ]

    def get(self, **_kwargs):
        return {"approval_work_item_id": "approval-1"} if self._work_item else None

    def get_decision(self, **_kwargs):
        return {"decision": "APPROVED"} if self._decision else None


def _delivery() -> dict[str, object]:
    return {
        "outbox_id": "outbox-1",
        "work_item": {"approval_work_item_id": "approval-1"},
        "decision": {"decision": "APPROVED"},
        "event": {"tenant_id": "VO00", "event_id": "event-1"},
    }


def _store():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE wc_approval_outbox ("
                "tenant_id TEXT, outbox_id TEXT, event_id TEXT, "
                "approval_work_item_id TEXT, delivery_state TEXT, "
                "updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_approval_outbox VALUES "
                "('VO00', 'outbox-1', 'event-1', 'approval-1', "
                "'PENDING', NULL)"
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyApprovalEventDeliveryStore(factory), engine


def test_pending_projection_requires_complete_lineage() -> None:
    store, _engine = _store()
    store._approvals = _ApprovalRepository()
    assert store.list_pending(limit=7) == [
        {
            "schema_version": "wc_approval_delivery.v1",
            **_delivery(),
        }
    ]

    for missing in ("work_item", "decision"):
        store._approvals = _ApprovalRepository(**{missing: False})
        with pytest.raises(ApprovalEventDeliveryError) as exc:
            store.list_pending(limit=7)
        assert exc.value.retryable is False


def test_delivery_store_marks_once_and_accepts_delivered_replay() -> None:
    store, engine = _store()
    store.mark_delivered(_delivery())
    store.mark_delivered(_delivery())
    with engine.connect() as connection:
        state = connection.execute(
            text("SELECT delivery_state FROM wc_approval_outbox")
        ).scalar_one()
    assert state == "DELIVERED"


def test_delivery_store_fails_closed_for_drift_and_database_failure() -> None:
    store, engine = _store()
    missing = _delivery()
    missing["outbox_id"] = "missing"
    with pytest.raises(ApprovalEventDeliveryError, match="concurrently"):
        store.mark_delivered(missing)

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE wc_approval_outbox"))
    with pytest.raises(ApprovalEventDeliveryError, match="persistence"):
        store.mark_delivered(_delivery())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_url": ""}, "base URL"),
        ({"service_token": ""}, "service token"),
        ({"timeout_seconds": True}, "timeout"),
        ({"timeout_seconds": 0}, "timeout"),
        ({"timeout_seconds": 121}, "timeout"),
    ],
)
def test_http_client_configuration_fails_closed(kwargs, message) -> None:
    values = {
        "base_url": "http://ae.local/",
        "service_token": "signed-token",
        "timeout_seconds": 15,
    }
    values.update(kwargs)
    with pytest.raises(ApprovalEventDeliveryError, match=message) as exc:
        HttpAeApprovalEventClient(**values)
    assert exc.value.retryable is False


def test_http_client_delivers_bound_receipt_and_builds_signed_request() -> None:
    observed = {}

    def opener(request, *, timeout):
        observed["url"] = request.full_url
        observed["authorization"] = request.headers["Authorization"]
        observed["timeout"] = timeout
        return _Response({"event_id": "event-1", "outbox_id": "outbox-1"})

    client = HttpAeApprovalEventClient(
        base_url="http://ae.local/",
        service_token="signed-token",
        timeout_seconds=12.5,
        opener=opener,
    )
    assert client.deliver(_delivery())["event_id"] == "event-1"
    assert observed == {
        "url": "http://ae.local/internal/v1/approval-decision-events",
        "authorization": "Bearer signed-token",
        "timeout": 12.5,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"event_id": "wrong", "outbox_id": "outbox-1"},
        {"event_id": "event-1", "outbox_id": "wrong"},
    ],
)
def test_http_client_rejects_unbound_receipt(payload) -> None:
    client = HttpAeApprovalEventClient(
        base_url="http://ae.local",
        service_token="signed-token",
        opener=lambda *_args, **_kwargs: _Response(payload),
    )
    with pytest.raises(ApprovalEventDeliveryError, match="binding") as exc:
        client.deliver(_delivery())
    assert exc.value.retryable is False


@pytest.mark.parametrize(
    ("status", "body", "retryable", "diagnostic"),
    [
        (
            403,
            {"error_code": "nex.forbidden", "detail": "denied"},
            False,
            "nex.forbidden: denied",
        ),
        (503, b"not-json", True, ""),
        (500, ["not", "an", "object"], True, ""),
    ],
)
def test_http_client_classifies_http_failures(
    status, body, retryable, diagnostic
) -> None:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def opener(*_args, **_kwargs):
        raise HTTPError(
            "http://ae.local",
            status,
            "failure",
            hdrs=None,
            fp=BytesIO(raw),
        )

    client = HttpAeApprovalEventClient(
        base_url="http://ae.local",
        service_token="signed-token",
        opener=opener,
    )
    with pytest.raises(ApprovalEventDeliveryError) as exc:
        client.deliver(_delivery())
    assert exc.value.retryable is retryable
    assert diagnostic in exc.value.detail


@pytest.mark.parametrize(
    "failure",
    [URLError("offline"), TimeoutError(), OSError(), json.JSONDecodeError("x", "x", 0)],
)
def test_http_client_types_transport_and_decode_failures(failure) -> None:
    def opener(*_args, **_kwargs):
        if isinstance(failure, json.JSONDecodeError):
            return _Response(b"not-json")
        raise failure

    client = HttpAeApprovalEventClient(
        base_url="http://ae.local",
        service_token="signed-token",
        opener=opener,
    )
    with pytest.raises(ApprovalEventDeliveryError, match="unavailable") as exc:
        client.deliver(_delivery())
    assert exc.value.retryable is True


def test_delivery_coordinator_preserves_order_and_counts() -> None:
    store = SimpleNamespace(
        list_pending=lambda **_kwargs: [_delivery(), _delivery()],
        delivered=[],
    )
    store.mark_delivered = store.delivered.append
    client = SimpleNamespace(delivered=[])
    client.deliver = client.delivered.append
    result = deliver_pending_approval_events(store=store, client=client, limit=2)
    assert result == {"pending_count": 2, "delivered_count": 2}
    assert client.delivered == store.delivered


@pytest.mark.parametrize(
    "delivery",
    [
        {**_delivery(), "event": "bad"},
        {**_delivery(), "work_item": "bad"},
        {**_delivery(), "outbox_id": ""},
        {
            **_delivery(),
            "event": {"tenant_id": "", "event_id": "event-1"},
        },
    ],
)
def test_delivery_store_rejects_malformed_bindings(delivery) -> None:
    store, _engine = _store()
    with pytest.raises(ApprovalEventDeliveryError) as exc:
        store.mark_delivered(delivery)
    assert exc.value.retryable is False
