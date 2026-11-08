from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    JobQueue,
    ServiceLogEmitter,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    build_common_job,
    build_subject_ref,
    run_worker_once,
    validate_common_job,
)

WC_EVENT_DELIVERY_JOB_TYPE = "WC_EVENT_DELIVERY"
WC_OUTBOX_SUBJECT_TYPE = "WC_OUTBOX"
WC_HANDOFF_WORKER_TYPE = "wc.claim_handoff.delivery.worker"


@dataclass(frozen=True)
class HandoffDeliveryError(Exception):
    error_code: str
    detail: str
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class HandoffOutboxStore(Protocol):
    def list_pending_handoffs(self, *, limit: int) -> Sequence[Mapping[str, Any]]: ...

    def mark_handoff_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]: ...

    def load_handoff_event(
        self, *, outbox_id: str, event_id: str
    ) -> Mapping[str, Any]: ...

    def mark_handoff_delivered(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        updated_at: str,
        agent_execution_id: str | None = None,
    ) -> Mapping[str, Any]: ...


class ClaimHandoffClient(Protocol):
    def deliver(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]: ...


def enqueue_pending_handoffs(
    *,
    store: HandoffOutboxStore,
    queue: JobQueue,
    limit: int = 100,
    clock: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise HandoffDeliveryError(
            "wc.handoff_bridge_limit_invalid", "Bridge limit must be between 1 and 500.", False
        )
    now = _time((clock or (lambda: datetime.now(UTC)))())
    enqueued: list[dict[str, Any]] = []
    for outbox in store.list_pending_handoffs(limit=limit):
        outbox_id = _required(outbox, "outbox_id")
        event_id = _required(outbox, "event_id")
        payload = outbox.get("event_payload")
        if outbox.get("event_type") != "CLAIM_EXECUTION_HANDOFF" or not isinstance(
            payload, Mapping
        ):
            raise HandoffDeliveryError(
                "wc.handoff_outbox_invalid", "Pending handoff outbox row is invalid.", False
            )
        job = build_common_job(
            job_id=_job_id(event_id),
            job_type=WC_EVENT_DELIVERY_JOB_TYPE,
            trace_id=_required(payload, "correlation_id"),
            request_id=event_id,
            subject_ref=build_subject_ref(WC_OUTBOX_SUBJECT_TYPE, outbox_id),
            idempotency_key=event_id,
            created_at=now,
            max_attempts=5,
            retryable=True,
        )
        job["payload"] = {"outbox_id": outbox_id, "event_id": event_id}
        saved = queue.enqueue(validate_common_job(job))
        store.mark_handoff_enqueued(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=str(saved["job_id"]),
            updated_at=now,
        )
        enqueued.append(saved)
    return enqueued


def run_handoff_delivery_job(
    job: Mapping[str, Any],
    *,
    store: HandoffOutboxStore,
    client: ClaimHandoffClient,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    normalized = validate_common_job(dict(job))
    if normalized["job_type"] != WC_EVENT_DELIVERY_JOB_TYPE:
        raise HandoffDeliveryError(
            "wc.handoff_job_type_invalid", "Worker can run only WC_EVENT_DELIVERY jobs.", False
        )
    payload = normalized.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"outbox_id", "event_id"}:
        raise HandoffDeliveryError(
            "wc.handoff_job_payload_invalid", "Delivery job payload must contain references only.", False
        )
    outbox_id = _required(payload, "outbox_id")
    event_id = _required(payload, "event_id")
    if normalized["subject_ref"] != build_subject_ref(WC_OUTBOX_SUBJECT_TYPE, outbox_id):
        raise HandoffDeliveryError(
            "wc.handoff_job_subject_invalid", "Delivery job subject does not match its payload.", False
        )
    if normalized["idempotency_key"] != event_id:
        raise HandoffDeliveryError(
            "wc.handoff_job_identity_invalid", "Delivery job event identity does not match.", False
        )
    event = store.load_handoff_event(outbox_id=outbox_id, event_id=event_id)
    handoff = event.get("event_payload")
    if event.get("event_type") != "CLAIM_EXECUTION_HANDOFF" or not isinstance(
        handoff, Mapping
    ):
        raise HandoffDeliveryError(
            "wc.handoff_event_invalid", "Stored handoff event is invalid.", False
        )
    planning_source = event.get("planning_source")
    if not isinstance(planning_source, Mapping):
        raise HandoffDeliveryError(
            "wc.handoff_planning_source_invalid",
            "Stored handoff planning source is invalid.",
            False,
        )
    observed_at = (clock or (lambda: datetime.now(UTC)))()
    _require_current_claim_authority(event, handoff, observed_at)
    envelope = {
        "event_id": event_id,
        "event_type": "CLAIM_EXECUTION_HANDOFF",
        "requester_ref": _required(event, "requester_ref"),
        "handoff": dict(handoff),
        "planning_source": dict(planning_source),
    }
    response = client.deliver(envelope)
    agent_execution_id = _required(response, "agent_execution_id")
    delivered = store.mark_handoff_delivered(
        outbox_id=outbox_id,
        event_id=event_id,
        job_id=str(normalized["job_id"]),
        updated_at=_time(observed_at),
        agent_execution_id=agent_execution_id,
    )
    return {
        "event_id": event_id,
        "outbox_id": outbox_id,
        "delivery_state": delivered["delivery_state"],
        "agent_execution_id": agent_execution_id,
    }


def run_handoff_delivery_worker_once(
    *,
    queue: JobQueue,
    store: HandoffOutboxStore,
    client: ClaimHandoffClient,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    service_log_emitter: ServiceLogEmitter | None = None,
    worker_id: str = "wc-handoff-delivery-worker-001",
    clock=None,
) -> WorkerJobExecution:
    return run_worker_once(
        config=WorkerRunnerConfig(
            service_id="nex-wc",
            worker_id=worker_id,
            worker_type=WC_HANDOFF_WORKER_TYPE,
            job_type=WC_EVENT_DELIVERY_JOB_TYPE,
        ),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        service_log_emitter=service_log_emitter,
        handler=lambda job: run_handoff_delivery_job(
            job,
            store=store,
            client=client,
            clock=(None if clock is None else lambda: _datetime(clock())),
        ),
        clock=clock,
    )


class HttpClaimHandoffClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 10.0
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/v1/work-handoffs"
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def deliver(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._service_token.strip():
            raise HandoffDeliveryError(
                "wc.handoff_service_token_missing",
                "AE handoff service token is not configured.",
                False,
            )
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(dict(envelope), sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise HandoffDeliveryError(
                "wc.handoff_delivery_http_failed",
                f"AE handoff delivery failed with HTTP {exc.code}.",
                exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise HandoffDeliveryError(
                "wc.handoff_delivery_unavailable", "AE handoff delivery is unavailable."
            ) from exc
        execution = payload.get("execution") if isinstance(payload, dict) else None
        if not isinstance(execution, Mapping) or not execution.get("agent_execution_id"):
            raise HandoffDeliveryError(
                "wc.handoff_delivery_response_invalid",
                "AE handoff admission response is invalid.",
                False,
            )
        return {"agent_execution_id": str(execution["agent_execution_id"])}


def _job_id(event_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://nex-platform.local/jobs/wc/handoff/{event_id}"))


def _required(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise HandoffDeliveryError(
            "wc.handoff_value_invalid", f"{field} must be a non-empty string.", False
        )
    return item.strip()


def _require_current_claim_authority(
    event: Mapping[str, Any],
    handoff: Mapping[str, Any],
    observed_at: datetime,
) -> None:
    claim_ref = _required(handoff, "claim_ref")
    lease_expires_at = event.get("claim_lease_expires_at")
    try:
        lease_expiry = datetime.fromisoformat(
            str(lease_expires_at).replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise HandoffDeliveryError(
            "wc.handoff_claim_authority_invalid",
            "Stored handoff claim authority is invalid.",
            False,
        ) from exc
    if lease_expiry.tzinfo is None:
        raise HandoffDeliveryError(
            "wc.handoff_claim_authority_invalid",
            "Stored handoff claim lease lacks a timezone.",
            False,
        )
    if (
        event.get("delivery_state") not in {"ENQUEUED", "DELIVERED"}
        or event.get("claim_state") != "ACTIVE"
        or event.get("assignment_status") != "ACTIVE"
        or str(event.get("active_claim_id")) != claim_ref
        or event.get("claim_generation") != handoff.get("claim_generation")
    ):
        raise HandoffDeliveryError(
            "wc.handoff_claim_stale",
            "Handoff no longer has current Claim and Assignment authority.",
            False,
        )
    if lease_expiry.astimezone(UTC) <= observed_at.astimezone(UTC):
        raise HandoffDeliveryError(
            "wc.handoff_claim_expired",
            "Handoff Claim lease expired before delivery.",
            False,
        )


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
