from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

WORK_EVIDENCE_TABLE = "wa_work_evidence"
WORK_EVIDENCE_SOURCE_TYPES = (
    "AE_AGENT_RESULT",
    "AE_ARTIFACT",
    "WC_WORK_RESULT",
)
WORK_EVIDENCE_ACTOR_TYPES = ("HUMAN", "AGENT")
WORK_EVIDENCE_AGENT_TYPES = ("IA", "CA", "PA", "EA")
WORK_EVIDENCE_CLASSIFICATIONS = ("INTERNAL", "CONFIDENTIAL", "RESTRICTED")
WORK_EVIDENCE_STATUSES = ("ACTIVE", "SUPERSEDED", "INVALIDATED")


class WorkEvidenceError(Exception):
    def __init__(self, error_code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class WorkEvidenceInput:
    tenant_id: str
    source_owner: str
    source_type: str
    source_ref: str
    source_revision_ref: str
    source_hash: str
    evidence_kind: str
    actor_type: str
    actor_ref: str
    occurred_at: datetime
    observed_at: datetime
    classification: str
    agent_type_snapshot: str | None = None
    project_ref: str | None = None
    evidence_status: str = "ACTIVE"
    supersedes_evidence_id: str | None = None


@dataclass(frozen=True)
class WorkEvidenceRecord:
    tenant_id: str
    work_evidence_id: str
    source_owner: str
    source_type: str
    source_ref: str
    source_revision_ref: str
    source_hash: str
    evidence_kind: str
    actor_type: str
    actor_ref: str
    agent_type_snapshot: str | None
    project_ref: str | None
    occurred_at: str
    observed_at: str
    classification: str
    evidence_status: str
    evidence_hash: str
    supersedes_evidence_id: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def deterministic_work_evidence_id(
    *,
    tenant_id: str,
    source_type: str,
    source_ref: str,
    source_revision_ref: str,
) -> str:
    identity = {
        "tenant_id": _required_string(tenant_id, "tenant_id"),
        "source_type": _choice(source_type, "source_type", WORK_EVIDENCE_SOURCE_TYPES),
        "source_ref": _required_string(source_ref, "source_ref"),
        "source_revision_ref": _required_string(
            source_revision_ref, "source_revision_ref"
        ),
    }
    return str(
        uuid5(
            NAMESPACE_URL,
            "nex-wa-work-evidence-v1:" + canonical_json(identity),
        )
    )


def build_work_evidence(
    candidate: WorkEvidenceInput,
    *,
    created_at: datetime | None = None,
) -> WorkEvidenceRecord:
    tenant_id = _required_string(candidate.tenant_id, "tenant_id")
    source_owner = _required_string(candidate.source_owner, "source_owner")
    source_type = _choice(
        candidate.source_type, "source_type", WORK_EVIDENCE_SOURCE_TYPES
    )
    source_ref = _required_string(candidate.source_ref, "source_ref")
    source_revision_ref = _required_string(
        candidate.source_revision_ref, "source_revision_ref"
    )
    try:
        source_hash = validate_hash_ref(candidate.source_hash)
    except ValueError as exc:
        raise _invalid("source_hash must be a lowercase SHA-256 hash reference") from exc
    evidence_kind = _required_string(candidate.evidence_kind, "evidence_kind")
    actor_type = _choice(
        candidate.actor_type, "actor_type", WORK_EVIDENCE_ACTOR_TYPES
    )
    actor_ref = _required_string(candidate.actor_ref, "actor_ref")
    agent_type = _optional_choice(
        candidate.agent_type_snapshot,
        "agent_type_snapshot",
        WORK_EVIDENCE_AGENT_TYPES,
    )
    project_ref = _optional_uuid(candidate.project_ref, "project_ref")
    occurred_at = _utc_timestamp(candidate.occurred_at, "occurred_at")
    observed_at = _utc_timestamp(candidate.observed_at, "observed_at")
    classification = _choice(
        candidate.classification,
        "classification",
        WORK_EVIDENCE_CLASSIFICATIONS,
    )
    evidence_status = _choice(
        candidate.evidence_status,
        "evidence_status",
        WORK_EVIDENCE_STATUSES,
    )
    supersedes = _optional_uuid(
        candidate.supersedes_evidence_id,
        "supersedes_evidence_id",
    )
    work_evidence_id = deterministic_work_evidence_id(
        tenant_id=tenant_id,
        source_type=source_type,
        source_ref=source_ref,
        source_revision_ref=source_revision_ref,
    )
    if supersedes == work_evidence_id:
        raise WorkEvidenceError(
            "WA_SUPERSESSION_INVALID",
            "WorkEvidence cannot supersede itself",
            409,
        )
    hash_projection = {
        "tenant_id": tenant_id,
        "source_owner": source_owner,
        "source_type": source_type,
        "source_ref": source_ref,
        "source_revision_ref": source_revision_ref,
        "source_hash": source_hash,
        "evidence_kind": evidence_kind,
        "actor_type": actor_type,
        "actor_ref": actor_ref,
        "agent_type_snapshot": agent_type,
        "project_ref": project_ref,
        "occurred_at": occurred_at,
        "classification": classification,
        "supersedes_evidence_id": supersedes,
    }
    created = _utc_timestamp(created_at or datetime.now(UTC), "created_at")
    return WorkEvidenceRecord(
        tenant_id=tenant_id,
        work_evidence_id=work_evidence_id,
        source_owner=source_owner,
        source_type=source_type,
        source_ref=source_ref,
        source_revision_ref=source_revision_ref,
        source_hash=source_hash,
        evidence_kind=evidence_kind,
        actor_type=actor_type,
        actor_ref=actor_ref,
        agent_type_snapshot=agent_type,
        project_ref=project_ref,
        occurred_at=occurred_at,
        observed_at=observed_at,
        classification=classification,
        evidence_status=evidence_status,
        evidence_hash=semantic_sha256_hash_ref(hash_projection),
        supersedes_evidence_id=supersedes,
        created_at=created,
    )


class SqlAlchemyWorkEvidenceRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_or_get(self, candidate: WorkEvidenceInput) -> WorkEvidenceRecord:
        record = build_work_evidence(candidate, created_at=self._clock())
        session = self._session_factory()
        try:
            existing = self._select_by_source(session, record)
            if existing is not None:
                reused = _reuse_or_conflict(existing, record)
                self._apply_supersession(session, reused)
                session.commit()
                return reused
            self._apply_supersession(session, record)
            try:
                session.execute(_INSERT_EVIDENCE, _database_params(session, record))
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._select_by_source(session, record)
                if existing is not None:
                    return _reuse_or_conflict(existing, record)
                raise WorkEvidenceError(
                    "WA_SUPERSESSION_INVALID",
                    "WorkEvidence supersession or tenant integrity failed",
                    409,
                )
            stored = self._select_by_id(
                session, record.tenant_id, record.work_evidence_id
            )
            if stored is None:
                raise WorkEvidenceError(
                    "WA_EVIDENCE_STORE_UNAVAILABLE",
                    "WorkEvidence was not readable after commit",
                    503,
                )
            return stored
        except WorkEvidenceError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence persistence is unavailable",
                503,
            ) from exc
        finally:
            session.close()

    def create_or_get_in_session(
        self,
        session: Session,
        candidate: WorkEvidenceInput,
        *,
        created_at: datetime | None = None,
    ) -> WorkEvidenceRecord:
        """Persist through a caller-owned transaction without settling it."""
        record = build_work_evidence(
            candidate,
            created_at=created_at or self._clock(),
        )
        existing = self._select_by_source(session, record)
        if existing is not None:
            reused = _reuse_or_conflict(existing, record)
            self._apply_supersession(session, reused)
            return reused
        self._apply_supersession(session, record)
        session.execute(_INSERT_EVIDENCE, _database_params(session, record))
        stored = self._select_by_id(
            session,
            record.tenant_id,
            record.work_evidence_id,
        )
        if stored is None:
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence was not readable before local commit",
                503,
            )
        return stored

    def get(self, tenant_id: str, work_evidence_id: str) -> WorkEvidenceRecord | None:
        normalized_tenant = _required_string(tenant_id, "tenant_id")
        normalized_id = _required_uuid(work_evidence_id, "work_evidence_id")
        try:
            with self._session_factory() as session:
                return self._select_by_id(session, normalized_tenant, normalized_id)
        except SQLAlchemyError as exc:
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence persistence is unavailable",
                503,
            ) from exc

    def get_by_source_identity(
        self,
        *,
        tenant_id: str,
        source_type: str,
        source_ref: str,
        source_revision_ref: str,
    ) -> WorkEvidenceRecord | None:
        normalized = {
            "tenant_id": _required_string(tenant_id, "tenant_id"),
            "source_type": _choice(
                source_type,
                "source_type",
                WORK_EVIDENCE_SOURCE_TYPES,
            ),
            "source_ref": _required_string(source_ref, "source_ref"),
            "source_revision_ref": _required_string(
                source_revision_ref,
                "source_revision_ref",
            ),
        }
        try:
            with self._session_factory() as session:
                row = session.execute(_SELECT_BY_SOURCE, normalized).mappings().first()
                return _record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence persistence is unavailable",
                503,
            ) from exc

    def list_source_lineage(
        self,
        tenant_id: str,
        work_evidence_id: str,
    ) -> tuple[WorkEvidenceRecord, ...]:
        normalized_tenant = _required_string(tenant_id, "tenant_id")
        normalized_id = _required_uuid(work_evidence_id, "work_evidence_id")
        try:
            with self._session_factory() as session:
                anchor = self._select_by_id(session, normalized_tenant, normalized_id)
                if anchor is None:
                    return ()
                rows = session.execute(
                    _SELECT_SOURCE_LINEAGE,
                    {
                        "tenant_id": normalized_tenant,
                        "source_type": anchor.source_type,
                        "source_ref": anchor.source_ref,
                    },
                ).mappings()
                return _order_source_lineage(
                    tuple(_record_from_row(row) for row in rows)
                )
        except SQLAlchemyError as exc:
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence persistence is unavailable",
                503,
            ) from exc

    def invalidate(
        self,
        tenant_id: str,
        work_evidence_id: str,
    ) -> WorkEvidenceRecord:
        normalized_tenant = _required_string(tenant_id, "tenant_id")
        normalized_id = _required_uuid(work_evidence_id, "work_evidence_id")
        session = self._session_factory()
        try:
            existing = self._select_by_id(session, normalized_tenant, normalized_id)
            if existing is None:
                raise WorkEvidenceError(
                    "WA_EVIDENCE_NOT_FOUND",
                    "WorkEvidence was not found",
                    404,
                )
            if existing.evidence_status != "INVALIDATED":
                session.execute(
                    _UPDATE_EVIDENCE_STATUS,
                    {
                        "tenant_id": normalized_tenant,
                        "work_evidence_id": _database_uuid(session, normalized_id),
                        "evidence_status": "INVALIDATED",
                    },
                )
                session.commit()
            stored = self._select_by_id(session, normalized_tenant, normalized_id)
            if stored is None:
                raise WorkEvidenceError(
                    "WA_EVIDENCE_STORE_UNAVAILABLE",
                    "WorkEvidence was not readable after invalidation",
                    503,
                )
            return stored
        except WorkEvidenceError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "WorkEvidence persistence is unavailable",
                503,
            ) from exc
        finally:
            session.close()

    def _apply_supersession(
        self,
        session: Session,
        record: WorkEvidenceRecord,
    ) -> None:
        if record.supersedes_evidence_id is None:
            return
        target = self._select_by_id(
            session,
            record.tenant_id,
            record.supersedes_evidence_id,
        )
        if target is None:
            raise WorkEvidenceError(
                "WA_SUPERSESSION_INVALID",
                "superseded WorkEvidence must exist in the same tenant",
                409,
            )
        if (
            target.source_type != record.source_type
            or target.source_ref != record.source_ref
        ):
            raise WorkEvidenceError(
                "WA_SUPERSESSION_INVALID",
                "superseded WorkEvidence must belong to the same source lineage",
                409,
            )
        if target.evidence_status == "ACTIVE":
            session.execute(
                _UPDATE_EVIDENCE_STATUS,
                {
                    "tenant_id": record.tenant_id,
                    "work_evidence_id": _database_uuid(
                        session, target.work_evidence_id
                    ),
                    "evidence_status": "SUPERSEDED",
                },
            )

    def _select_by_source(
        self,
        session: Session,
        record: WorkEvidenceRecord,
    ) -> WorkEvidenceRecord | None:
        row = session.execute(
            _SELECT_BY_SOURCE,
            {
                "tenant_id": record.tenant_id,
                "source_type": record.source_type,
                "source_ref": record.source_ref,
                "source_revision_ref": record.source_revision_ref,
            },
        ).mappings().first()
        return _record_from_row(row) if row is not None else None

    def _select_by_id(
        self,
        session: Session,
        tenant_id: str,
        work_evidence_id: str,
    ) -> WorkEvidenceRecord | None:
        row = session.execute(
            _SELECT_BY_ID,
            {
                "tenant_id": tenant_id,
                "work_evidence_id": _database_uuid(session, work_evidence_id),
            },
        ).mappings().first()
        return _record_from_row(row) if row is not None else None


_SELECT_COLUMNS = """
    tenant_id,
    work_evidence_id,
    source_owner,
    source_type,
    source_ref,
    source_revision_ref,
    source_hash,
    evidence_kind,
    actor_type,
    actor_ref,
    agent_type_snapshot,
    project_ref,
    occurred_at,
    observed_at,
    classification,
    evidence_status,
    evidence_hash,
    supersedes_evidence_id,
    created_at
"""
_SELECT_BY_SOURCE = text(
    f"""
    SELECT {_SELECT_COLUMNS}
    FROM {WORK_EVIDENCE_TABLE}
    WHERE tenant_id = :tenant_id
      AND source_type = :source_type
      AND source_ref = :source_ref
      AND source_revision_ref = :source_revision_ref
    """
)
_SELECT_BY_ID = text(
    f"""
    SELECT {_SELECT_COLUMNS}
    FROM {WORK_EVIDENCE_TABLE}
    WHERE tenant_id = :tenant_id AND work_evidence_id = :work_evidence_id
    """
)
_SELECT_SOURCE_LINEAGE = text(
    f"""
    SELECT {_SELECT_COLUMNS}
    FROM {WORK_EVIDENCE_TABLE}
    WHERE tenant_id = :tenant_id
      AND source_type = :source_type
      AND source_ref = :source_ref
    ORDER BY created_at, work_evidence_id
    """
)
_UPDATE_EVIDENCE_STATUS = text(
    f"""
    UPDATE {WORK_EVIDENCE_TABLE}
    SET evidence_status = :evidence_status
    WHERE tenant_id = :tenant_id AND work_evidence_id = :work_evidence_id
    """
)
_INSERT_EVIDENCE = text(
    f"""
    INSERT INTO {WORK_EVIDENCE_TABLE} (
        {_SELECT_COLUMNS}
    ) VALUES (
        :tenant_id,
        :work_evidence_id,
        :source_owner,
        :source_type,
        :source_ref,
        :source_revision_ref,
        :source_hash,
        :evidence_kind,
        :actor_type,
        :actor_ref,
        :agent_type_snapshot,
        :project_ref,
        :occurred_at,
        :observed_at,
        :classification,
        :evidence_status,
        :evidence_hash,
        :supersedes_evidence_id,
        :created_at
    )
    """
)


def _reuse_or_conflict(
    existing: WorkEvidenceRecord,
    candidate: WorkEvidenceRecord,
) -> WorkEvidenceRecord:
    if existing.source_hash == candidate.source_hash:
        return existing
    raise WorkEvidenceError(
        "WA_SOURCE_IDEMPOTENCY_CONFLICT",
        "source identity already exists with a different source hash",
        409,
    )


def _order_source_lineage(
    records: tuple[WorkEvidenceRecord, ...],
) -> tuple[WorkEvidenceRecord, ...]:
    by_parent: dict[str | None, list[WorkEvidenceRecord]] = {}
    known_ids = {record.work_evidence_id for record in records}
    for record in records:
        parent = record.supersedes_evidence_id
        if parent not in known_ids:
            parent = None
        by_parent.setdefault(parent, []).append(record)
    for children in by_parent.values():
        children.sort(key=lambda item: (item.created_at, item.work_evidence_id))

    ordered: list[WorkEvidenceRecord] = []

    def append_children(parent: str | None) -> None:
        for child in by_parent.get(parent, ()):
            ordered.append(child)
            append_children(child.work_evidence_id)

    append_children(None)
    return tuple(ordered)


def _database_params(session: Session, record: WorkEvidenceRecord) -> dict[str, Any]:
    values = record.to_dict()
    for name in ("work_evidence_id", "project_ref", "supersedes_evidence_id"):
        if values[name] is not None:
            values[name] = _database_uuid(session, str(values[name]))
    for name in ("occurred_at", "observed_at", "created_at"):
        values[name] = datetime.fromisoformat(str(values[name]).replace("Z", "+00:00"))
    return values


def _database_uuid(session: Session, value: str) -> str | UUID:
    bind = session.get_bind()
    return UUID(value) if bind is not None and bind.dialect.name == "postgresql" else value


def _record_from_row(row: Any) -> WorkEvidenceRecord:
    return WorkEvidenceRecord(
        tenant_id=str(row["tenant_id"]),
        work_evidence_id=str(row["work_evidence_id"]),
        source_owner=str(row["source_owner"]),
        source_type=str(row["source_type"]),
        source_ref=str(row["source_ref"]),
        source_revision_ref=str(row["source_revision_ref"]),
        source_hash=str(row["source_hash"]),
        evidence_kind=str(row["evidence_kind"]),
        actor_type=str(row["actor_type"]),
        actor_ref=str(row["actor_ref"]),
        agent_type_snapshot=_optional_row_string(row["agent_type_snapshot"]),
        project_ref=_optional_row_string(row["project_ref"]),
        occurred_at=_row_timestamp(row["occurred_at"]),
        observed_at=_row_timestamp(row["observed_at"]),
        classification=str(row["classification"]),
        evidence_status=str(row["evidence_status"]),
        evidence_hash=str(row["evidence_hash"]),
        supersedes_evidence_id=_optional_row_string(row["supersedes_evidence_id"]),
        created_at=_row_timestamp(row["created_at"]),
    )


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _invalid(f"{field} must be a non-empty trimmed string")
    return value


def _choice(value: object, field: str, allowed: tuple[str, ...]) -> str:
    normalized = _required_string(value, field)
    if normalized not in allowed:
        raise _invalid(f"{field} is unsupported")
    return normalized


def _optional_choice(
    value: object,
    field: str,
    allowed: tuple[str, ...],
) -> str | None:
    if value is None:
        return None
    return _choice(value, field, allowed)


def _required_uuid(value: object, field: str) -> str:
    normalized = _required_string(value, field)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _optional_uuid(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_uuid(value, field)


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _row_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return _utc_timestamp(value, "stored timestamp")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _utc_timestamp(parsed, "stored timestamp")
        except (ValueError, WorkEvidenceError) as exc:
            raise WorkEvidenceError(
                "WA_EVIDENCE_STORE_UNAVAILABLE",
                "stored WorkEvidence timestamp is invalid",
                503,
            ) from exc
    raise WorkEvidenceError(
        "WA_EVIDENCE_STORE_UNAVAILABLE",
        "stored WorkEvidence timestamp is invalid",
        503,
    )


def _optional_row_string(value: object) -> str | None:
    return None if value is None else str(value)


def _invalid(detail: str) -> WorkEvidenceError:
    return WorkEvidenceError("WA_EVIDENCE_INVALID", detail, 422)
