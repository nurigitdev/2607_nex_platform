from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.plan_finalization import (
    P5PlanFinalizationError,
    SqlAlchemyP5PlanFinalizationService,
)


@dataclass(frozen=True)
class WorkspaceResultPublicationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class AgentResultCompletionNotifier(Protocol):
    def notify_agent_result(self, *, tenant_id: str, result_id: str) -> object: ...


class SqlAlchemyWorkspaceResultPublisher:
    """Publishes an IA AgentResult into its owner-private workspace atomically."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        completion_notifier: AgentResultCompletionNotifier | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._completion_notifier = completion_notifier

    def publish(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        delivery_ref = _required_uuid("delivery_id", delivery_id)
        timestamp = _timestamp(now)
        try:
            with self._session_factory() as session:
                record = _load_publication(session, tenant, delivery_ref)
                if record is None:
                    raise WorkspaceResultPublicationError(
                        "ae.workspace_result_delivery_not_found",
                        "Workspace result delivery was not found.",
                    )
                _require_workspace_result_lineage(record)
                activity = _workspace_activity(record)
                existing_activity = _load_activity(session, activity["activity_id"])

                if record["delivery_state"] == "ACKNOWLEDGED":
                    _require_replay_state(record, existing_activity, activity)
                    session.commit()
                    projection = _publication_projection(
                        record,
                        activity_id=activity["activity_id"],
                        created=False,
                        replayed=True,
                    )
                    self._notify(record)
                    return projection
                if record["delivery_state"] not in {"PENDING", "RETRY_PENDING"}:
                    raise WorkspaceResultPublicationError(
                        "ae.workspace_result_delivery_state_invalid",
                        "Workspace result delivery is not publishable.",
                    )
                if (
                    record["execution_state"] != "RUNNING"
                    or record["execution_phase"] != "RESULT_PUBLISH"
                ):
                    raise WorkspaceResultPublicationError(
                        "ae.workspace_result_execution_state_invalid",
                        "Workspace publication requires RUNNING / RESULT_PUBLISH authority.",
                    )

                created = existing_activity is None
                if created:
                    inserted = session.execute(
                        text(_activity_insert_sql(_dialect_name(session))),
                        _activity_params(activity),
                    )
                    created = int(inserted.rowcount or 0) == 1
                    if created:
                        session.execute(
                            text(
                                "UPDATE ae_workspaces SET activity_count = activity_count + 1, "
                                "last_activity_type = :activity_type, updated_at = :created_at "
                                "WHERE workspace_id = :workspace_id AND tenant_id = :tenant_id "
                                "AND owner_user_id = :owner_user_id"
                            ),
                            {
                                **activity,
                                "tenant_id": record["tenant_id"],
                                "owner_user_id": record["principal_id"],
                            },
                        )
                persisted_activity = _load_activity(session, activity["activity_id"])
                _require_activity_semantics(persisted_activity, activity)

                acknowledged = session.execute(
                    text(
                        "UPDATE ae_result_delivery SET state = 'ACKNOWLEDGED', "
                        "attempt_no = attempt_no + 1, "
                        "external_delivery_ref = :external_ref, "
                        "latest_preflight_ref = :preflight_ref, updated_at = :now, "
                        "acknowledged_at = :now WHERE tenant_id = :tenant_id "
                        "AND delivery_id = :delivery_id "
                        "AND state IN ('PENDING', 'RETRY_PENDING')"
                    ),
                    {
                        "tenant_id": tenant,
                        "delivery_id": delivery_ref,
                        "external_ref": (
                            f"AE:WORKSPACE_ACTIVITY:{activity['activity_id']}"
                        ),
                        "preflight_ref": f"AE:WORKSPACE:{record['workspace_id']}",
                        "now": timestamp,
                    },
                )
                if int(acknowledged.rowcount or 0) != 1:
                    raise WorkspaceResultPublicationError(
                        "ae.workspace_result_delivery_conflict",
                        "Workspace result delivery changed before ACK persistence.",
                        True,
                    )
                completed = session.execute(
                    text(
                        "UPDATE ae_agent_execution SET state = 'SUCCEEDED', "
                        "phase = 'FINALIZE', completed_at = :now, updated_at = :now, "
                        "version = version + 1 WHERE tenant_id = :tenant_id "
                        "AND agent_execution_id = :execution_id "
                        "AND result_id = :result_id AND state = 'RUNNING' "
                        "AND phase = 'RESULT_PUBLISH'"
                    ),
                    {
                        "tenant_id": tenant,
                        "execution_id": record["agent_execution_id"],
                        "result_id": record["result_id"],
                        "now": timestamp,
                    },
                )
                if int(completed.rowcount or 0) != 1:
                    raise WorkspaceResultPublicationError(
                        "ae.workspace_result_execution_conflict",
                        "IA execution cannot succeed without exact workspace delivery authority.",
                        True,
                    )
                session.commit()
                projection = _publication_projection(
                    record,
                    activity_id=activity["activity_id"],
                    created=created,
                    replayed=False,
                )
                self._notify(record)
                return projection
        except WorkspaceResultPublicationError:
            raise
        except SQLAlchemyError as exc:
            raise WorkspaceResultPublicationError(
                "ae.workspace_result_store_unavailable",
                "AE workspace result store is unavailable.",
                True,
            ) from exc

    def _notify(self, record: Mapping[str, Any]) -> None:
        if self._completion_notifier is not None:
            try:
                self._completion_notifier.notify_agent_result(
                    tenant_id=str(record["tenant_id"]),
                    result_id=str(record["result_id"]),
                )
            except Exception:  # noqa: BLE001,S110 - post-commit best effort
                # Source completion is authoritative; WA is reconciled separately.
                pass


class SqlAlchemyInstalledIaResultCloser:
    """Closes ready IA executions and resumes publication after a restart."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        finalizer: SqlAlchemyP5PlanFinalizationService | None = None,
        publisher: SqlAlchemyWorkspaceResultPublisher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._finalizer = finalizer or SqlAlchemyP5PlanFinalizationService(
            session_factory
        )
        self._publisher = publisher or SqlAlchemyWorkspaceResultPublisher(
            session_factory
        )

    def close_ready(self, *, limit: int = 10, now: str | None = None) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            "SELECT tenant_id, agent_execution_id, phase FROM ae_agent_execution "
                            "WHERE agent_type = 'IA' AND source_type = 'PROMPT' "
                            "AND state = 'RUNNING' "
                            "AND phase IN ('RESULT_VERIFY', 'RESULT_PUBLISH') "
                            "ORDER BY updated_at ASC, agent_execution_id ASC "
                            "LIMIT :limit"
                        ),
                        {"limit": bounded_limit},
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise WorkspaceResultPublicationError(
                "ae.workspace_result_candidate_query_unavailable",
                "AE result finalization candidates are unavailable.",
                True,
            ) from exc

        finalized_count = 0
        published_count = 0
        replayed_count = 0
        failures: list[dict[str, Any]] = []
        for row in rows:
            tenant_id = str(row["tenant_id"])
            execution_id = str(row["agent_execution_id"])
            try:
                if row["phase"] == "RESULT_VERIFY":
                    aggregate = self._finalizer.finalize(
                        tenant_id=tenant_id,
                        execution_id=execution_id,
                        created_at=now,
                    )
                    finalized_count += 1
                    delivery_id = str(aggregate.delivery["delivery_id"])
                else:
                    delivery_id = _delivery_id_for_execution(
                        self._session_factory,
                        tenant_id=tenant_id,
                        execution_id=execution_id,
                    )
                publication = self._publisher.publish(
                    tenant_id=tenant_id,
                    delivery_id=delivery_id,
                    now=now,
                )
                published_count += int(not publication["replayed"])
                replayed_count += int(publication["replayed"])
            except (P5PlanFinalizationError, WorkspaceResultPublicationError) as exc:
                failures.append(
                    {
                        "tenant_id": tenant_id,
                        "agent_execution_id": execution_id,
                        "error_code": exc.error_code,
                        "retryable": bool(exc.retryable),
                    }
                )
        return {
            "candidate_count": len(rows),
            "finalized_count": finalized_count,
            "published_count": published_count,
            "replayed_count": replayed_count,
            "failed_count": len(failures),
            "failures": failures,
        }


class SqlAlchemyInteractionAgentResultSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_owner_result(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        interaction_id: str,
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _required_text("tenant_id", tenant_id, 128),
            "owner_user_id": _required_text("owner_user_id", owner_user_id, 160),
            "interaction_id": _required_uuid("interaction_id", interaction_id),
        }
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            "SELECT execution.agent_execution_id, execution.workspace_id, "
                            "execution.legacy_interaction_id, execution.state AS execution_state, "
                            "execution.phase AS execution_phase, execution.result_id, "
                            "execution.updated_at, execution.completed_at, "
                            "result.status AS result_status, result.result_hash, "
                            "result.result_envelope_json, delivery.delivery_id, "
                            "delivery.state AS delivery_state, delivery.external_delivery_ref "
                            "FROM ae_agent_execution AS execution "
                            "JOIN ae_workspaces AS workspace "
                            "ON workspace.workspace_id = execution.workspace_id "
                            "AND workspace.tenant_id = execution.tenant_id "
                            "LEFT JOIN ae_agent_result AS result "
                            "ON result.tenant_id = execution.tenant_id "
                            "AND result.agent_execution_id = execution.agent_execution_id "
                            "LEFT JOIN ae_result_delivery AS delivery "
                            "ON delivery.tenant_id = result.tenant_id "
                            "AND delivery.result_id = result.result_id "
                            "AND delivery.target_type = 'WORKSPACE_RESULT' "
                            "WHERE execution.tenant_id = :tenant_id "
                            "AND execution.legacy_interaction_id = :interaction_id "
                            "AND execution.principal_id = :owner_user_id "
                            "AND workspace.owner_user_id = :owner_user_id"
                        ),
                        params,
                    )
                    .mappings()
                    .first()
                )
        except SQLAlchemyError as exc:
            raise WorkspaceResultPublicationError(
                "ae.interaction_agent_result_store_unavailable",
                "AE interaction result store is unavailable.",
                True,
            ) from exc
        if row is None:
            return None
        return _interaction_result_projection(row)


def _load_publication(
    session: Session, tenant_id: str, delivery_id: str
) -> dict[str, Any] | None:
    suffix = (
        " FOR UPDATE OF delivery"
        if _dialect_name(session) == "postgresql"
        else ""
    )
    row = (
        session.execute(
            text(
                "SELECT delivery.tenant_id, delivery.delivery_id, "
                "delivery.result_id, delivery.agent_execution_id, "
                "delivery.target_type, delivery.target_ref, "
                "delivery.state AS delivery_state, delivery.attempt_no, "
                "delivery.publication_operation_id, delivery.external_delivery_ref, "
                "result.status AS result_status, result.result_hash, "
                "result.result_envelope_json, execution.agent_type, "
                "execution.principal_id, execution.source_type, "
                "execution.workspace_id, execution.legacy_interaction_id, "
                "execution.state AS execution_state, "
                "execution.phase AS execution_phase, execution.correlation_id, "
                "workspace.owner_user_id FROM ae_result_delivery AS delivery "
                "JOIN ae_agent_result AS result "
                "ON result.tenant_id = delivery.tenant_id "
                "AND result.result_id = delivery.result_id "
                "JOIN ae_agent_execution AS execution "
                "ON execution.tenant_id = delivery.tenant_id "
                "AND execution.agent_execution_id = delivery.agent_execution_id "
                "JOIN ae_workspaces AS workspace "
                "ON workspace.workspace_id = execution.workspace_id "
                "AND workspace.tenant_id = execution.tenant_id "
                "WHERE delivery.tenant_id = :tenant_id "
                "AND delivery.delivery_id = :delivery_id" + suffix
            ),
            {"tenant_id": tenant_id, "delivery_id": delivery_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    record = dict(row)
    for field in (
        "delivery_id",
        "result_id",
        "agent_execution_id",
        "workspace_id",
        "legacy_interaction_id",
    ):
        if record.get(field) is not None:
            record[field] = str(record[field])
    record["agent_result"] = _json_object(record.pop("result_envelope_json"))
    return record


def _require_workspace_result_lineage(record: Mapping[str, Any]) -> None:
    if (
        record.get("agent_type") != "IA"
        or record.get("source_type") != "PROMPT"
        or record.get("target_type") != "WORKSPACE_RESULT"
        or str(record.get("target_ref")) != str(record.get("workspace_id"))
        or str(record.get("principal_id")) != str(record.get("owner_user_id"))
        or record.get("result_status") not in {"SUCCEEDED", "PARTIAL"}
    ):
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_lineage_invalid",
            "Workspace result delivery is outside its owner-private IA lineage.",
        )


def _workspace_activity(record: Mapping[str, Any]) -> dict[str, Any]:
    activity_id = str(
        uuid5(
            NAMESPACE_URL,
            "nex:workspace-result:"
            f"{record['tenant_id']}:{record['publication_operation_id']}",
        )
    )
    result = record["agent_result"]
    structured = result.get("structured_result")
    structured = structured if isinstance(structured, Mapping) else {}
    return {
        "activity_schema_version": "ae_workspace_activity.v1",
        "activity_id": activity_id,
        "workspace_id": str(record["workspace_id"]),
        "activity_type": "agent.result.published",
        "trace_id": hashlib.sha256(
            str(record["correlation_id"]).encode("utf-8")
        ).hexdigest()[:32],
        "request_id": str(record["publication_operation_id"]),
        "summary": "Agent result is available.",
        "metadata": {
            "interaction_ref": f"AE:CHAT_INTERACTION:{record['legacy_interaction_id']}",
            "agent_execution_ref": (
                f"AE:AGENT_EXECUTION:{record['agent_execution_id']}"
            ),
            "agent_result_ref": f"AE:AGENT_RESULT:{record['result_id']}",
            "agent_result_hash": record["result_hash"],
            "result_delivery_ref": f"AE:RESULT_DELIVERY:{record['delivery_id']}",
            "result_status": record["result_status"],
            "structured_result_contract_ref": result.get(
                "structured_result_contract_ref"
            ),
            "business_refs": list(result.get("business_refs") or ()),
            "external_refs": list(structured.get("external_refs") or ()),
        },
        "created_at": str(result["created_at"]),
    }


def _activity_insert_sql(dialect_name: str) -> str:
    metadata = "CAST(:metadata AS JSONB)" if dialect_name == "postgresql" else ":metadata"
    return f"""
        INSERT INTO ae_workspace_activities (
            activity_schema_version, activity_id, workspace_id, activity_type,
            trace_id, request_id, summary, metadata, created_at
        ) VALUES (
            :activity_schema_version, :activity_id, :workspace_id, :activity_type,
            :trace_id, :request_id, :summary, {metadata}, :created_at
        ) ON CONFLICT (activity_id) DO NOTHING
    """


def _activity_params(activity: Mapping[str, Any]) -> dict[str, Any]:
    return {**activity, "metadata": _canonical_json(activity["metadata"])}


def _load_activity(session: Session, activity_id: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT activity_schema_version, activity_id, workspace_id, "
                "activity_type, trace_id, request_id, summary, metadata, created_at "
                "FROM ae_workspace_activities WHERE activity_id = :activity_id"
            ),
            {"activity_id": activity_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    activity = dict(row)
    activity["activity_id"] = str(activity["activity_id"])
    activity["workspace_id"] = str(activity["workspace_id"])
    activity["metadata"] = _json_object(activity["metadata"])
    activity["created_at"] = _datetime_text(activity["created_at"])
    return activity


def _require_activity_semantics(
    existing: Mapping[str, Any] | None, expected: Mapping[str, Any]
) -> None:
    if existing is None:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_activity_missing",
            "Workspace activity was not persisted.",
            True,
        )
    fields = (
        "activity_schema_version",
        "activity_id",
        "workspace_id",
        "activity_type",
        "trace_id",
        "request_id",
        "summary",
        "metadata",
        "created_at",
    )
    if any(existing.get(field) != expected.get(field) for field in fields):
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_activity_conflict",
            "Workspace result activity already exists with different semantics.",
        )


def _require_replay_state(
    record: Mapping[str, Any],
    existing_activity: Mapping[str, Any] | None,
    expected_activity: Mapping[str, Any],
) -> None:
    _require_activity_semantics(existing_activity, expected_activity)
    expected_ref = f"AE:WORKSPACE_ACTIVITY:{expected_activity['activity_id']}"
    if (
        record.get("external_delivery_ref") != expected_ref
        or record.get("execution_state") != "SUCCEEDED"
        or record.get("execution_phase") != "FINALIZE"
    ):
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_replay_conflict",
            "Acknowledged workspace publication has inconsistent terminal state.",
        )


def _publication_projection(
    record: Mapping[str, Any],
    *,
    activity_id: str,
    created: bool,
    replayed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "ae_workspace_result_publication.v1",
        "tenant_id": record["tenant_id"],
        "interaction_id": record["legacy_interaction_id"],
        "agent_execution_id": record["agent_execution_id"],
        "result_id": record["result_id"],
        "result_hash": record["result_hash"],
        "delivery_id": record["delivery_id"],
        "delivery_state": "ACKNOWLEDGED",
        "workspace_id": record["workspace_id"],
        "workspace_activity_id": activity_id,
        "execution_state": "SUCCEEDED",
        "created": created,
        "replayed": replayed,
    }


def _delivery_id_for_execution(
    factory: sessionmaker[Session], *, tenant_id: str, execution_id: str
) -> str:
    try:
        with factory() as session:
            row = session.execute(
                text(
                    "SELECT delivery_id FROM ae_result_delivery "
                    "WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id "
                    "AND target_type = 'WORKSPACE_RESULT'"
                ),
                {"tenant_id": tenant_id, "execution_id": execution_id},
            ).first()
    except SQLAlchemyError as exc:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_store_unavailable",
            "AE workspace result store is unavailable.",
            True,
        ) from exc
    if row is None:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_delivery_not_found",
            "RESULT_PUBLISH execution is missing its workspace delivery.",
        )
    return str(row[0])


def _interaction_result_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    result_id = row.get("result_id")
    envelope = (
        _json_object(row["result_envelope_json"])
        if row.get("result_envelope_json") is not None
        else None
    )
    result = None
    if envelope is not None:
        structured = envelope.get("structured_result")
        structured = structured if isinstance(structured, Mapping) else {}
        result = {
            "result_ref": f"AE:AGENT_RESULT:{result_id}",
            "result_hash": row["result_hash"],
            "status": row["result_status"],
            "structured_result_contract_ref": envelope.get(
                "structured_result_contract_ref"
            ),
            "business_refs": list(envelope.get("business_refs") or ()),
            "external_refs": list(structured.get("external_refs") or ()),
            "artifact_refs": list(envelope.get("artifact_refs") or ()),
            "warnings": list(envelope.get("warnings") or ()),
            "delivery": {
                "delivery_ref": f"AE:RESULT_DELIVERY:{row['delivery_id']}",
                "state": row["delivery_state"],
                "workspace_activity_ref": row["external_delivery_ref"],
            },
        }
    return {
        "schema_version": "ae_interaction_agent_result.v1",
        "interaction_id": str(row["legacy_interaction_id"]),
        "workspace_id": str(row["workspace_id"]),
        "agent_execution_id": str(row["agent_execution_id"]),
        "execution_state": row["execution_state"],
        "execution_phase": row["execution_phase"],
        "terminal": row["execution_state"] in {
            "SUCCEEDED",
            "FAILED",
            "BLOCKED",
            "CANCELLED",
        },
        "result": result,
        "updated_at": _datetime_text(row["updated_at"]),
        "completed_at": (
            _datetime_text(row["completed_at"])
            if row.get("completed_at") is not None
            else None
        ),
        "metadata": {
            "owner_scope_authority": "claim",
            "raw_result_included": False,
            "prompt_included": False,
        },
    }


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _required_text(name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_identity_invalid",
            f"{name} must be a bounded non-empty string.",
        )
    return value.strip()


def _required_uuid(name: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_identity_invalid",
            f"{name} must be a UUID.",
        ) from exc


def _timestamp(value: str | None) -> str:
    candidate = value or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_timestamp_invalid",
            "Workspace publication timestamp must be ISO-8601.",
        ) from exc
    if parsed.tzinfo is None:
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_timestamp_invalid",
            "Workspace publication timestamp must include a timezone.",
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _json_object(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise WorkspaceResultPublicationError(
            "ae.workspace_result_record_invalid",
            "Persisted AgentResult JSON must be an object.",
        )
    return dict(decoded)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
