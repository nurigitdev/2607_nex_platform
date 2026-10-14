from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

P5_STEP_RESULT_SCHEMA_VERSION = "1.1"
P6_STEP_RESULT_SCHEMA_VERSION = "1.2"
STEP_RESULT_SCHEMA_VERSION = P5_STEP_RESULT_SCHEMA_VERSION
TERMINAL_RESULT_STATUSES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"})
STEP_RESULT_EXECUTOR_KINDS = frozenset(
    {
        "P4_CHAT_RAG_COMPATIBILITY",
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
    }
)
_COMPILED_STEP_KEY = re.compile(r"^E[0-9]{1,3}$")
_LOGICAL_STEP_ID = re.compile(r"^S[0-9]{1,3}$")


@dataclass
class StepResultError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_step_result(
    *,
    step_result_id: str,
    execution_id: str,
    executable_plan_id: str,
    executable_step_id: str,
    compiled_step_key: str,
    logical_step_ref: str,
    attempt_no: int,
    status: str,
    result_contract_ref: str,
    result_payload: Mapping[str, Any],
    started_at: str,
    completed_at: str,
    external_refs: Sequence[str] = (),
    artifact_refs: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
    error_ref: str | None = None,
    executor_kind: str | None = None,
    business_operation_id: str | None = None,
) -> dict[str, Any]:
    schema_version = (
        P5_STEP_RESULT_SCHEMA_VERSION
        if executor_kind is None
        else P6_STEP_RESULT_SCHEMA_VERSION
    )
    result: dict[str, Any] = {
        "schema_version": schema_version,
        "step_result_id": _required_uuid("step_result_id", step_result_id),
        "execution_id": _required_uuid("execution_id", execution_id),
        "executable_plan_id": _required_uuid("executable_plan_id", executable_plan_id),
        "executable_step_id": _required_uuid("executable_step_id", executable_step_id),
        "compiled_step_key": _compiled_key(compiled_step_key),
        "logical_step_ref": _logical_step(logical_step_ref),
        "attempt_no": _positive_int("attempt_no", attempt_no),
        "status": _terminal_status(status),
        "result_contract_ref": _required_text(
            "result_contract_ref", result_contract_ref, 256
        ),
        "result_payload": _mapping("result_payload", result_payload),
        "external_refs": _references("external_refs", external_refs, 64),
        "artifact_refs": _references("artifact_refs", artifact_refs, 64),
        "evidence_refs": _references("evidence_refs", evidence_refs, 128),
        "error_ref": _optional_text("error_ref", error_ref, 256),
        "business_operation_id": business_operation_id,
        "operation_fingerprint": None,
        "started_at": _timestamp("started_at", started_at),
        "completed_at": _timestamp("completed_at", completed_at),
    }
    if executor_kind is not None:
        result["executor_kind"] = executor_kind
    if _parse_timestamp(result["completed_at"]) < _parse_timestamp(
        result["started_at"]
    ):
        raise _invalid("StepResult completed_at precedes started_at.")
    result["result_hash"] = semantic_sha256_hash_ref(
        step_result_semantic_projection(result)
    )
    return validate_step_result_contract(result)


def step_result_semantic_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key
        not in {
            "step_result_id",
            "started_at",
            "completed_at",
            "result_hash",
        }
    }


def validate_step_result_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("StepResult must be canonical JSON.") from exc
    required = {
        "schema_version",
        "step_result_id",
        "execution_id",
        "executable_plan_id",
        "executable_step_id",
        "compiled_step_key",
        "logical_step_ref",
        "attempt_no",
        "status",
        "result_contract_ref",
        "result_payload",
        "external_refs",
        "artifact_refs",
        "evidence_refs",
        "business_operation_id",
        "operation_fingerprint",
        "started_at",
        "completed_at",
        "result_hash",
    }
    schema_version = result.get("schema_version")
    optional = {"error_ref"}
    if schema_version == P6_STEP_RESULT_SCHEMA_VERSION:
        required.add("executor_kind")
    if (
        not required.issubset(result)
        or not set(result).issubset(required | optional)
        or schema_version
        not in {P5_STEP_RESULT_SCHEMA_VERSION, P6_STEP_RESULT_SCHEMA_VERSION}
    ):
        raise _invalid("StepResult fields or schema version are invalid.")
    for field in (
        "step_result_id",
        "execution_id",
        "executable_plan_id",
        "executable_step_id",
    ):
        _required_uuid(field, result[field])
    _compiled_key(result["compiled_step_key"])
    _logical_step(result["logical_step_ref"])
    _positive_int("attempt_no", result["attempt_no"])
    _terminal_status(result["status"])
    _required_text("result_contract_ref", result["result_contract_ref"], 256)
    _mapping("result_payload", result["result_payload"])
    _references("external_refs", result["external_refs"], 64)
    _references("artifact_refs", result["artifact_refs"], 64)
    _references("evidence_refs", result["evidence_refs"], 128)
    _optional_text("error_ref", result.get("error_ref"), 256)
    if result["operation_fingerprint"] is not None:
        raise _invalid("StepResult operation fingerprint must remain null.")
    if schema_version == P5_STEP_RESULT_SCHEMA_VERSION:
        if result["business_operation_id"] is not None:
            raise _invalid("P5 StepResult WRITE identity must remain null.")
    else:
        executor_kind = result["executor_kind"]
        if executor_kind not in STEP_RESULT_EXECUTOR_KINDS:
            raise _invalid("P6 StepResult executor_kind is invalid.")
        if executor_kind == "LOCAL_SKILL":
            _required_uuid("business_operation_id", result["business_operation_id"])
        elif result["business_operation_id"] is not None:
            raise _invalid("Non-LOCAL_SKILL StepResult identity must remain null.")
    started = _timestamp("started_at", result["started_at"])
    completed = _timestamp("completed_at", result["completed_at"])
    if _parse_timestamp(completed) < _parse_timestamp(started):
        raise _invalid("StepResult completed_at precedes started_at.")
    try:
        validate_hash_ref(result["result_hash"])
    except ValueError as exc:
        raise _invalid("StepResult result_hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(step_result_semantic_projection(result))
    if result["result_hash"] != expected:
        raise _invalid("StepResult hash does not match semantic content.")
    return result


class SqlAlchemyStepResultRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, *, tenant_id: str, step_result: Mapping[str, Any]) -> dict[str, Any]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        result = validate_step_result_contract(step_result)
        try:
            with self._session_factory() as session:
                step = _load_step_lineage(session, tenant, result["executable_step_id"])
                _require_step_lineage(step, result)
                saved = persist_step_result_in_session(session, tenant, result)
                session.commit()
                return saved
        except StepResultError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(self, *, tenant_id: str, step_result_id: str) -> dict[str, Any] | None:
        tenant = _required_text("tenant_id", tenant_id, 128)
        result_id = _required_uuid("step_result_id", step_result_id)
        try:
            with self._session_factory() as session:
                return load_step_result_by_id(session, tenant, result_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_by_step(
        self, *, tenant_id: str, executable_step_id: str
    ) -> dict[str, Any] | None:
        tenant = _required_text("tenant_id", tenant_id, 128)
        step_id = _required_uuid("executable_step_id", executable_step_id)
        try:
            with self._session_factory() as session:
                return load_step_result_by_step(session, tenant, step_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_for_plan(
        self, *, tenant_id: str, executable_plan_id: str
    ) -> list[dict[str, Any]]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        plan_id = _required_uuid("executable_plan_id", executable_plan_id)
        try:
            with self._session_factory() as session:
                return load_step_results_for_plan(session, tenant, plan_id)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def persist_step_result_in_session(
    session: Session, tenant_id: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = validate_step_result_contract(result)
    params = _result_params(tenant_id, normalized)
    inserted = session.execute(text(_insert_sql(_dialect_name(session))), params)
    saved = load_step_result_by_id(session, tenant_id, normalized["step_result_id"])
    if saved is None:
        conflict = load_step_result_by_step(
            session, tenant_id, normalized["executable_step_id"]
        )
        if conflict is not None:
            raise StepResultError(
                "ae.step_result_step_conflict",
                "A different StepResult already owns this ExecutableStep.",
            )
        raise StepResultError(
            "ae.step_result_write_conflict",
            "StepResult could not be reloaded after persistence.",
            True,
        )
    if saved != normalized:
        raise StepResultError(
            "ae.step_result_immutable_conflict",
            "StepResult identity exists with different immutable content.",
        )
    if int(inserted.rowcount or 0) == 0:
        by_step = load_step_result_by_step(
            session, tenant_id, normalized["executable_step_id"]
        )
        if by_step != normalized:
            raise StepResultError(
                "ae.step_result_step_conflict",
                "ExecutableStep already has a different terminal result.",
            )
    return saved


def load_step_result_by_id(
    session: Session, tenant_id: str, step_result_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT result_json FROM ae_step_result "
                "WHERE tenant_id = :tenant_id AND step_result_id = :result_id"
            ),
            {"tenant_id": tenant_id, "result_id": step_result_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_object(row["result_json"])


def load_step_result_by_step(
    session: Session, tenant_id: str, executable_step_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT result_json FROM ae_step_result "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
            ),
            {"tenant_id": tenant_id, "step_id": executable_step_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_object(row["result_json"])


def load_step_results_for_plan(
    session: Session, tenant_id: str, executable_plan_id: str
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                "SELECT result_json FROM ae_step_result "
                "WHERE tenant_id = :tenant_id AND executable_plan_id = :plan_id "
                "ORDER BY compiled_step_key"
            ),
            {"tenant_id": tenant_id, "plan_id": executable_plan_id},
        )
        .mappings()
        .all()
    )
    return [_json_object(row["result_json"]) for row in rows]


def _require_step_lineage(
    step: Mapping[str, Any] | None, result: Mapping[str, Any]
) -> None:
    if step is None:
        raise StepResultError(
            "ae.step_result_step_not_found",
            "StepResult requires an existing P5 ExecutableStep.",
        )
    expected = {
        "agent_execution_id": result["execution_id"],
        "executable_plan_id": result["executable_plan_id"],
        "compiled_step_key": result["compiled_step_key"],
        "logical_step_id": result["logical_step_ref"],
        "state": result["status"],
    }
    if result["schema_version"] == P6_STEP_RESULT_SCHEMA_VERSION:
        expected["executor_kind"] = result["executor_kind"]
    if any(str(step.get(key)) != str(value) for key, value in expected.items()):
        raise StepResultError(
            "ae.step_result_lineage_mismatch",
            "StepResult does not match the terminal ExecutableStep lineage.",
        )


def _load_step_lineage(
    session: Session, tenant_id: str, executable_step_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT agent_execution_id, executable_plan_id, compiled_step_key, "
                "logical_step_id, state, executor_kind FROM ae_executable_step "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
            ),
            {"tenant_id": tenant_id, "step_id": executable_step_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _result_params(tenant_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "step_result_id": result["step_result_id"],
        "agent_execution_id": result["execution_id"],
        "executable_plan_id": result["executable_plan_id"],
        "executable_step_id": result["executable_step_id"],
        "compiled_step_key": result["compiled_step_key"],
        "logical_step_id": result["logical_step_ref"],
        "attempt_no": result["attempt_no"],
        "status": result["status"],
        "result_contract_ref": result["result_contract_ref"],
        "result_payload": canonical_json(result["result_payload"]),
        "external_refs": canonical_json(result["external_refs"]),
        "artifact_refs": canonical_json(result["artifact_refs"]),
        "evidence_refs": canonical_json(result["evidence_refs"]),
        "error_ref": result.get("error_ref"),
        "business_operation_id": result["business_operation_id"],
        "operation_fingerprint": None,
        "executor_kind": result.get("executor_kind"),
        "started_at": result["started_at"],
        "completed_at": result["completed_at"],
        "result_hash": result["result_hash"],
        "result_json": canonical_json(result),
    }


def _insert_sql(dialect_name: str) -> str:
    json_value = "CAST(:{name} AS JSONB)" if dialect_name == "postgresql" else ":{name}"
    return """
        INSERT INTO ae_step_result (
            tenant_id, step_result_id, agent_execution_id, executable_plan_id,
            executable_step_id, compiled_step_key, logical_step_id, attempt_no,
            status, result_contract_ref, result_payload, external_refs,
            artifact_refs, evidence_refs, error_ref, business_operation_id,
            operation_fingerprint, executor_kind, started_at, completed_at, result_hash,
            result_json
        ) VALUES (
            :tenant_id, :step_result_id, :agent_execution_id,
            :executable_plan_id, :executable_step_id, :compiled_step_key,
            :logical_step_id, :attempt_no, :status, :result_contract_ref,
            {result_payload}, {external_refs}, {artifact_refs}, {evidence_refs},
            :error_ref, :business_operation_id, :operation_fingerprint,
            :executor_kind,
            :started_at, :completed_at, :result_hash, {result_json}
        ) ON CONFLICT DO NOTHING
    """.format(
        result_payload=json_value.format(name="result_payload"),
        external_refs=json_value.format(name="external_refs"),
        artifact_refs=json_value.format(name="artifact_refs"),
        evidence_refs=json_value.format(name="evidence_refs"),
        result_json=json_value.format(name="result_json"),
    )


def _mapping(field: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be canonical JSON.") from exc


def _references(field: str, values: Sequence[str], maximum_items: int) -> list[str]:
    if (
        isinstance(values, (str, bytes))
        or not isinstance(values, Sequence)
        or len(values) > maximum_items
    ):
        raise _invalid(f"{field} must be a bounded reference array.")
    normalized = [_required_text(field, item, 256) for item in values]
    if len(set(normalized)) != len(normalized):
        raise _invalid(f"{field} contains duplicate references.")
    return sorted(normalized)


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _compiled_key(value: object) -> str:
    if not isinstance(value, str) or _COMPILED_STEP_KEY.fullmatch(value) is None:
        raise _invalid("compiled_step_key must be an E-key.")
    return value


def _logical_step(value: object) -> str:
    if not isinstance(value, str) or _LOGICAL_STEP_ID.fullmatch(value) is None:
        raise _invalid("logical_step_ref must be an S-key.")
    return value


def _terminal_status(value: object) -> str:
    if not isinstance(value, str) or value not in TERMINAL_RESULT_STATUSES:
        raise _invalid("StepResult status is not terminal.")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _required_text(field, value, maximum)


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_object(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise StepResultError(
            "ae.step_result_corrupt",
            "Stored StepResult is not an object.",
        )
    return dict(decoded)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> StepResultError:
    return StepResultError("ae.step_result_invalid", detail)


def _unavailable() -> StepResultError:
    return StepResultError(
        "ae.step_result_store_unavailable",
        "AE StepResult store is unavailable.",
        True,
    )
