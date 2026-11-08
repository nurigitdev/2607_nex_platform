from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nex_runtime import resolve_service_endpoint

from nex_ae_api.service_auth import resolve_ae_outbound_service_token
from nex_ae_api.wa_source_projections import (
    AgentResultWaProjectionSource,
    WaSourceProjectionError,
    build_artifact_wa_projection,
)


@dataclass(frozen=True)
class WaNotificationOutcome:
    status: str
    retryable: bool
    detail: str | None = None


class HttpWaEvidenceIntakeClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def admit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self._service_token.strip():
            raise ValueError("WA evidence intake service token is required")
        request_identity = _notification_identity(payload)
        request = Request(
            f"{self._base_url}/internal/v1/evidence-intake",
            method="POST",
            data=json.dumps(dict(payload), sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-NeX-Request-Id": f"wa-notify-{request_identity}",
                "X-NeX-Trace-Id": f"wa-notify-{request_identity}",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"WA intake failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("WA intake is unavailable") from exc
        if not isinstance(value, Mapping) or value.get("status") != "QUEUED":
            raise RuntimeError("WA intake returned an invalid acknowledgement")
        if any(
            value.get(field) != payload.get(field)
            for field in ("source_type", "source_ref", "source_revision_ref")
        ):
            raise RuntimeError("WA intake acknowledgement changed source identity")
        return dict(value)


class AeWaPostCompletionNotifier:
    """Best-effort notification after AE's authoritative completion commit."""

    def __init__(
        self,
        client: HttpWaEvidenceIntakeClient,
        *,
        agent_results: AgentResultWaProjectionSource,
    ) -> None:
        self._client = client
        self._agent_results = agent_results

    def notify_agent_result(
        self,
        *,
        tenant_id: str,
        result_id: str,
    ) -> WaNotificationOutcome:
        try:
            projection = self._agent_results.get_projection(
                tenant_id=tenant_id,
                result_id=result_id,
            )
            if projection is None:
                return WaNotificationOutcome("NOT_READY", False, "source not found")
            if not _agent_result_complete(projection):
                return WaNotificationOutcome("NOT_READY", False, "completion barrier open")
            return self._admit(_agent_result_payload(projection))
        except WaSourceProjectionError as exc:
            return WaNotificationOutcome("RETRY_PENDING", exc.retryable, exc.error_code)
        except Exception as exc:  # noqa: BLE001 - best-effort boundary
            return WaNotificationOutcome("RETRY_PENDING", True, type(exc).__name__)

    def notify_ready_artifact(
        self,
        record: Mapping[str, Any],
        *,
        artifact_version_id: str,
    ) -> WaNotificationOutcome:
        try:
            projection = build_artifact_wa_projection(
                dict(record),
                artifact_version_id=artifact_version_id,
            )
            if projection is None:
                return WaNotificationOutcome("NOT_READY", False, "version not found")
            return self._admit(_artifact_payload(projection))
        except WaSourceProjectionError as exc:
            return WaNotificationOutcome("RETRY_PENDING", exc.retryable, exc.error_code)
        except Exception as exc:  # noqa: BLE001 - best-effort boundary
            return WaNotificationOutcome("RETRY_PENDING", True, type(exc).__name__)

    def _admit(self, payload: Mapping[str, Any]) -> WaNotificationOutcome:
        acknowledgement = self._client.admit(payload)
        return WaNotificationOutcome(
            "REUSED" if acknowledgement.get("idempotent_reuse") is True else "ACCEPTED",
            False,
        )


def build_ae_wa_post_completion_notifier(
    *,
    agent_results: AgentResultWaProjectionSource,
    environ: Mapping[str, str] | None = None,
) -> AeWaPostCompletionNotifier:
    env = {} if environ is None else environ
    endpoint = resolve_service_endpoint("nex-wa", environ=env)
    token = resolve_ae_outbound_service_token(
        env.get("NEX_AE_TO_WA_SERVICE_TOKEN"),
        audience="nex-wa",
        environ=env,
    )
    return AeWaPostCompletionNotifier(
        HttpWaEvidenceIntakeClient(
            base_url=env.get("NEX_WA_BASE_URL", endpoint.base_url),
            service_token=token,
            timeout_seconds=float(env.get("NEX_AE_TO_WA_TIMEOUT_SECONDS", "15")),
        ),
        agent_results=agent_results,
    )


def _agent_result_complete(value: Mapping[str, Any]) -> bool:
    target = "WORKSPACE_RESULT" if value.get("agent_type") == "IA" else "WC_WORK_RESULT"
    return (
        value.get("status") in {"SUCCEEDED", "PARTIAL"}
        and value.get("agent_execution_state") == "SUCCEEDED"
        and value.get("required_delivery_target_type") == target
        and value.get("required_delivery_state") == "ACKNOWLEDGED"
    )


def _agent_result_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": value["tenant_id"],
        "source_type": "AE_AGENT_RESULT",
        "source_ref": value["agent_execution_id"],
        "source_revision_ref": value["result_id"],
        "source_hash": value["result_hash"],
        "occurred_at": value["created_at"],
        "correlation_id": value["agent_execution_id"],
    }


def _artifact_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": value["tenant_id"],
        "source_type": "AE_ARTIFACT",
        "source_ref": value["artifact_id"],
        "source_revision_ref": value["artifact_version_id"],
        "source_hash": value["artifact_content_hash"],
        "occurred_at": value["created_at"],
        "correlation_id": value["artifact_id"],
    }


def _notification_identity(payload: Mapping[str, Any]) -> str:
    semantic = "|".join(
        str(payload[field])
        for field in ("tenant_id", "source_type", "source_ref", "source_revision_ref")
    )
    return hashlib.sha256(semantic.encode("utf-8")).hexdigest()[:32]
