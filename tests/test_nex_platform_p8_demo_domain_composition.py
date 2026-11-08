from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventError,
    ApprovalDecisionEventRouter,
    HttpEosBusinessApprovalDecisionClient,
    register_approval_decision_event_routes,
)
from nex_eos.approval_decision_api import register_approval_decision_routes
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_wc.approval_event_delivery import (
    ApprovalEventDeliveryError,
    HttpAeApprovalEventClient,
    deliver_pending_approval_events,
)

TENANT = "VO00"
OUTBOX_ID = "6875d742-0858-4f47-a04e-7c58dc7a15f1"
EVENT_ID = "d04a36a1-c0b1-44f4-bd22-530ee47651a5"
WORK_ITEM_ID = "c28b25f0-5484-4b2d-abd9-18afc08090de"
DECISION_ID = "6330c925-9b16-48b7-9a92-f8c6c28c5374"
INSTANCE_ID = "18e822e7-23f6-47fb-9c75-b126cf43c683"


def _delivery(domain: str = "BUSINESS_FORMAL") -> dict[str, object]:
    work_item = {
        "tenant_id": TENANT,
        "approval_work_item_id": WORK_ITEM_ID,
        "approval_domain": domain,
        "resume_target_ref": f"eos.approval-instance:{INSTANCE_ID}:stage:1",
    }
    decision = {
        "tenant_id": TENANT,
        "approval_work_item_id": WORK_ITEM_ID,
        "decision_id": DECISION_ID,
        "decision": "APPROVE",
    }
    event = {
        "tenant_id": TENANT,
        "event_id": EVENT_ID,
        "event_type": f"{domain}_APPROVAL_DECIDED",
        "approval_work_item_id": WORK_ITEM_ID,
        "decision_id": DECISION_ID,
    }
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": OUTBOX_ID,
        "work_item": work_item,
        "decision": decision,
        "event": event,
    }


class _Admission:
    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls = 0

    def ingest(self, delivery):
        self.calls += 1
        return {
            "outbox_id": delivery["outbox_id"],
            "event_id": delivery["event"]["event_id"],
            "approval_domain": self.domain,
        }


def _service_token(service_id: str, audience: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE],
    ).access_token


def test_ae_approval_router_preserves_domain_separation() -> None:
    nsl = _Admission("NSL_WRITE")
    business = _Admission("BUSINESS_FORMAL")
    router = ApprovalDecisionEventRouter(
        nsl_admission=nsl,
        business_admission=business,
    )

    assert router.ingest(_delivery("NSL_WRITE"))["approval_domain"] == "NSL_WRITE"
    assert router.ingest(_delivery())["approval_domain"] == "BUSINESS_FORMAL"
    assert nsl.calls == business.calls == 1

    with pytest.raises(ApprovalDecisionEventError, match="does not consume"):
        router.ingest(_delivery("AGENT_FORMAL"))
    with pytest.raises(ApprovalDecisionEventError, match="lineage"):
        malformed = _delivery()
        malformed["decision"] = {**malformed["decision"], "tenant_id": "OTHER"}
        router.ingest(malformed)


def test_ae_approval_route_accepts_only_wc_and_returns_bound_receipt() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    admission = _Admission("BUSINESS_FORMAL")
    register_approval_decision_event_routes(app, admission=admission)
    client = TestClient(app)

    accepted = client.post(
        "/internal/v1/approval-decision-events",
        json=_delivery(),
        headers={"Authorization": f"Bearer {_service_token('nex-wc', 'nex-ae-api')}"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["outbox_id"] == OUTBOX_ID

    denied = client.post(
        "/internal/v1/approval-decision-events",
        json=_delivery(),
        headers={"Authorization": f"Bearer {_service_token('nex-eos', 'nex-ae-api')}"},
    )
    assert denied.status_code == 403


class _TransitionService:
    def __init__(self) -> None:
        self.kwargs = None

    def advance_from_wc_decision(self, **kwargs):
        self.kwargs = kwargs
        return {"instance": {"state": "APPROVED"}}


def test_eos_approval_route_uses_existing_transition_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-eos"])
    service = _TransitionService()
    app.state.eos_approval_transition_service = service
    register_approval_decision_routes(app)
    client = TestClient(app)

    accepted = client.post(
        "/internal/v1/approval-decision-events",
        json=_delivery(),
        headers={"Authorization": f"Bearer {_service_token('nex-ae-api', 'nex-eos')}"},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {
        "schema_version": "eos_approval_decision_receipt.v1",
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "approval_instance_id": INSTANCE_ID,
        "transition_state": "APPROVED",
    }
    assert service.kwargs["approval_instance_id"] == INSTANCE_ID

    denied = client.post(
        "/internal/v1/approval-decision-events",
        json=_delivery(),
        headers={"Authorization": f"Bearer {_service_token('nex-wc', 'nex-eos')}"},
    )
    assert denied.status_code == 403


class _Response:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


def test_wc_to_ae_and_ae_to_eos_http_adapters_bind_receipts() -> None:
    observed: list[tuple[str, str]] = []

    def ae_opener(request, *, timeout):
        observed.append((request.full_url, request.headers["Authorization"]))
        payload = json.loads(request.data)
        return _Response(
            {
                "outbox_id": payload["outbox_id"],
                "event_id": payload["event"]["event_id"],
            }
        )

    receipt = HttpAeApprovalEventClient(
        base_url="https://ae.example",
        service_token="wc-token",
        opener=ae_opener,
    ).deliver(_delivery())
    assert receipt["event_id"] == EVENT_ID

    eos = HttpEosBusinessApprovalDecisionClient(
        base_url="https://eos.example",
        service_token="ae-token",
        opener=lambda request, **_kwargs: (
            observed.append((request.full_url, request.headers["Authorization"]))
            or _Response(
                {
                    "outbox_id": OUTBOX_ID,
                    "event_id": EVENT_ID,
                    "approval_domain": "BUSINESS_FORMAL",
                }
            )
        ),
    ).ingest(_delivery())
    assert eos["outbox_id"] == OUTBOX_ID
    assert observed == [
        ("https://ae.example/internal/v1/approval-decision-events", "Bearer wc-token"),
        ("https://eos.example/internal/v1/approval-decision-events", "Bearer ae-token"),
    ]

    with pytest.raises(ApprovalEventDeliveryError, match="receipt binding"):
        HttpAeApprovalEventClient(
            base_url="https://ae.example",
            service_token="token",
            opener=lambda *_args, **_kwargs: _Response(
                {"outbox_id": "wrong", "event_id": EVENT_ID}
            ),
        ).deliver(_delivery())


def test_wc_approval_delivery_marks_only_after_ack() -> None:
    class Store:
        def __init__(self):
            self.marked = []

        def list_pending(self, *, limit):
            assert limit == 32
            return [_delivery()]

        def mark_delivered(self, item):
            self.marked.append(item["outbox_id"])

    class Client:
        def deliver(self, item):
            return {"outbox_id": item["outbox_id"], "event_id": EVENT_ID}

    store = Store()
    result = deliver_pending_approval_events(store=store, client=Client())
    assert result == {"pending_count": 1, "delivered_count": 1}
    assert store.marked == [OUTBOX_ID]

    failing_store = Store()

    class FailingClient:
        def deliver(self, _item):
            raise ApprovalEventDeliveryError("unavailable")

    with pytest.raises(ApprovalEventDeliveryError):
        deliver_pending_approval_events(store=failing_store, client=FailingClient())
    assert failing_store.marked == []


def test_ae_to_eos_http_adapter_rejects_unbound_receipt_and_bad_timeout() -> None:
    with pytest.raises(ApprovalDecisionEventError, match="receipt binding"):
        HttpEosBusinessApprovalDecisionClient(
            base_url="https://eos.example",
            service_token="token",
            opener=lambda *_args, **_kwargs: _Response(
                {
                    "outbox_id": OUTBOX_ID,
                    "event_id": EVENT_ID,
                    "approval_domain": "NSL_WRITE",
                }
            ),
        ).ingest(_delivery())

    with pytest.raises(ApprovalDecisionEventError, match="timeout"):
        HttpEosBusinessApprovalDecisionClient(
            base_url="https://eos.example",
            service_token="token",
            timeout_seconds=0,
        )
