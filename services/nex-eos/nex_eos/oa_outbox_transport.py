from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .outbox_publication import (
    EosOutboxEvent,
    EosOutboxPublicationError,
    EosOutboxPublishReceipt,
    EosOutboxTransport,
)
from .project_entitlement_events import PROJECT_ENTITLEMENT_EVENT_TYPE


class RoutingEosOutboxTransport:
    def __init__(
        self,
        *,
        ae_transport: EosOutboxTransport,
        oa_transport: EosOutboxTransport,
    ) -> None:
        self._ae_transport = ae_transport
        self._oa_transport = oa_transport

    def publish(self, event: EosOutboxEvent) -> EosOutboxPublishReceipt:
        if event.event_type == PROJECT_ENTITLEMENT_EVENT_TYPE:
            return self._oa_transport.publish(event)
        return self._ae_transport.publish(event)

    def route_projection(self) -> dict[str, Any]:
        return {
            "schema_version": "eos.outbox_route_projection.v1",
            "routes": {
                PROJECT_ENTITLEMENT_EVENT_TYPE: {
                    "destination_service_id": "nex-oa",
                    "transport_type": self._oa_transport.__class__.__name__,
                },
                "DEFAULT": {
                    "destination_service_id": "nex-ae-api",
                    "transport_type": self._ae_transport.__class__.__name__,
                },
            },
            "content_included": False,
            "secret_included": False,
        }


class HttpOaProjectEntitlementTransport:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise _invalid("OA API base URL is required.", retryable=False)
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid("OA service token is required.", retryable=False)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
        ):
            raise _invalid("OA outbox timeout is invalid.", retryable=False)
        self._url = (
            f"{base_url.rstrip('/')}/internal/v1/auth/project-entitlement-events"
        )
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def publish(self, event: EosOutboxEvent) -> EosOutboxPublishReceipt:
        if not isinstance(event, EosOutboxEvent):
            raise _invalid("EOS outbox event is invalid.", retryable=False)
        if event.event_type != PROJECT_ENTITLEMENT_EVENT_TYPE:
            raise _invalid(
                "OA transport received an unsupported event type.", retryable=False
            )
        body = {
            "event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "business_operation_id": event.business_operation_id,
            "event_type": event.event_type,
            "event_payload": event.event_payload,
            "event_payload_hash": event.event_payload_hash,
        }
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise _invalid(
                f"OA Project entitlement publication failed with HTTP {exc.code}.",
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise _invalid(
                "OA Project entitlement publication is unavailable.", retryable=True
            ) from exc
        return _receipt(payload, event)


def _receipt(value: object, event: EosOutboxEvent) -> EosOutboxPublishReceipt:
    if not isinstance(value, Mapping):
        raise _invalid("OA Project entitlement receipt is invalid.", retryable=False)
    if (
        value.get("event_id") != event.event_id
        or value.get("event_payload_hash") != event.event_payload_hash
        or value.get("inbox_state") != "APPLIED"
    ):
        raise _invalid(
            "OA Project entitlement receipt binding is invalid.", retryable=False
        )
    receipt_ref = value.get("receipt_ref")
    if not isinstance(receipt_ref, str) or not receipt_ref.strip():
        raise _invalid(
            "OA Project entitlement receipt reference is invalid.", retryable=False
        )
    return EosOutboxPublishReceipt(
        event_id=event.event_id,
        event_payload_hash=event.event_payload_hash,
        receipt_ref=receipt_ref,
    )


def _invalid(detail: str, *, retryable: bool) -> EosOutboxPublicationError:
    return EosOutboxPublicationError(
        "EOS_OUTBOX_OA_PUBLICATION_FAILED", detail, retryable=retryable
    )
