from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.authorization import (
    AuthorizationSource,
    AuthorizationSubjectDenied,
    require_active_scope,
)
from nex_wc.coordination import InMemoryCoordinationRepository

WORK_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "result_id",
        "work_item_id",
        "revision_no",
        "result_type",
        "summary",
        "payload",
        "schema_ref",
        "technical_outcome",
        "business_outcome",
        "artifact_refs",
        "evidence_refs",
        "business_object_refs",
        "source_execution_ref",
        "source_plan_ref",
        "claim_ref",
        "claim_generation",
        "assignment_ref",
        "submitted_by",
        "trace",
        "submitted_at",
    }
)
REQUIRED_WORK_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "result_id",
        "work_item_id",
        "revision_no",
        "result_type",
        "technical_outcome",
        "business_outcome",
        "submitted_by",
        "trace",
        "submitted_at",
    }
)
TECHNICAL_OUTCOMES = frozenset({"SUCCEEDED", "PARTIAL", "FAILED", "UNKNOWN"})
BUSINESS_OUTCOMES = frozenset(
    {"VERIFIED", "REVISED", "REJECTED", "PENDING_VERIFICATION", "NOT_APPLICABLE"}
)


@dataclass
class WorkResultError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class WorkResultRepository(Protocol):
    def get_result_source(
        self, *, tenant_id: str, result_id: str
    ) -> Mapping[str, Any] | None: ...

    def list_result_sources_by_execution(
        self, *, tenant_id: str, source_execution_ref: str, limit: int
    ) -> Sequence[Mapping[str, Any]]: ...

    def get_submission_context(
        self, *, tenant_id: str, work_item_id: str
    ) -> Mapping[str, Any] | None: ...

    def commit_result(
        self,
        *,
        work_result: Mapping[str, Any],
        result_hash: str,
        expected_version: int,
        authorization: Mapping[str, Any],
        outbox_id: str,
        event_id: str,
        now: str,
    ) -> Mapping[str, Any]: ...

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


class InMemoryWorkResultRepository:
    def __init__(self, coordination: InMemoryCoordinationRepository) -> None:
        self._coordination = coordination
        self._results: dict[tuple[str, str], dict[str, Any]] = {}
        self._work_revisions: dict[tuple[str, str, int], tuple[str, str]] = {}
        self._lock = RLock()

    def get_submission_context(
        self, *, tenant_id: str, work_item_id: str
    ) -> Mapping[str, Any] | None:
        with self._lock:
            record = self._coordination._work_items._records.get(
                (tenant_id, work_item_id)
            )
            if record is None:
                return None
            claims = self._coordination._claims.get((tenant_id, work_item_id), ())
            claim = next(
                (item for item in reversed(claims) if item["state"] == "ACTIVE"),
                claims[-1] if claims else None,
            )
            assignment = self._coordination._assignments.get((tenant_id, work_item_id))
            return _submission_context(record, claim, assignment)

    def get_result_source(
        self, *, tenant_id: str, result_id: str
    ) -> Mapping[str, Any] | None:
        with self._lock:
            record = self._results.get((tenant_id, result_id))
            return None if record is None else copy.deepcopy(record)

    def list_result_sources_by_execution(
        self, *, tenant_id: str, source_execution_ref: str, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            records = [
                copy.deepcopy(record)
                for (record_tenant, _), record in self._results.items()
                if record_tenant == tenant_id
                and record["work_result"].get("source_execution_ref")
                == source_execution_ref
            ]
        records.sort(
            key=lambda record: (
                str(record["work_result"].get("submitted_at") or ""),
                str(record["work_result"].get("result_id") or ""),
            )
        )
        return records[:limit]

    def commit_result(
        self,
        *,
        work_result: Mapping[str, Any],
        result_hash: str,
        expected_version: int,
        authorization: Mapping[str, Any],
        outbox_id: str,
        event_id: str,
        now: str,
    ) -> Mapping[str, Any]:
        result = copy.deepcopy(dict(work_result))
        tenant_id = result["tenant_id"]
        work_item_id = result["work_item_id"]
        with self._lock:
            existing = self._results.get((tenant_id, result["result_id"]))
            if existing is not None:
                _require_same_result(existing, result_hash, work_item_id)
                return _acceptance(existing, created=False)
            revision_key = (tenant_id, work_item_id, result["revision_no"])
            revision_ref = self._work_revisions.get(revision_key)
            if revision_ref is not None:
                existing = self._results[revision_ref]
                _require_same_result(existing, result_hash, work_item_id)
                return _acceptance(existing, created=False)
            record = self._coordination._work_items._records.get(
                (tenant_id, work_item_id)
            )
            if record is None:
                raise _not_found()
            context = self.get_submission_context(
                tenant_id=tenant_id, work_item_id=work_item_id
            )
            _require_commit_authority(context, result, expected_version)
            event = _result_event(result, event_id=event_id, now=now)
            saved = {
                "work_result": result,
                "result_hash": result_hash,
                "work_item_version": expected_version + 1,
                "outbox_id": outbox_id,
                "event_id": event_id,
                "accepted_at": now,
                "authorization_revision_hash": authorization["revision_hash"],
            }
            self._results[(tenant_id, result["result_id"])] = saved
            self._work_revisions[revision_key] = (tenant_id, result["result_id"])
            self._coordination._outbox[(tenant_id, outbox_id)] = {
                "tenant_id": tenant_id,
                "outbox_id": outbox_id,
                "event_id": event_id,
                "work_item_id": work_item_id,
                "event_type": "WORK_RESULT_SUBMITTED",
                "event_payload": event,
                "delivery_state": "PENDING",
                "enqueued_job_id": None,
                "created_at": now,
                "updated_at": now,
            }
            _transition_work_item(record, state="RESULT_SUBMITTED", updated_at=now)
            return _acceptance(saved, created=True)

    def list_pending_result_events(self, *, limit: int) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            rows = [
                copy.deepcopy(row)
                for row in self._coordination._outbox.values()
                if row["event_type"] == "WORK_RESULT_SUBMITTED"
                and row["delivery_state"] == "PENDING"
            ]
            rows.sort(key=lambda row: (row["created_at"], row["outbox_id"]))
            return rows[:limit]

    def mark_result_event_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]:
        return self._update_outbox(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=job_id,
            target_state="ENQUEUED",
            updated_at=updated_at,
        )

    def load_result_event(self, *, outbox_id: str, event_id: str) -> Mapping[str, Any]:
        with self._lock:
            row = next(
                (
                    item
                    for item in self._coordination._outbox.values()
                    if item["outbox_id"] == outbox_id
                    and item["event_id"] == event_id
                    and item["event_type"] == "WORK_RESULT_SUBMITTED"
                ),
                None,
            )
            if row is None:
                raise WorkResultError(
                    "wc.work_result_event_not_found",
                    "WorkResult outbox event was not found.",
                    404,
                )
            return copy.deepcopy(row)

    def mark_result_event_delivered(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]:
        return self._update_outbox(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=job_id,
            target_state="DELIVERED",
            updated_at=updated_at,
        )

    def _update_outbox(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        target_state: str,
        updated_at: str,
    ) -> Mapping[str, Any]:
        with self._lock:
            row = next(
                (
                    item
                    for item in self._coordination._outbox.values()
                    if item["outbox_id"] == outbox_id
                    and item["event_id"] == event_id
                    and item["event_type"] == "WORK_RESULT_SUBMITTED"
                ),
                None,
            )
            if row is None:
                raise WorkResultError(
                    "wc.work_result_event_not_found",
                    "WorkResult outbox event was not found.",
                    404,
                )
            if row["enqueued_job_id"] not in {None, job_id}:
                raise WorkResultError(
                    "wc.work_result_event_job_conflict",
                    "WorkResult event is bound to another delivery job.",
                )
            if row["delivery_state"] == "DELIVERED" and target_state != "DELIVERED":
                return copy.deepcopy(row)
            row["enqueued_job_id"] = job_id
            row["delivery_state"] = target_state
            row["updated_at"] = updated_at
            return copy.deepcopy(row)


class SqlAlchemyWorkResultRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_submission_context(
        self, *, tenant_id: str, work_item_id: str
    ) -> Mapping[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_submission_context(
                    session, tenant_id=tenant_id, work_item_id=work_item_id
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_result_source(
        self, *, tenant_id: str, result_id: str
    ) -> Mapping[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            f"SELECT {_RESULT_SOURCE_COLUMNS} FROM wc_work_result "
                            "WHERE tenant_id = :tenant_id AND result_id = :result_id"
                        ),
                        {"tenant_id": tenant_id, "result_id": result_id},
                    )
                    .mappings()
                    .first()
                )
                return None if row is None else _result_source_from_row(row)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_result_sources_by_execution(
        self, *, tenant_id: str, source_execution_ref: str, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            f"SELECT {_RESULT_SOURCE_COLUMNS} FROM wc_work_result "
                            "WHERE tenant_id = :tenant_id "
                            "AND source_execution_ref = :source_execution_ref "
                            "ORDER BY submitted_at, result_id LIMIT :limit"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "source_execution_ref": source_execution_ref,
                            "limit": limit,
                        },
                    )
                    .mappings()
                    .all()
                )
                return [_result_source_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_pending_result_events(self, *, limit: int) -> Sequence[Mapping[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(text(_OUTBOX_PENDING_SQL), {"limit": limit})
                    .mappings()
                    .all()
                )
                return [_outbox_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def mark_result_event_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]:
        return self._update_outbox(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=job_id,
            target_state="ENQUEUED",
            updated_at=updated_at,
        )

    def load_result_event(self, *, outbox_id: str, event_id: str) -> Mapping[str, Any]:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_OUTBOX_SELECT_SQL),
                        {"outbox_id": outbox_id, "event_id": event_id},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise WorkResultError(
                        "wc.work_result_event_not_found",
                        "WorkResult outbox event was not found.",
                        404,
                    )
                return _outbox_from_row(row)
        except WorkResultError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def mark_result_event_delivered(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> Mapping[str, Any]:
        return self._update_outbox(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=job_id,
            target_state="DELIVERED",
            updated_at=updated_at,
        )

    def _update_outbox(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        target_state: str,
        updated_at: str,
    ) -> Mapping[str, Any]:
        params = {
            "outbox_id": outbox_id,
            "event_id": event_id,
            "job_id": job_id,
            "target_state": target_state,
            "updated_at": updated_at,
        }
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(text(_OUTBOX_UPDATE_SQL), params).mappings().first()
                )
                if row is None:
                    raise WorkResultError(
                        "wc.work_result_event_update_conflict",
                        "WorkResult outbox event changed or is bound to another job.",
                        409,
                        True,
                    )
                session.commit()
                return _outbox_from_row(row)
        except WorkResultError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def commit_result(
        self,
        *,
        work_result: Mapping[str, Any],
        result_hash: str,
        expected_version: int,
        authorization: Mapping[str, Any],
        outbox_id: str,
        event_id: str,
        now: str,
    ) -> Mapping[str, Any]:
        result = dict(work_result)
        params = {
            "tenant_id": result["tenant_id"],
            "result_id": result["result_id"],
            "work_item_id": result["work_item_id"],
            "revision_no": result["revision_no"],
            "result_type": result["result_type"],
            "result_schema_ref": result["schema_ref"],
            "result_hash": result_hash,
            "result_payload": json.dumps(result, sort_keys=True),
            "source_execution_ref": result["source_execution_ref"],
            "claim_id": result["claim_ref"],
            "claim_generation": result["claim_generation"],
            "assignment_id": result["assignment_ref"],
            "submitted_agent_id": result["submitted_by"]["entity_id"],
            "authorization_revision_hash": authorization["revision_hash"],
            "authorization_checked_at": authorization["checked_at"],
            "submitted_at": result["submitted_at"],
            "expected_version": expected_version,
            "next_version": expected_version + 1,
            "outbox_id": outbox_id,
            "event_id": event_id,
            "event_payload": json.dumps(
                _result_event(result, event_id=event_id, now=now), sort_keys=True
            ),
            "now": now,
        }
        try:
            with self._session_factory() as session:
                existing = _load_result_by_identity(
                    session,
                    tenant_id=params["tenant_id"],
                    result_id=params["result_id"],
                    work_item_id=params["work_item_id"],
                    revision_no=params["revision_no"],
                )
                if existing is not None:
                    _require_same_result(existing, result_hash, params["work_item_id"])
                    return _acceptance(existing, created=False)
                context = _load_submission_context(
                    session,
                    tenant_id=params["tenant_id"],
                    work_item_id=params["work_item_id"],
                    lock=True,
                )
                existing = _load_result_by_identity(
                    session,
                    tenant_id=params["tenant_id"],
                    result_id=params["result_id"],
                    work_item_id=params["work_item_id"],
                    revision_no=params["revision_no"],
                )
                if existing is not None:
                    _require_same_result(existing, result_hash, params["work_item_id"])
                    session.commit()
                    return _acceptance(existing, created=False)
                _require_commit_authority(context, result, expected_version)
                session.execute(text(_RESULT_INSERT_SQL), params)
                updated = session.execute(text(_WORK_UPDATE_SQL), params)
                if int(updated.rowcount or 0) != 1:
                    raise WorkResultError(
                        "wc.work_result_version_conflict",
                        "WorkItem changed before WorkResult commit.",
                        409,
                        True,
                    )
                session.execute(text(_OUTBOX_INSERT_SQL), params)
                session.commit()
                return {
                    "schema_version": "wc_work_result_acceptance.v1",
                    "created": True,
                    "tenant_id": params["tenant_id"],
                    "work_item_id": params["work_item_id"],
                    "work_item_version": params["next_version"],
                    "result_id": params["result_id"],
                    "result_hash": result_hash,
                    "outbox_id": outbox_id,
                    "event_id": event_id,
                    "accepted_at": now,
                }
        except WorkResultError:
            raise
        except IntegrityError as exc:
            raise WorkResultError(
                "wc.work_result_identity_conflict",
                "WorkResult identity or revision already exists.",
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class WorkResultService:
    def __init__(
        self,
        repository: WorkResultRepository,
        *,
        authorization_source: AuthorizationSource,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def submit(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: object,
        work_result: object,
    ) -> Mapping[str, Any]:
        tenant = _required("tenant_id", tenant_id, 128)
        work_id = _uuid("work_item_id", work_item_id)
        version = _positive_int("expected_version", expected_version)
        result = validate_work_result(work_result)
        if result["tenant_id"] != tenant or result["work_item_id"] != work_id:
            raise _invalid("WorkResult tenant/work item path lineage differs.")
        context = self._repository.get_submission_context(
            tenant_id=tenant, work_item_id=work_id
        )
        if context is None:
            raise _not_found()
        requester = _required(
            "requester_ref", context["work_item"]["requester"]["entity_id"], 160
        )
        try:
            authorization = self._authorization_source.effective_authorization(
                tenant_id=tenant, subject_id=requester
            )
            revision_hash = require_active_scope(
                authorization,
                required_scope="work:result:submit",
            )
        except AuthorizationSubjectDenied as exc:
            raise WorkResultError(
                "wc.work_result_authorization_denied",
                "Requester lacks active work:result:submit authority.",
                403,
            ) from exc
        except Exception as exc:
            raise WorkResultError(
                "wc.work_result_authorization_unavailable",
                "OA effective authorization is unavailable.",
                503,
                True,
            ) from exc
        now = _time(self._clock())
        return self._repository.commit_result(
            work_result=result,
            result_hash=semantic_sha256_hash_ref(result),
            expected_version=version,
            authorization={"revision_hash": revision_hash, "checked_at": now},
            outbox_id=_uuid("outbox_id", self._id_factory()),
            event_id=_uuid("event_id", self._id_factory()),
            now=now,
        )


def validate_work_result(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("work_result must be an object.")
    result = copy.deepcopy(dict(value))
    unknown = set(result) - WORK_RESULT_FIELDS
    missing = REQUIRED_WORK_RESULT_FIELDS - set(result)
    if unknown:
        raise _invalid(f"unsupported WorkResult field: {min(unknown)}")
    if missing:
        raise _invalid(f"missing WorkResult field: {min(missing)}")
    if result["schema_version"] != "2.1":
        raise _invalid("WorkResult schema_version must be 2.1.")
    for field, maximum in (
        ("tenant_id", 128),
        ("result_id", 128),
        ("result_type", 120),
        ("source_execution_ref", 128),
        ("claim_ref", 128),
        ("assignment_ref", 128),
    ):
        result[field] = _required(field, result.get(field), maximum)
    result["work_item_id"] = _uuid("work_item_id", result.get("work_item_id"))
    result["claim_ref"] = _uuid("claim_ref", result["claim_ref"])
    result["assignment_ref"] = _uuid("assignment_ref", result["assignment_ref"])
    result["revision_no"] = _positive_int("revision_no", result["revision_no"])
    result["claim_generation"] = _positive_int(
        "claim_generation", result.get("claim_generation")
    )
    result["schema_ref"] = _required("schema_ref", result.get("schema_ref"), 512)
    if result["technical_outcome"] not in TECHNICAL_OUTCOMES:
        raise _invalid("technical_outcome is invalid.")
    if result["business_outcome"] not in BUSINESS_OUTCOMES:
        raise _invalid("business_outcome is invalid.")
    result["submitted_by"] = _entity_ref(result["submitted_by"], "submitted_by")
    if result["submitted_by"]["entity_type"] != "AGENT":
        raise _invalid("Initial P7 WorkResult submitted_by must be AGENT.")
    result["submitted_by"]["entity_id"] = _uuid(
        "submitted_by.entity_id", result["submitted_by"]["entity_id"]
    )
    result["trace"] = _trace(result["trace"])
    result["submitted_at"] = _timestamp("submitted_at", result["submitted_at"])
    summary = result.get("summary")
    if summary is not None and (not isinstance(summary, str) or len(summary) > 4000):
        raise _invalid("summary must be null or at most 4000 characters.")
    for field in ("artifact_refs", "evidence_refs", "business_object_refs"):
        result[field] = _entity_refs(result.get(field, ()), field)
    try:
        json.dumps(result.get("payload"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise _invalid("payload must be JSON serializable.") from exc
    return result


def _require_commit_authority(
    context: Mapping[str, Any] | None,
    result: Mapping[str, Any],
    expected_version: int,
) -> None:
    if context is None:
        raise _not_found()
    item = context["work_item"]
    claim = context.get("claim")
    assignment = context.get("assignment")
    if item["version"] != expected_version or item["state"] != "ASSIGNED":
        raise WorkResultError(
            "wc.work_result_version_conflict",
            "WorkItem is not at the expected ASSIGNED version.",
        )
    if not isinstance(claim, Mapping) or claim.get("state") != "ACTIVE":
        raise WorkResultError(
            "wc.work_result_claim_stale", "Current active Claim is required."
        )
    if not isinstance(assignment, Mapping) or assignment.get("status") != "ACTIVE":
        raise WorkResultError(
            "wc.work_result_assignment_stale", "Current active Assignment is required."
        )
    expected = (
        str(claim["claim_id"]),
        int(claim["claim_generation"]),
        str(assignment["assignment_id"]),
        str(assignment["agent_id"]),
    )
    actual = (
        result["claim_ref"],
        result["claim_generation"],
        result["assignment_ref"],
        result["submitted_by"]["entity_id"],
    )
    if actual != expected:
        raise WorkResultError(
            "wc.work_result_authority_mismatch",
            "WorkResult does not match current Claim and Assignment authority.",
        )
    expected_contract = context["delegation_spec"]["result_contract_ref"]
    if result["schema_ref"] != expected_contract:
        raise WorkResultError(
            "wc.work_result_contract_mismatch",
            "WorkResult schema_ref differs from the delegated result contract.",
        )


def _submission_context(
    record: Mapping[str, Any],
    claim: Mapping[str, Any] | None,
    assignment: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "work_item": copy.deepcopy(record["work_item"]),
        "delegation_spec": copy.deepcopy(record["delegation_spec"]),
        "claim": None if claim is None else copy.deepcopy(dict(claim)),
        "assignment": None if assignment is None else copy.deepcopy(dict(assignment)),
    }


def _load_submission_context(
    session: Session,
    *,
    tenant_id: str,
    work_item_id: str,
    lock: bool = False,
) -> dict[str, Any] | None:
    suffix = (
        " FOR UPDATE OF work"
        if lock and session.get_bind().dialect.name == "postgresql"
        else ""
    )
    row = (
        session.execute(
            text(
                "SELECT work.work_item, work.delegation_spec, "
                "work.state AS work_state, work.version AS work_version, "
                "claim.claim_id, claim.claim_generation, claim.state AS claim_state, "
                "assignment.assignment_id, assignment.agent_id, "
                "assignment.status AS assignment_status "
                "FROM wc_work_item AS work "
                "LEFT JOIN wc_claim AS claim ON claim.tenant_id = work.tenant_id "
                "AND claim.work_item_id = work.work_item_id AND claim.state = 'ACTIVE' "
                "LEFT JOIN wc_assignment AS assignment "
                "ON assignment.tenant_id = work.tenant_id "
                "AND assignment.work_item_id = work.work_item_id "
                "AND assignment.status = 'ACTIVE' "
                "WHERE work.tenant_id = :tenant_id "
                "AND work.work_item_id = :work_item_id" + suffix
            ),
            {"tenant_id": tenant_id, "work_item_id": work_item_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    item = dict(row["work_item"])
    item["state"] = row["work_state"]
    item["version"] = int(row["work_version"])
    return {
        "work_item": item,
        "delegation_spec": dict(row["delegation_spec"]),
        "claim": (
            None
            if row["claim_id"] is None
            else {
                "claim_id": str(row["claim_id"]),
                "claim_generation": int(row["claim_generation"]),
                "state": row["claim_state"],
            }
        ),
        "assignment": (
            None
            if row["assignment_id"] is None
            else {
                "assignment_id": str(row["assignment_id"]),
                "agent_id": str(row["agent_id"]),
                "status": row["assignment_status"],
            }
        ),
    }


def _load_result_by_identity(
    session: Session,
    *,
    tenant_id: str,
    result_id: str,
    work_item_id: str,
    revision_no: int,
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT result.result_id, result.work_item_id, result.result_hash, "
                "result.submitted_at, outbox.outbox_id, outbox.event_id, "
                "work.version AS work_item_version "
                "FROM wc_work_result AS result "
                "JOIN wc_work_item AS work ON work.tenant_id = result.tenant_id "
                "AND work.work_item_id = result.work_item_id "
                "JOIN wc_event_outbox AS outbox ON outbox.tenant_id = result.tenant_id "
                "AND outbox.work_item_id = result.work_item_id "
                "AND outbox.event_type = 'WORK_RESULT_SUBMITTED' "
                "AND outbox.event_payload ->> 'result_id' = result.result_id "
                "WHERE result.tenant_id = :tenant_id AND "
                "(result.result_id = :result_id OR "
                "(result.work_item_id = :work_item_id AND result.revision_no = :revision_no)) "
                "ORDER BY result.submitted_at DESC LIMIT 1"
            ),
            {
                "tenant_id": tenant_id,
                "result_id": result_id,
                "work_item_id": work_item_id,
                "revision_no": revision_no,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "tenant_id": tenant_id,
        "result_id": str(row["result_id"]),
        "work_item_id": str(row["work_item_id"]),
        "result_hash": row["result_hash"],
        "work_item_version": int(row["work_item_version"]),
        "outbox_id": str(row["outbox_id"]),
        "event_id": str(row["event_id"]),
        "accepted_at": _time(row["submitted_at"]),
    }


def _result_event(
    result: Mapping[str, Any], *, event_id: str, now: str
) -> dict[str, Any]:
    event = {
        "schema_version": "2.1",
        "event_id": event_id,
        "event_name": "WORK_RESULT_SUBMITTED",
        "tenant_id": result["tenant_id"],
        "work_item_id": result["work_item_id"],
        "result_id": result["result_id"],
        "revision_no": result["revision_no"],
        "result_type": result["result_type"],
        "result_schema_ref": result["schema_ref"],
        "technical_outcome": result["technical_outcome"],
        "business_outcome": result["business_outcome"],
        "source_execution_ref": result["source_execution_ref"],
        "claim_ref": result["claim_ref"],
        "claim_generation": result["claim_generation"],
        "assignment_ref": result["assignment_ref"],
        "submitted_by": copy.deepcopy(result["submitted_by"]),
        "resume_match_ref": result["work_item_id"],
        "correlation_id": result["trace"]["correlation_id"],
        "causation_id": result["result_id"],
        "occurred_at": now,
    }
    return event


def _acceptance(record: Mapping[str, Any], *, created: bool) -> dict[str, Any]:
    return {
        "schema_version": "wc_work_result_acceptance.v1",
        "created": created,
        "tenant_id": record.get("tenant_id")
        or record.get("work_result", {}).get("tenant_id"),
        "work_item_id": record["work_item_id"]
        if "work_item_id" in record
        else record["work_result"]["work_item_id"],
        "work_item_version": int(record["work_item_version"]),
        "result_id": record["result_id"]
        if "result_id" in record
        else record["work_result"]["result_id"],
        "result_hash": record["result_hash"],
        "outbox_id": record["outbox_id"],
        "event_id": record["event_id"],
        "accepted_at": record["accepted_at"],
    }


def _outbox_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_payload = row["event_payload"]
    payload = (
        json.loads(raw_payload)
        if isinstance(raw_payload, str)
        else copy.deepcopy(dict(raw_payload))
    )
    return {
        "tenant_id": row["tenant_id"],
        "outbox_id": str(row["outbox_id"]),
        "event_id": str(row["event_id"]),
        "work_item_id": str(row["work_item_id"]),
        "event_type": row["event_type"],
        "event_payload": payload,
        "delivery_state": row["delivery_state"],
        "enqueued_job_id": (
            None if row["enqueued_job_id"] is None else str(row["enqueued_job_id"])
        ),
        "created_at": _time(row["created_at"]),
        "updated_at": _time(row["updated_at"]),
    }


def _result_source_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_payload = row["result_payload"]
    payload = (
        json.loads(raw_payload)
        if isinstance(raw_payload, str)
        else copy.deepcopy(dict(raw_payload))
    )
    return {
        "tenant_id": row["tenant_id"],
        "result_id": str(row["result_id"]),
        "work_item_id": str(row["work_item_id"]),
        "revision_no": int(row["revision_no"]),
        "result_hash": row["result_hash"],
        "source_execution_ref": row["source_execution_ref"],
        "claim_id": str(row["claim_id"]),
        "claim_generation": int(row["claim_generation"]),
        "assignment_id": str(row["assignment_id"]),
        "submitted_agent_id": str(row["submitted_agent_id"]),
        "submitted_at": _time(row["submitted_at"]),
        "work_result": payload,
    }


def _require_same_result(
    existing: Mapping[str, Any], result_hash: str, work_item_id: str
) -> None:
    existing_work_item_id = (
        existing["work_item_id"]
        if "work_item_id" in existing
        else existing["work_result"]["work_item_id"]
    )
    if (
        existing["result_hash"] != result_hash
        or str(existing_work_item_id) != work_item_id
    ):
        raise WorkResultError(
            "wc.work_result_idempotency_conflict",
            "WorkResult identity was reused with different semantics.",
        )


def _transition_work_item(
    record: dict[str, Any], *, state: str, updated_at: str
) -> None:
    record["state"] = state
    record["version"] += 1
    record["updated_at"] = updated_at
    record["work_item"]["state"] = state
    record["work_item"]["version"] = record["version"]
    record["work_item"]["updated_at"] = updated_at


def _entity_ref(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an entity reference.")
    result = copy.deepcopy(dict(value))
    if set(result) - {"entity_type", "entity_id", "version", "status"}:
        raise _invalid(f"{field} contains unsupported fields.")
    result["entity_type"] = _required(
        f"{field}.entity_type", result.get("entity_type"), 80
    )
    result["entity_id"] = _required(f"{field}.entity_id", result.get("entity_id"), 160)
    return result


def _entity_refs(value: object, field: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid(f"{field} must be an array.")
    return [_entity_ref(item, field) for item in value]


def _trace(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {
        "correlation_id",
        "causation_id",
        "request_id",
    }:
        raise _invalid("trace is invalid.")
    result = copy.deepcopy(dict(value))
    result["correlation_id"] = _required(
        "trace.correlation_id", result.get("correlation_id"), 128
    )
    for field in ("causation_id", "request_id"):
        if result.get(field) is not None:
            result[field] = _required(f"trace.{field}", result[field], 128)
    return result


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _timestamp(field: str, value: object) -> str:
    text_value = _required(field, value, 64)
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return _time(parsed)


def _time(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value
    return normalized.isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> WorkResultError:
    return WorkResultError("wc.work_result_invalid", detail, 400)


def _not_found() -> WorkResultError:
    return WorkResultError("wc.work_item_not_found", "WorkItem was not found.", 404)


def _unavailable() -> WorkResultError:
    return WorkResultError(
        "wc.work_result_store_unavailable",
        "WC WorkResult persistence is unavailable.",
        503,
        True,
    )


_RESULT_INSERT_SQL = """
    INSERT INTO wc_work_result (
        tenant_id, result_id, work_item_id, revision_no, result_type,
        result_schema_ref, result_hash, result_payload, source_execution_ref,
        claim_id, claim_generation, assignment_id, submitted_agent_id,
        authorization_revision_hash, authorization_checked_at, submitted_at
    ) VALUES (
        :tenant_id, :result_id, :work_item_id, :revision_no, :result_type,
        :result_schema_ref, :result_hash, CAST(:result_payload AS JSONB),
        :source_execution_ref, :claim_id, :claim_generation, :assignment_id,
        :submitted_agent_id, :authorization_revision_hash,
        :authorization_checked_at, :submitted_at
    )
"""

_RESULT_SOURCE_COLUMNS = """
    tenant_id, result_id, work_item_id, revision_no, result_hash,
    result_payload, source_execution_ref, claim_id, claim_generation,
    assignment_id, submitted_agent_id, submitted_at
"""

_WORK_UPDATE_SQL = """
    UPDATE wc_work_item
    SET state = 'RESULT_SUBMITTED', version = :next_version,
        work_item = jsonb_set(
            jsonb_set(
                jsonb_set(work_item, '{state}', '"RESULT_SUBMITTED"'::jsonb),
                '{version}', to_jsonb(CAST(:next_version AS integer))
            ),
            '{updated_at}', to_jsonb(CAST(:now AS text))
        ),
        updated_at = CAST(:now AS TIMESTAMPTZ)
    WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
      AND state = 'ASSIGNED' AND version = :expected_version
"""

_OUTBOX_INSERT_SQL = """
    INSERT INTO wc_event_outbox (
        tenant_id, outbox_id, event_id, work_item_id, event_type,
        event_payload, delivery_state, created_at, updated_at
    ) VALUES (
        :tenant_id, :outbox_id, :event_id, :work_item_id,
        'WORK_RESULT_SUBMITTED', CAST(:event_payload AS JSONB),
        'PENDING', :now, :now
    )
"""

_OUTBOX_COLUMNS = """
    tenant_id, outbox_id, event_id, work_item_id, event_type, event_payload,
    delivery_state, enqueued_job_id, created_at, updated_at
"""

_OUTBOX_PENDING_SQL = f"""
    SELECT {_OUTBOX_COLUMNS}
    FROM wc_event_outbox
    WHERE event_type = 'WORK_RESULT_SUBMITTED' AND delivery_state = 'PENDING'
    ORDER BY created_at, outbox_id
    LIMIT :limit
"""

_OUTBOX_SELECT_SQL = f"""
    SELECT {_OUTBOX_COLUMNS}
    FROM wc_event_outbox
    WHERE outbox_id = :outbox_id AND event_id = :event_id
      AND event_type = 'WORK_RESULT_SUBMITTED'
"""

_OUTBOX_UPDATE_SQL = f"""
    UPDATE wc_event_outbox
    SET delivery_state = :target_state,
        enqueued_job_id = COALESCE(enqueued_job_id, :job_id),
        updated_at = :updated_at
    WHERE outbox_id = :outbox_id AND event_id = :event_id
      AND event_type = 'WORK_RESULT_SUBMITTED'
      AND delivery_state IN ('PENDING', 'ENQUEUED', 'DELIVERED')
      AND (enqueued_job_id IS NULL OR enqueued_job_id = :job_id)
    RETURNING {_OUTBOX_COLUMNS}
"""
