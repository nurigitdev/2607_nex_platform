from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .operator_reviews import (
    _datetime_value,
    _dialect_name,
    _json_param_expr,
    _json_value,
    _utc_now,
    operator_note_preview,
    sha256_text,
)


LIVENESS_ACK_STATE_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state.v1"
)
LIVENESS_ACK_STATE_LIST_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_list.v1"
)
AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE = "ag_op_review_ack_state"
MAX_ACK_COMMENT_PREVIEW_LENGTH = 240
MAX_ACK_STATE_LIMIT = 200
DEFAULT_ACK_STATE_LIMIT = 50
DEFAULT_SUPPRESSION_TTL_SECONDS = 1800
MAX_SUPPRESSION_TTL_SECONDS = 86400

ACK_LIVENESS_STATUSES = (
    "MISSING",
    "STALE",
    "SOURCE_NOT_CONFIGURED",
    "SOURCE_UNAVAILABLE",
)
ACK_ACTIONS = (
    "acknowledge_once",
    "suppress_for_ttl",
    "acknowledge_source_attention",
    "suppress_source_attention_for_ttl",
    "clear",
)
ACK_STATE_STATUSES = ("ACKNOWLEDGED", "SUPPRESSED", "EXPIRED", "CLEARED")
ACK_TTL_ACTIONS = ("suppress_for_ttl", "suppress_source_attention_for_ttl")
ACK_SOURCE_ATTENTION_ACTIONS = (
    "acknowledge_source_attention",
    "suppress_source_attention_for_ttl",
)
ACK_ACTIONABLE_ACTIONS = ("acknowledge_once", "suppress_for_ttl")
LIVENESS_ACK_STATE_MUTATION_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_mutation.v1"
)
LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_expiry_reconciliation.v1"
)


class OperatorReviewLivenessAckStateError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.detail = message
        self.status_code = status_code


@dataclass
class OperatorReviewLivenessAckStateStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["ack_state_id"]] = record
        return record

    def get(self, ack_state_id: str) -> dict[str, Any] | None:
        return self.records.get(ack_state_id)

    def get_by_acknowledgement_key(
        self,
        acknowledgement_key: str,
    ) -> dict[str, Any] | None:
        for record in self.records.values():
            if record.get("acknowledgement_key") == acknowledgement_key:
                return record
        return None

    def list_states(
        self,
        *,
        service_id: str | None = None,
        worker_id: str | None = None,
        liveness_status: str | None = None,
        state_status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        selected = [
            record
            for record in self.records.values()
            if _ack_state_matches_filter(
                record,
                service_id=service_id,
                worker_id=worker_id,
                liveness_status=liveness_status,
                state_status=state_status,
            )
        ]
        selected.sort(
            key=lambda record: (
                str(record.get("updated_at") or ""),
                str(record.get("ack_state_id") or ""),
            ),
            reverse=True,
        )
        return selected[:normalize_ack_state_limit(limit)]

    def delete(self, ack_state_id: str) -> int:
        return 1 if self.records.pop(ack_state_id, None) is not None else 0


class SqlAlchemyOperatorReviewLivenessAckStateStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_ack_state_upsert_sql(_dialect_name(session))),
                    _ack_state_record_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise _ack_state_store_unavailable_error() from exc

    def get(self, ack_state_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_ack_state_select_sql("ack_state_id = :ack_state_id")),
                        {"ack_state_id": ack_state_id},
                    )
                    .mappings()
                    .first()
                )
            return _ack_state_record_from_row(row) if row else None
        except SQLAlchemyError as exc:
            raise _ack_state_store_unavailable_error() from exc

    def get_by_acknowledgement_key(
        self,
        acknowledgement_key: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _ack_state_select_sql(
                                "acknowledgement_key = :acknowledgement_key"
                            )
                        ),
                        {"acknowledgement_key": acknowledgement_key},
                    )
                    .mappings()
                    .first()
                )
            return _ack_state_record_from_row(row) if row else None
        except SQLAlchemyError as exc:
            raise _ack_state_store_unavailable_error() from exc

    def list_states(
        self,
        *,
        service_id: str | None = None,
        worker_id: str | None = None,
        liveness_status: str | None = None,
        state_status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where_clause, params = _ack_state_filter_clause(
            service_id=service_id,
            worker_id=worker_id,
            liveness_status=liveness_status,
            state_status=state_status,
        )
        params["limit"] = normalize_ack_state_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _ack_state_select_sql(
                                where_clause
                                + " ORDER BY updated_at DESC, ack_state_id ASC"
                                + " LIMIT :limit"
                            )
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_ack_state_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _ack_state_store_unavailable_error() from exc

    def delete(self, ack_state_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        "DELETE FROM ag_op_review_ack_state "
                        "WHERE ack_state_id = :ack_state_id"
                    ),
                    {"ack_state_id": ack_state_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise _ack_state_store_unavailable_error() from exc


DEFAULT_OPERATOR_REVIEW_LIVENESS_ACK_STATE_STORE = (
    OperatorReviewLivenessAckStateStore()
)


def default_operator_review_liveness_ack_state_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyOperatorReviewLivenessAckStateStore(session_factory)
    return DEFAULT_OPERATOR_REVIEW_LIVENESS_ACK_STATE_STORE


def build_operator_review_liveness_ack_state_record(
    *,
    ack_state_id: str,
    acknowledgement_key: str,
    service_id: str,
    worker_id: str,
    worker_type: str,
    liveness_status: str,
    action: str,
    state_status: str,
    operator_ref: dict[str, Any],
    reason_codes: list[str],
    comment: str | None = None,
    idempotency_key: str | None = None,
    requested_ttl_seconds: int | None = None,
    suppressed_until: object | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: object | None = None,
    updated_at: object | None = None,
    cleared_at: object | None = None,
) -> dict[str, Any]:
    normalized_action = _required_choice(
        action,
        ACK_ACTIONS,
        "ag.operator_review_liveness_ack_state_action_invalid",
        "action",
    )
    normalized_state_status = _required_choice(
        state_status,
        ACK_STATE_STATUSES,
        "ag.operator_review_liveness_ack_state_status_invalid",
        "state_status",
    )
    normalized_liveness_status = _required_choice(
        liveness_status,
        ACK_LIVENESS_STATUSES,
        "ag.operator_review_liveness_ack_liveness_status_invalid",
        "liveness_status",
    )
    normalized_operator_ref = _operator_ref(operator_ref)
    normalized_reason_codes = _reason_codes(reason_codes)
    if not normalized_reason_codes:
        raise OperatorReviewLivenessAckStateError(
            "reason_codes must contain at least one bounded reason code.",
            error_code="ag.operator_review_liveness_ack_reason_codes_required",
        )
    if normalized_action in ACK_TTL_ACTIONS and suppressed_until is None:
        raise OperatorReviewLivenessAckStateError(
            "suppressed_until is required for TTL suppression actions.",
            error_code="ag.operator_review_liveness_ack_suppressed_until_required",
        )
    normalized_comment = _optional_text(comment)
    normalized_idempotency_key = _optional_text(idempotency_key)
    observed_created_at = _datetime_value(created_at) if created_at else _utc_now()
    observed_updated_at = (
        _datetime_value(updated_at) if updated_at else observed_created_at
    )
    return {
        "ack_state_schema_version": LIVENESS_ACK_STATE_SCHEMA_VERSION,
        "ack_state_id": _required_text(
            ack_state_id,
            "ag.operator_review_liveness_ack_state_id_invalid",
            "ack_state_id",
        ),
        "acknowledgement_key": _required_text(
            acknowledgement_key,
            "ag.operator_review_liveness_ack_key_invalid",
            "acknowledgement_key",
        ),
        "service_id": _required_text(
            service_id,
            "ag.operator_review_liveness_ack_service_id_invalid",
            "service_id",
        ),
        "worker_id": _required_text(
            worker_id,
            "ag.operator_review_liveness_ack_worker_id_invalid",
            "worker_id",
        ),
        "worker_type": _required_text(
            worker_type,
            "ag.operator_review_liveness_ack_worker_type_invalid",
            "worker_type",
        ),
        "liveness_status": normalized_liveness_status,
        "action": normalized_action,
        "state_status": normalized_state_status,
        "operator_ref": normalized_operator_ref,
        "reason_codes": normalized_reason_codes,
        "comment_hash": sha256_text(normalized_comment)
        if normalized_comment is not None
        else None,
        "comment_preview": _comment_preview(normalized_comment),
        "idempotency_key_hash": sha256_text(normalized_idempotency_key)
        if normalized_idempotency_key is not None
        else None,
        "requested_ttl_seconds": _optional_positive_int(
            requested_ttl_seconds,
            "requested_ttl_seconds",
        ),
        "suppressed_until": (
            _datetime_value(suppressed_until) if suppressed_until else None
        ),
        "metadata": _metadata(metadata),
        "created_at": observed_created_at,
        "updated_at": observed_updated_at,
        "cleared_at": _datetime_value(cleared_at) if cleared_at else None,
    }


def acknowledgement_key_for_liveness(
    *,
    service_id: str,
    worker_id: str,
    liveness_status: str,
) -> str:
    normalized_service_id = _required_text(
        service_id,
        "ag.operator_review_liveness_ack_service_id_invalid",
        "service_id",
    )
    normalized_worker_id = _required_text(
        worker_id,
        "ag.operator_review_liveness_ack_worker_id_invalid",
        "worker_id",
    )
    normalized_liveness_status = _required_choice(
        liveness_status,
        ACK_LIVENESS_STATUSES,
        "ag.operator_review_liveness_ack_liveness_status_invalid",
        "liveness_status",
    )
    return (
        f"{normalized_service_id}:{normalized_worker_id}:"
        f"{normalized_liveness_status.lower()}"
    )


def ack_state_id_for_acknowledgement_key(acknowledgement_key: str) -> str:
    normalized_key = _required_text(
        acknowledgement_key,
        "ag.operator_review_liveness_ack_key_invalid",
        "acknowledgement_key",
    )
    return f"ack-{uuid5(NAMESPACE_URL, f'nex-ag:{normalized_key}')}"


def build_operator_review_liveness_ack_state_transition(
    existing_state: dict[str, Any] | None = None,
    *,
    service_id: str,
    worker_id: str,
    worker_type: str,
    liveness_status: str,
    action: str,
    requested_ttl_seconds: int | None = None,
    suppressed_until: object | None = None,
    observed_at: object | None = None,
) -> dict[str, Any]:
    normalized_liveness_status = _required_choice(
        liveness_status,
        ACK_LIVENESS_STATUSES,
        "ag.operator_review_liveness_ack_liveness_status_invalid",
        "liveness_status",
    )
    normalized_action = _required_choice(
        action,
        ACK_ACTIONS,
        "ag.operator_review_liveness_ack_state_action_invalid",
        "action",
    )
    observed = _datetime_value(observed_at) if observed_at else _utc_now()
    _required_text(
        service_id,
        "ag.operator_review_liveness_ack_service_id_invalid",
        "service_id",
    )
    _required_text(
        worker_id,
        "ag.operator_review_liveness_ack_worker_id_invalid",
        "worker_id",
    )
    _required_text(
        worker_type,
        "ag.operator_review_liveness_ack_worker_type_invalid",
        "worker_type",
    )
    if normalized_action == "clear":
        if existing_state is None:
            raise OperatorReviewLivenessAckStateError(
                "clear requires an existing acknowledgement state.",
                error_code="ag.operator_review_liveness_ack_clear_state_missing",
            )
        target_status = "CLEARED"
    else:
        allowed_actions = _allowed_actions_for_liveness(normalized_liveness_status)
        if normalized_action not in allowed_actions:
            raise OperatorReviewLivenessAckStateError(
                "action is not allowed for the current liveness status.",
                error_code="ag.operator_review_liveness_ack_action_not_allowed",
            )
        target_status = _state_status_for_action(normalized_action)

    ttl_seconds = _transition_ttl_seconds(
        normalized_action,
        requested_ttl_seconds,
    )
    expires_at = _transition_suppressed_until(
        normalized_action,
        ttl_seconds,
        suppressed_until,
        observed,
    )
    acknowledgement_key = acknowledgement_key_for_liveness(
        service_id=service_id,
        worker_id=worker_id,
        liveness_status=normalized_liveness_status,
    )
    previous_status = (
        str(existing_state.get("state_status") or "")
        if isinstance(existing_state, dict)
        else None
    )
    return {
        "mutation_schema_version": LIVENESS_ACK_STATE_MUTATION_SCHEMA_VERSION,
        "transition_status": "ACCEPTED",
        "acknowledgement_key": acknowledgement_key,
        "ack_state_id": ack_state_id_for_acknowledgement_key(acknowledgement_key),
        "action": normalized_action,
        "previous_state_status": previous_status,
        "target_state_status": target_status,
        "liveness_status": normalized_liveness_status,
        "requested_ttl_seconds": ttl_seconds,
        "suppressed_until": expires_at,
        "observed_at": observed,
        "guardrails": {
            "source_liveness_projection_suppressed": False,
            "raw_comment_stored": False,
            "raw_idempotency_key_stored": False,
            "process_control_invoked": False,
        },
    }


def apply_operator_review_liveness_ack_state_transition(
    existing_state: dict[str, Any] | None = None,
    *,
    service_id: str,
    worker_id: str,
    worker_type: str,
    liveness_status: str,
    action: str,
    operator_ref: dict[str, Any],
    reason_codes: list[str],
    comment: str | None = None,
    idempotency_key: str | None = None,
    requested_ttl_seconds: int | None = None,
    suppressed_until: object | None = None,
    observed_at: object | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transition = build_operator_review_liveness_ack_state_transition(
        existing_state,
        service_id=service_id,
        worker_id=worker_id,
        worker_type=worker_type,
        liveness_status=liveness_status,
        action=action,
        requested_ttl_seconds=requested_ttl_seconds,
        suppressed_until=suppressed_until,
        observed_at=observed_at,
    )
    state_metadata = dict(metadata or {})
    state_metadata["last_transition"] = transition
    state = build_operator_review_liveness_ack_state_record(
        ack_state_id=transition["ack_state_id"],
        acknowledgement_key=transition["acknowledgement_key"],
        service_id=service_id,
        worker_id=worker_id,
        worker_type=worker_type,
        liveness_status=transition["liveness_status"],
        action=transition["action"],
        state_status=transition["target_state_status"],
        operator_ref=operator_ref,
        reason_codes=reason_codes,
        comment=comment,
        idempotency_key=idempotency_key,
        requested_ttl_seconds=transition["requested_ttl_seconds"],
        suppressed_until=transition["suppressed_until"],
        metadata=state_metadata,
        created_at=(
            existing_state.get("created_at")
            if isinstance(existing_state, dict)
            and existing_state.get("created_at") is not None
            else transition["observed_at"]
        ),
        updated_at=transition["observed_at"],
        cleared_at=(
            transition["observed_at"]
            if transition["target_state_status"] == "CLEARED"
            else None
        ),
    )
    return {
        "mutation_schema_version": LIVENESS_ACK_STATE_MUTATION_SCHEMA_VERSION,
        "mutation_status": "ACCEPTED",
        "transition": transition,
        "state": state,
    }


def project_operator_review_liveness_ack_state_effective_status(
    state: dict[str, Any] | None,
    *,
    observed_at: object | None = None,
) -> dict[str, Any]:
    observed = _datetime_value(observed_at) if observed_at else _utc_now()
    if not isinstance(state, dict):
        return {
            "projection_schema_version": (
                "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_effective_status.v1"
            ),
            "projection_status": "MISSING",
            "observed_at": observed,
            "state_present": False,
            "stored_state_status": None,
            "effective_state_status": None,
            "expired": False,
            "suppressed_until": None,
        }
    stored_status = str(state.get("state_status") or "")
    suppressed_until = state.get("suppressed_until")
    expired = (
        stored_status == "SUPPRESSED"
        and suppressed_until is not None
        and _parse_datetime(suppressed_until) <= _parse_datetime(observed)
    )
    return {
        "projection_schema_version": (
            "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_effective_status.v1"
        ),
        "projection_status": "READY",
        "observed_at": observed,
        "state_present": True,
        "stored_state_status": stored_status,
        "effective_state_status": "EXPIRED" if expired else stored_status,
        "expired": expired,
        "suppressed_until": (
            _datetime_value(suppressed_until) if suppressed_until is not None else None
        ),
    }


def build_operator_review_liveness_ack_expiry_reconciliation_candidate(
    state: dict[str, Any] | None,
    *,
    observed_at: object | None = None,
) -> dict[str, Any]:
    observed = _datetime_value(observed_at) if observed_at else _utc_now()
    if not isinstance(state, dict):
        return {
            "reconciliation_schema_version": (
                LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION
            ),
            "candidate_status": "SKIPPED",
            "reason": "state_missing",
            "observed_at": observed,
            "ack_state_id": None,
            "acknowledgement_key": None,
            "expected_state_status": None,
            "expected_updated_at": None,
            "target_state_status": None,
        }
    projection = project_operator_review_liveness_ack_state_effective_status(
        state,
        observed_at=observed,
    )
    stored_status = projection["stored_state_status"]
    suppressed_until = projection["suppressed_until"]
    if stored_status != "SUPPRESSED":
        candidate_status = "SKIPPED"
        reason = "state_not_suppressed"
    elif suppressed_until is None:
        candidate_status = "SKIPPED"
        reason = "suppression_deadline_missing"
    elif projection["expired"] is not True:
        candidate_status = "SKIPPED"
        reason = "suppression_active"
    else:
        candidate_status = "ELIGIBLE"
        reason = "suppression_expired"
    return {
        "reconciliation_schema_version": (
            LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION
        ),
        "candidate_status": candidate_status,
        "reason": reason,
        "observed_at": observed,
        "ack_state_id": state.get("ack_state_id"),
        "acknowledgement_key": state.get("acknowledgement_key"),
        "expected_state_status": stored_status,
        "expected_updated_at": state.get("updated_at"),
        "target_state_status": "EXPIRED" if candidate_status == "ELIGIBLE" else None,
        "suppressed_until": suppressed_until,
        "guardrails": {
            "compare_and_set_required": True,
            "source_liveness_projection_mutated": False,
            "raw_comment_required": False,
            "raw_payload_required": False,
        },
    }


def apply_operator_review_liveness_ack_expiry_reconciliation(
    state: dict[str, Any] | None,
    *,
    observed_at: object | None = None,
) -> dict[str, Any]:
    candidate = build_operator_review_liveness_ack_expiry_reconciliation_candidate(
        state,
        observed_at=observed_at,
    )
    if candidate["candidate_status"] != "ELIGIBLE":
        return {
            "reconciliation_schema_version": (
                LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION
            ),
            "mutation_status": "SKIPPED",
            "candidate": candidate,
            "state": dict(state) if isinstance(state, dict) else None,
        }
    updated = dict(state or {})
    metadata = dict(updated.get("metadata") or {})
    metadata["last_expiry_reconciliation"] = {
        "observed_at": candidate["observed_at"],
        "previous_state_status": candidate["expected_state_status"],
        "target_state_status": candidate["target_state_status"],
        "reason": candidate["reason"],
    }
    updated.update(
        {
            "state_status": "EXPIRED",
            "updated_at": candidate["observed_at"],
            "metadata": metadata,
        }
    )
    return {
        "reconciliation_schema_version": (
            LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION
        ),
        "mutation_status": "APPLIED",
        "candidate": candidate,
        "state": updated,
    }


def build_operator_review_liveness_ack_state_list_response(
    states: list[dict[str, Any]],
    *,
    checked_at: object | None = None,
) -> dict[str, Any]:
    selected = list(states)
    return {
        "projection_schema_version": LIVENESS_ACK_STATE_LIST_SCHEMA_VERSION,
        "projection_status": "READY",
        "checked_at": _datetime_value(checked_at) if checked_at else _utc_now(),
        "state_count": len(selected),
        "states": selected,
        "source_table": AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
        "redaction": {
            "raw_comment_included": False,
            "raw_idempotency_key_included": False,
            "raw_payloads_included": False,
        },
    }


def normalize_ack_state_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_ACK_STATE_LIMIT
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as exc:
        raise OperatorReviewLivenessAckStateError(
            "limit must be an integer.",
            error_code="ag.operator_review_liveness_ack_limit_invalid",
        ) from exc
    return max(1, min(parsed, MAX_ACK_STATE_LIMIT))


def _ack_state_matches_filter(
    record: dict[str, Any],
    *,
    service_id: str | None,
    worker_id: str | None,
    liveness_status: str | None,
    state_status: str | None,
) -> bool:
    return all(
        (
            service_id is None or record.get("service_id") == service_id,
            worker_id is None or record.get("worker_id") == worker_id,
            liveness_status is None
            or record.get("liveness_status") == liveness_status,
            state_status is None or record.get("state_status") == state_status,
        )
    )


def _ack_state_filter_clause(
    *,
    service_id: str | None,
    worker_id: str | None,
    liveness_status: str | None,
    state_status: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    for name, value in (
        ("service_id", service_id),
        ("worker_id", worker_id),
        ("liveness_status", liveness_status),
        ("state_status", state_status),
    ):
        if value is not None:
            clauses.append(f"{name} = :{name}")
            params[name] = value
    return " AND ".join(clauses), params


def _ack_state_upsert_sql(dialect_name: str) -> str:
    operator_ref_expr = _json_param_expr("operator_ref", dialect_name)
    reason_codes_expr = _json_param_expr("reason_codes", dialect_name)
    metadata_expr = _json_param_expr("metadata", dialect_name)
    return f"""
        INSERT INTO ag_op_review_ack_state (
            ack_state_id,
            ack_state_schema_version,
            acknowledgement_key,
            service_id,
            worker_id,
            worker_type,
            liveness_status,
            action,
            state_status,
            operator_type,
            operator_id,
            tenant_id,
            operator_ref,
            reason_codes,
            comment_hash,
            comment_preview,
            idempotency_key_hash,
            requested_ttl_seconds,
            suppressed_until,
            metadata,
            created_at,
            updated_at,
            cleared_at
        )
        VALUES (
            :ack_state_id,
            :ack_state_schema_version,
            :acknowledgement_key,
            :service_id,
            :worker_id,
            :worker_type,
            :liveness_status,
            :action,
            :state_status,
            :operator_type,
            :operator_id,
            :tenant_id,
            {operator_ref_expr},
            {reason_codes_expr},
            :comment_hash,
            :comment_preview,
            :idempotency_key_hash,
            :requested_ttl_seconds,
            :suppressed_until,
            {metadata_expr},
            :created_at,
            :updated_at,
            :cleared_at
        )
        ON CONFLICT (ack_state_id) DO UPDATE SET
            ack_state_schema_version = excluded.ack_state_schema_version,
            acknowledgement_key = excluded.acknowledgement_key,
            service_id = excluded.service_id,
            worker_id = excluded.worker_id,
            worker_type = excluded.worker_type,
            liveness_status = excluded.liveness_status,
            action = excluded.action,
            state_status = excluded.state_status,
            operator_type = excluded.operator_type,
            operator_id = excluded.operator_id,
            tenant_id = excluded.tenant_id,
            operator_ref = excluded.operator_ref,
            reason_codes = excluded.reason_codes,
            comment_hash = excluded.comment_hash,
            comment_preview = excluded.comment_preview,
            idempotency_key_hash = excluded.idempotency_key_hash,
            requested_ttl_seconds = excluded.requested_ttl_seconds,
            suppressed_until = excluded.suppressed_until,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at,
            cleared_at = excluded.cleared_at
    """


def _ack_state_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            ack_state_schema_version,
            ack_state_id,
            acknowledgement_key,
            service_id,
            worker_id,
            worker_type,
            liveness_status,
            action,
            state_status,
            operator_ref,
            reason_codes,
            comment_hash,
            comment_preview,
            idempotency_key_hash,
            requested_ttl_seconds,
            suppressed_until,
            metadata,
            created_at,
            updated_at,
            cleared_at
        FROM ag_op_review_ack_state
        WHERE {where_clause}
    """


def _ack_state_record_params(record: dict[str, Any]) -> dict[str, Any]:
    operator = record["operator_ref"]
    return {
        **record,
        "operator_type": operator["operator_type"],
        "operator_id": operator["operator_id"],
        "tenant_id": operator.get("tenant_id"),
        "operator_ref": json.dumps(record["operator_ref"]),
        "reason_codes": json.dumps(record["reason_codes"]),
        "metadata": json.dumps(record["metadata"]),
    }


def _ack_state_record_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "ack_state_schema_version": data["ack_state_schema_version"],
        "ack_state_id": data["ack_state_id"],
        "acknowledgement_key": data["acknowledgement_key"],
        "service_id": data["service_id"],
        "worker_id": data["worker_id"],
        "worker_type": data["worker_type"],
        "liveness_status": data["liveness_status"],
        "action": data["action"],
        "state_status": data["state_status"],
        "operator_ref": _json_value(data["operator_ref"], {}),
        "reason_codes": _json_value(data["reason_codes"], []),
        "comment_hash": data["comment_hash"],
        "comment_preview": data["comment_preview"],
        "idempotency_key_hash": data["idempotency_key_hash"],
        "requested_ttl_seconds": data["requested_ttl_seconds"],
        "suppressed_until": (
            _datetime_value(data["suppressed_until"])
            if data["suppressed_until"]
            else None
        ),
        "metadata": _json_value(data["metadata"], {}),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
        "cleared_at": _datetime_value(data["cleared_at"])
        if data["cleared_at"]
        else None,
    }


def _required_text(value: object, error_code: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperatorReviewLivenessAckStateError(
            f"{field_name} must be a non-empty string.",
            error_code=error_code,
        )
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OperatorReviewLivenessAckStateError(
            "optional text fields must be strings when provided.",
            error_code="ag.operator_review_liveness_ack_text_invalid",
        )
    stripped = value.strip()
    return stripped or None


def _required_choice(
    value: object,
    choices: tuple[str, ...],
    error_code: str,
    field_name: str,
) -> str:
    normalized = _required_text(value, error_code, field_name)
    if normalized not in choices:
        raise OperatorReviewLivenessAckStateError(
            f"{field_name} must be one of {', '.join(choices)}.",
            error_code=error_code,
        )
    return normalized


def _operator_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperatorReviewLivenessAckStateError(
            "operator_ref must be an object.",
            error_code="ag.operator_review_liveness_ack_operator_ref_invalid",
        )
    operator_type = _required_text(
        value.get("operator_type"),
        "ag.operator_review_liveness_ack_operator_type_invalid",
        "operator_type",
    )
    if operator_type not in {"service", "user"}:
        raise OperatorReviewLivenessAckStateError(
            "operator_type must be one of service, user.",
            error_code="ag.operator_review_liveness_ack_operator_type_invalid",
        )
    operator_id = _required_text(
        value.get("operator_id"),
        "ag.operator_review_liveness_ack_operator_id_invalid",
        "operator_id",
    )
    normalized = {
        "operator_type": operator_type,
        "operator_id": operator_id,
    }
    tenant_id = _optional_text(value.get("tenant_id"))
    if tenant_id is not None:
        normalized["tenant_id"] = tenant_id
    return normalized


def _reason_codes(value: object) -> list[str]:
    if not isinstance(value, list):
        raise OperatorReviewLivenessAckStateError(
            "reason_codes must be a list.",
            error_code="ag.operator_review_liveness_ack_reason_codes_invalid",
        )
    normalized: list[str] = []
    for item in value:
        reason = _required_text(
            item,
            "ag.operator_review_liveness_ack_reason_code_invalid",
            "reason_code",
        )
        if len(reason) > 80:
            raise OperatorReviewLivenessAckStateError(
                "reason_code must be 80 characters or fewer.",
                error_code="ag.operator_review_liveness_ack_reason_code_too_long",
            )
        normalized.append(reason)
    return normalized


def _metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {
            "state_storage": "ag_owned_ack_suppression_overlay_only",
            "raw_comment_stored": False,
            "raw_idempotency_key_stored": False,
            "source_liveness_projection_suppressed": False,
        }
    if not isinstance(value, dict):
        raise OperatorReviewLivenessAckStateError(
            "metadata must be an object.",
            error_code="ag.operator_review_liveness_ack_metadata_invalid",
        )
    return {
        **value,
        "state_storage": "ag_owned_ack_suppression_overlay_only",
        "raw_comment_stored": False,
        "raw_idempotency_key_stored": False,
        "source_liveness_projection_suppressed": False,
    }


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise OperatorReviewLivenessAckStateError(
            f"{field_name} must be an integer.",
            error_code="ag.operator_review_liveness_ack_positive_int_invalid",
        ) from exc
    if parsed <= 0:
        raise OperatorReviewLivenessAckStateError(
            f"{field_name} must be greater than zero.",
            error_code="ag.operator_review_liveness_ack_positive_int_invalid",
        )
    return parsed


def _comment_preview(value: str | None) -> str | None:
    preview = operator_note_preview(value)
    if preview is None:
        return None
    return preview[:MAX_ACK_COMMENT_PREVIEW_LENGTH]


def _ack_state_store_unavailable_error() -> OperatorReviewLivenessAckStateError:
    return OperatorReviewLivenessAckStateError(
        "operator review liveness acknowledgement state store is unavailable.",
        error_code="ag.operator_review_liveness_ack_state_store_unavailable",
        status_code=503,
    )


def _allowed_actions_for_liveness(liveness_status: str) -> tuple[str, ...]:
    if liveness_status in {"MISSING", "STALE"}:
        return ACK_ACTIONABLE_ACTIONS
    if liveness_status in {"SOURCE_NOT_CONFIGURED", "SOURCE_UNAVAILABLE"}:
        return ACK_SOURCE_ATTENTION_ACTIONS
    return ()


def _state_status_for_action(action: str) -> str:
    if action in {"acknowledge_once", "acknowledge_source_attention"}:
        return "ACKNOWLEDGED"
    if action in ACK_TTL_ACTIONS:
        return "SUPPRESSED"
    if action == "clear":
        return "CLEARED"
    raise OperatorReviewLivenessAckStateError(
        "action is not supported by the acknowledgement state machine.",
        error_code="ag.operator_review_liveness_ack_state_action_invalid",
    )


def _transition_ttl_seconds(action: str, requested_ttl_seconds: int | None) -> int | None:
    if action not in ACK_TTL_ACTIONS:
        return None
    ttl_seconds = (
        DEFAULT_SUPPRESSION_TTL_SECONDS
        if requested_ttl_seconds is None
        else _optional_positive_int(requested_ttl_seconds, "requested_ttl_seconds")
    )
    if ttl_seconds > MAX_SUPPRESSION_TTL_SECONDS:
        raise OperatorReviewLivenessAckStateError(
            "requested_ttl_seconds exceeds the maximum suppression TTL.",
            error_code="ag.operator_review_liveness_ack_ttl_too_large",
        )
    return ttl_seconds


def _transition_suppressed_until(
    action: str,
    ttl_seconds: int | None,
    suppressed_until: object | None,
    observed_at: str,
) -> str | None:
    if action not in ACK_TTL_ACTIONS:
        return None
    if suppressed_until is not None:
        return _datetime_value(suppressed_until)
    if ttl_seconds is None:
        raise OperatorReviewLivenessAckStateError(
            "requested_ttl_seconds is required for TTL suppression.",
            error_code="ag.operator_review_liveness_ack_ttl_required",
        )
    expires_at = _parse_datetime(observed_at) + timedelta(seconds=ttl_seconds)
    return expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime:
    normalized = _datetime_value(value)
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise OperatorReviewLivenessAckStateError(
            "datetime values must be ISO-8601 timestamps.",
            error_code="ag.operator_review_liveness_ack_datetime_invalid",
        ) from exc
