from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class WorkResultPublicationError(Exception):
    error_code: str
    detail: str
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class HttpWcWorkResultClient:
    """Thin authenticated boundary used by the S7 ResultDelivery publisher."""

    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def status(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any]:
        if not self._service_token.strip():
            raise WorkResultPublicationError(
                "ae.wc_work_result_service_token_missing",
                "WC WorkResult service token is not configured.",
                False,
            )
        request = Request(
            f"{self._base_url}/api/v1/work-items/{work_item_id}/status",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-NeX-Tenant-Id": tenant_id,
                "Accept": "application/json",
            },
        )
        payload = self._request(request, action="status lookup")
        if (
            payload.get("tenant_id") != tenant_id
            or payload.get("work_item_id") != work_item_id
            or isinstance(payload.get("version"), bool)
            or not isinstance(payload.get("version"), int)
            or payload["version"] < 1
        ):
            raise _invalid_response()
        return dict(payload)

    def submit(
        self, *, expected_version: int, work_result: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not self._service_token.strip():
            raise WorkResultPublicationError(
                "ae.wc_work_result_service_token_missing",
                "WC WorkResult service token is not configured.",
                False,
            )
        work_item_id = _required(work_result, "work_item_id")
        result_id = _required(work_result, "result_id")
        expected_hash = semantic_sha256_hash_ref(work_result)
        request = Request(
            f"{self._base_url}/api/v1/work-items/{work_item_id}/results",
            method="POST",
            data=json.dumps(
                {
                    "expected_version": expected_version,
                    "work_result": dict(work_result),
                },
                sort_keys=True,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-NeX-Tenant-Id": str(work_result.get("tenant_id") or ""),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        payload = self._request(request, action="submission")
        if (
            payload.get("work_item_id") != work_item_id
            or payload.get("result_id") != result_id
            or payload.get("result_hash") != expected_hash
        ):
            raise _invalid_response()
        return dict(payload)

    def _request(self, request: Request, *, action: str) -> Mapping[str, Any]:
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise WorkResultPublicationError(
                "ae.wc_work_result_http_failed",
                f"WC WorkResult {action} failed with HTTP {exc.code}.",
                exc.code >= 500 or exc.code in {408, 429},
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkResultPublicationError(
                "ae.wc_work_result_unavailable",
                f"WC WorkResult {action} is unavailable.",
            ) from exc
        if not isinstance(payload, Mapping):
            raise _invalid_response()
        return payload


class SqlAlchemyWcWorkResultPublisher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: HttpWcWorkResultClient,
    ) -> None:
        self._session_factory = session_factory
        self._client = client

    def publish(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            with self._session_factory() as session:
                record = _load_publication(session, tenant_id, delivery_id)
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc
        if record is None:
            raise WorkResultPublicationError(
                "ae.wc_work_result_delivery_not_found",
                "WC WorkResult delivery was not found.",
                False,
            )
        if record["state"] == "ACKNOWLEDGED":
            return _publication_result(record, acknowledged=True)
        if record["state"] not in {"PENDING", "RETRY_PENDING"}:
            raise WorkResultPublicationError(
                "ae.wc_work_result_delivery_state_invalid",
                "WC WorkResult delivery is not publishable.",
                False,
            )
        work_result = build_wc_work_result(
            agent_result=record["agent_result"],
            execution=record,
            planning_source=record["planning_source"],
            submitted_at=record["created_at"],
        )
        status = self._client.status(
            tenant_id=tenant_id, work_item_id=record["work_item_ref"]
        )
        accepted = self._client.submit(
            expected_version=int(status["version"]), work_result=work_result
        )
        preflight_ref = (
            f"WC:WORK_ITEM_STATUS:{record['work_item_ref']}:v{status['version']}"
        )
        external_ref = (
            f"WC:WORK_RESULT:{accepted['result_id']}:{accepted['result_hash']}"
        )
        try:
            with self._session_factory() as session:
                updated = session.execute(
                    text(
                        "UPDATE ae_result_delivery SET state = 'ACKNOWLEDGED', "
                        "attempt_no = attempt_no + 1, external_delivery_ref = :external_ref, "
                        "latest_preflight_ref = :preflight_ref, updated_at = :now, "
                        "acknowledged_at = :now WHERE tenant_id = :tenant_id "
                        "AND delivery_id = :delivery_id "
                        "AND state IN ('PENDING', 'RETRY_PENDING')"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "delivery_id": delivery_id,
                        "external_ref": external_ref,
                        "preflight_ref": preflight_ref,
                        "now": timestamp,
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise WorkResultPublicationError(
                        "ae.wc_work_result_delivery_conflict",
                        "WC WorkResult delivery changed before ACK persistence.",
                    )
                successful = record["agent_result"].get("status") in {
                    "SUCCEEDED",
                    "PARTIAL",
                }
                if successful:
                    execution_updated = session.execute(
                        text(
                            "UPDATE ae_agent_execution SET state = 'SUCCEEDED', "
                            "phase = 'FINALIZE', completed_at = :now, "
                            "updated_at = :now, version = version + 1 "
                            "WHERE tenant_id = :tenant_id "
                            "AND agent_execution_id = :execution_id "
                            "AND result_id = :result_id AND state = 'RUNNING' "
                            "AND phase = 'RESULT_PUBLISH'"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "execution_id": record["agent_execution_id"],
                            "result_id": record["result_id"],
                            "now": timestamp,
                        },
                    )
                    if int(execution_updated.rowcount or 0) != 1:
                        raise WorkResultPublicationError(
                            "ae.wc_work_result_execution_conflict",
                            "Child execution cannot succeed without exact delivery authority.",
                        )
                session.commit()
        except WorkResultPublicationError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc
        return {
            "schema_version": "ae_wc_work_result_publication.v1",
            "tenant_id": tenant_id,
            "delivery_id": delivery_id,
            "result_id": record["result_id"],
            "result_hash": accepted["result_hash"],
            "work_item_id": record["work_item_ref"],
            "work_item_version": accepted["work_item_version"],
            "delivery_state": "ACKNOWLEDGED",
            "execution_state": (
                "SUCCEEDED"
                if record["agent_result"].get("status") in {"SUCCEEDED", "PARTIAL"}
                else record["agent_result"].get("status")
            ),
            "created": bool(accepted["created"]),
        }


def build_wc_work_result(
    *,
    agent_result: Mapping[str, Any],
    execution: Mapping[str, Any],
    planning_source: Mapping[str, Any],
    submitted_at: str,
) -> dict[str, Any]:
    status = str(agent_result.get("status"))
    technical_outcome = (
        status if status in {"SUCCEEDED", "PARTIAL", "FAILED"} else "FAILED"
    )
    provenance = agent_result.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    return {
        "schema_version": "2.1",
        "tenant_id": str(agent_result["tenant_id"]),
        "result_id": str(agent_result["result_id"]),
        "work_item_id": str(execution["work_item_ref"]),
        "revision_no": 1,
        "result_type": "AGENT_RESULT",
        "summary": None,
        "payload": {
            "agent_result_ref": f"AE:AGENT_RESULT:{agent_result['result_id']}",
            "agent_result_hash": agent_result["result_hash"],
            "structured_result": agent_result["structured_result"],
        },
        "schema_ref": planning_source["result_contract_ref"],
        "technical_outcome": technical_outcome,
        "business_outcome": "PENDING_VERIFICATION",
        "artifact_refs": _entity_refs(agent_result.get("artifact_refs"), "ARTIFACT"),
        "evidence_refs": _entity_refs(agent_result.get("evidence_refs"), "EVIDENCE"),
        "business_object_refs": _entity_refs(
            agent_result.get("business_refs"), "BUSINESS_OBJECT"
        ),
        "source_execution_ref": str(agent_result["agent_execution_id"]),
        "source_plan_ref": provenance.get("executable_plan_id"),
        "claim_ref": str(execution["claim_ref"]),
        "claim_generation": int(execution["claim_generation"]),
        "assignment_ref": str(execution["assignment_ref"]),
        "submitted_by": {
            "entity_type": "AGENT",
            "entity_id": str(agent_result["agent_id"]),
        },
        "trace": {
            "correlation_id": str(execution["correlation_id"]),
            "causation_id": execution.get("causation_id"),
            "request_id": str(execution["agent_execution_id"]),
        },
        "submitted_at": submitted_at,
    }


def _required(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise WorkResultPublicationError(
            "ae.wc_work_result_invalid",
            f"{field} must be a non-empty string.",
            False,
        )
    return item.strip()


def _load_publication(
    session: Session, tenant_id: str, delivery_id: str
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF delivery" if session.get_bind().dialect.name == "postgresql" else ""
    row = session.execute(
        text(
            "SELECT delivery.tenant_id, delivery.delivery_id, delivery.result_id, "
            "delivery.agent_execution_id, delivery.target_type, "
            "delivery.target_ref, delivery.state, delivery.attempt_no, "
            "result.result_envelope_json, execution.agent_id, "
            "execution.agent_type, execution.project_id, "
            "execution.work_item_ref, execution.claim_ref, "
            "execution.claim_generation, execution.assignment_ref, "
            "execution.correlation_id, execution.causation_id, "
            "inbox.planning_source_json, delivery.created_at "
            "FROM ae_result_delivery AS delivery "
            "JOIN ae_agent_result AS result ON result.tenant_id = delivery.tenant_id "
            "AND result.result_id = delivery.result_id "
            "JOIN ae_agent_execution AS execution "
            "ON execution.tenant_id = delivery.tenant_id "
            "AND execution.agent_execution_id = delivery.agent_execution_id "
            "JOIN ae_claim_handoff_inbox AS inbox "
            "ON inbox.tenant_id = delivery.tenant_id "
            "AND inbox.agent_execution_id = delivery.agent_execution_id "
            "WHERE delivery.tenant_id = :tenant_id "
            "AND delivery.delivery_id = :delivery_id" + suffix
        ),
        {"tenant_id": tenant_id, "delivery_id": delivery_id},
    ).mappings().first()
    if row is None:
        return None
    record = dict(row)
    for key in ("delivery_id", "result_id", "agent_execution_id", "agent_id"):
        record[key] = str(record[key])
    record["created_at"] = _datetime_value(record["created_at"])
    result_value = record.pop("result_envelope_json")
    source_value = record.pop("planning_source_json")
    record["agent_result"] = (
        json.loads(result_value) if isinstance(result_value, str) else dict(result_value)
    )
    record["planning_source"] = (
        json.loads(source_value) if isinstance(source_value, str) else dict(source_value)
    )
    if (
        record["target_type"] != "WC_WORK_RESULT"
        or record["target_ref"] != str(record["work_item_ref"])
    ):
        raise WorkResultPublicationError(
            "ae.wc_work_result_delivery_lineage_invalid",
            "ResultDelivery is outside its claimed WorkItem lineage.",
            False,
        )
    return record


def _entity_refs(value: object, entity_type: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkResultPublicationError(
            "ae.wc_work_result_invalid",
            "AgentResult references must be arrays.",
            False,
        )
    refs: list[dict[str, str]] = []
    for item in value:
        ref = str(item)
        if not ref or len(ref) > 160:
            raise WorkResultPublicationError(
                "ae.wc_work_result_invalid",
                "AgentResult reference exceeds the WC WorkResult bound.",
                False,
            )
        refs.append({"entity_type": entity_type, "entity_id": ref})
    return refs


def _publication_result(
    record: Mapping[str, Any], *, acknowledged: bool
) -> dict[str, Any]:
    return {
        "schema_version": "ae_wc_work_result_publication.v1",
        "tenant_id": record.get("tenant_id"),
        "delivery_id": record["delivery_id"],
        "result_id": record["result_id"],
        "work_item_id": str(record["work_item_ref"]),
        "delivery_state": "ACKNOWLEDGED" if acknowledged else record["state"],
        "execution_state": "SUCCEEDED" if acknowledged else None,
        "created": False,
    }


def _store_unavailable() -> WorkResultPublicationError:
    return WorkResultPublicationError(
        "ae.wc_work_result_store_unavailable",
        "AE WC WorkResult publication store is unavailable.",
    )


def _invalid_response() -> WorkResultPublicationError:
    return WorkResultPublicationError(
        "ae.wc_work_result_ack_invalid",
        "WC did not acknowledge the exact WorkResult identity and hash.",
        False,
    )


def _datetime_value(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo is not None else value
        return normalized.isoformat().replace("+00:00", "Z")
    return str(value)
