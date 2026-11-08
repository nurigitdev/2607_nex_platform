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
    build_common_job,
    build_subject_ref,
    validate_common_job,
)

from nex_wc.handoff_delivery import (
    WC_EVENT_DELIVERY_JOB_TYPE,
    WC_OUTBOX_SUBJECT_TYPE,
)


@dataclass
class WorkResultDeliveryError(Exception):
    error_code: str
    detail: str
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class WorkResultOutboxStore(Protocol):
    def list_pending_result_events(
        self, *, limit: int
    ) -> Sequence[Mapping[str, Any]]: ...

    def mark_result_event_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]: ...

    def load_result_event(
        self, *, outbox_id: str, event_id: str
    ) -> Mapping[str, Any]: ...

    def mark_result_event_delivered(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]: ...


class WorkResultEventClient(Protocol):
    def deliver(self, event: Mapping[str, Any]) -> Mapping[str, Any]: ...


def enqueue_pending_result_events(
    *,
    store: WorkResultOutboxStore,
    queue: JobQueue,
    limit: int = 100,
    clock: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise WorkResultDeliveryError(
            "wc.work_result_bridge_limit_invalid",
            "Bridge limit must be between 1 and 500.",
            False,
        )
    now = _time((clock or (lambda: datetime.now(UTC)))())
    jobs: list[dict[str, Any]] = []
    for outbox in store.list_pending_result_events(limit=limit):
        outbox_id = _required(outbox, "outbox_id")
        event_id = _required(outbox, "event_id")
        event = outbox.get("event_payload")
        if outbox.get("event_type") != "WORK_RESULT_SUBMITTED" or not isinstance(
            event, Mapping
        ):
            raise WorkResultDeliveryError(
                "wc.work_result_outbox_invalid",
                "Pending WorkResult outbox row is invalid.",
                False,
            )
        job = build_common_job(
            job_id=_job_id(event_id),
            job_type=WC_EVENT_DELIVERY_JOB_TYPE,
            trace_id=_required(event, "correlation_id"),
            request_id=event_id,
            subject_ref=build_subject_ref(WC_OUTBOX_SUBJECT_TYPE, outbox_id),
            idempotency_key=event_id,
            created_at=now,
            max_attempts=5,
            retryable=True,
        )
        job["payload"] = {"outbox_id": outbox_id, "event_id": event_id}
        saved = queue.enqueue(validate_common_job(job))
        store.mark_result_event_enqueued(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=str(saved["job_id"]),
            updated_at=now,
        )
        jobs.append(saved)
    return jobs


def run_work_result_delivery_job(
    job: Mapping[str, Any],
    *,
    store: WorkResultOutboxStore,
    client: WorkResultEventClient,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    normalized = validate_common_job(dict(job))
    if normalized["job_type"] != WC_EVENT_DELIVERY_JOB_TYPE:
        raise WorkResultDeliveryError(
            "wc.work_result_job_type_invalid",
            "Worker can run only WC_EVENT_DELIVERY jobs.",
            False,
        )
    payload = normalized.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"outbox_id", "event_id"}:
        raise WorkResultDeliveryError(
            "wc.work_result_job_payload_invalid",
            "Delivery job payload must contain references only.",
            False,
        )
    outbox_id = _required(payload, "outbox_id")
    event_id = _required(payload, "event_id")
    if normalized["subject_ref"] != build_subject_ref(
        WC_OUTBOX_SUBJECT_TYPE, outbox_id
    ):
        raise WorkResultDeliveryError(
            "wc.work_result_job_subject_invalid",
            "Delivery job subject does not match its payload.",
            False,
        )
    if normalized["idempotency_key"] != event_id:
        raise WorkResultDeliveryError(
            "wc.work_result_job_identity_invalid",
            "Delivery job event identity does not match.",
            False,
        )
    row = store.load_result_event(outbox_id=outbox_id, event_id=event_id)
    event = row.get("event_payload")
    if row.get("event_type") != "WORK_RESULT_SUBMITTED" or not isinstance(
        event, Mapping
    ):
        raise WorkResultDeliveryError(
            "wc.work_result_event_invalid",
            "Stored WorkResult event is invalid.",
            False,
        )
    response = client.deliver(event)
    if response.get("event_id") != event_id:
        raise WorkResultDeliveryError(
            "wc.work_result_event_ack_invalid",
            "AE acknowledged a different WorkResult event.",
            False,
        )
    delivered = store.mark_result_event_delivered(
        outbox_id=outbox_id,
        event_id=event_id,
        job_id=str(normalized["job_id"]),
        updated_at=_time((clock or (lambda: datetime.now(UTC)))()),
    )
    return {
        "event_id": event_id,
        "outbox_id": outbox_id,
        "delivery_state": delivered["delivery_state"],
        "inbox_state": response.get("inbox_state"),
        "wait_state": response.get("wait_state"),
        "resume_runtime_job_id": response.get("resume_runtime_job_id"),
    }


class HttpWorkResultEventClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 10.0
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/v1/work-result-events"
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def deliver(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._service_token.strip():
            raise WorkResultDeliveryError(
                "wc.work_result_service_token_missing",
                "AE WorkResult event service token is not configured.",
                False,
            )
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(dict(event), sort_keys=True).encode("utf-8"),
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
            raise WorkResultDeliveryError(
                "wc.work_result_event_http_failed",
                f"AE WorkResult event delivery failed with HTTP {exc.code}.",
                exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkResultDeliveryError(
                "wc.work_result_event_unavailable",
                "AE WorkResult event delivery is unavailable.",
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("event_id") != event.get(
            "event_id"
        ):
            raise WorkResultDeliveryError(
                "wc.work_result_event_response_invalid",
                "AE WorkResult event response is invalid.",
                False,
            )
        return dict(payload)


def _job_id(event_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/jobs/wc/work-result/{event_id}",
        )
    )


def _required(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise WorkResultDeliveryError(
            "wc.work_result_value_invalid",
            f"{field} must be a non-empty string.",
            False,
        )
    return item.strip()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
