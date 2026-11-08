from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

WORK_ASSET_TABLE = "wa_work_asset"
WORK_ASSET_EVIDENCE_TABLE = "wa_work_asset_evidence"
WORK_ASSET_TYPES = ("AGENT_EXECUTION_RESULT", "HUMAN_OWNED_ARTIFACT")
WORK_ASSET_STATUSES = ("ACTIVE", "SUPERSEDED", "INVALIDATED")
WORK_ASSET_BINDING_ROLES = ("PRIMARY", "SUPPORTING")
ACTOR_TYPES = ("HUMAN", "AGENT")
AGENT_TYPES = ("IA", "CA", "PA", "EA")
CLASSIFICATIONS = ("INTERNAL", "CONFIDENTIAL", "RESTRICTED")


class WorkAssetError(Exception):
    def __init__(self, error_code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class WorkAssetBindingInput:
    work_evidence_id: str
    binding_role: str


@dataclass(frozen=True)
class WorkAssetInput:
    tenant_id: str
    asset_type: str
    actor_type: str
    actor_ref: str
    occurred_at: datetime
    classification: str
    bindings: tuple[WorkAssetBindingInput, ...]
    agent_type_snapshot: str | None = None
    project_ref: str | None = None
    asset_status: str = "ACTIVE"
    agent_execution_id: str | None = None
    artifact_id: str | None = None
    artifact_version_id: str | None = None


@dataclass(frozen=True)
class WorkAssetBindingRecord:
    work_evidence_id: str
    binding_role: str
    created_at: str

    def semantic_projection(self) -> dict[str, str]:
        return {
            "work_evidence_id": self.work_evidence_id,
            "binding_role": self.binding_role,
        }


@dataclass(frozen=True)
class WorkAssetRecord:
    tenant_id: str
    work_asset_id: str
    asset_type: str
    actor_type: str
    actor_ref: str
    agent_type_snapshot: str | None
    project_ref: str | None
    occurred_at: str
    classification: str
    asset_status: str
    asset_hash: str
    version: int
    created_at: str
    updated_at: str
    bindings: tuple[WorkAssetBindingRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def deterministic_work_asset_id(candidate: WorkAssetInput) -> str:
    tenant_id = _required_string(candidate.tenant_id, "tenant_id")
    asset_type = _choice(candidate.asset_type, "asset_type", WORK_ASSET_TYPES)
    if asset_type == "AGENT_EXECUTION_RESULT":
        identity = {
            "tenant_id": tenant_id,
            "agent_execution_id": _required_string(
                candidate.agent_execution_id, "agent_execution_id"
            ),
        }
        if candidate.artifact_id is not None or candidate.artifact_version_id is not None:
            raise _invalid("Agent WorkAsset cannot carry artifact identity")
    else:
        identity = {
            "tenant_id": tenant_id,
            "artifact_id": _required_string(candidate.artifact_id, "artifact_id"),
            "artifact_version_id": _required_string(
                candidate.artifact_version_id, "artifact_version_id"
            ),
        }
        if candidate.agent_execution_id is not None:
            raise _invalid("Human Artifact WorkAsset cannot carry agent identity")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"nex-wa-work-asset-v1:{asset_type}:" + canonical_json(identity),
        )
    )


def build_work_asset(
    candidate: WorkAssetInput,
    *,
    version: int = 1,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> WorkAssetRecord:
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid("version must be a positive integer")
    tenant_id = _required_string(candidate.tenant_id, "tenant_id")
    work_asset_id = deterministic_work_asset_id(candidate)
    asset_type = _choice(candidate.asset_type, "asset_type", WORK_ASSET_TYPES)
    actor_type = _choice(candidate.actor_type, "actor_type", ACTOR_TYPES)
    actor_ref = _required_string(candidate.actor_ref, "actor_ref")
    agent_type = _optional_choice(
        candidate.agent_type_snapshot,
        "agent_type_snapshot",
        AGENT_TYPES,
    )
    project_ref = _optional_uuid(candidate.project_ref, "project_ref")
    occurred_at = _utc_timestamp(candidate.occurred_at, "occurred_at")
    classification = _choice(
        candidate.classification,
        "classification",
        CLASSIFICATIONS,
    )
    asset_status = _choice(
        candidate.asset_status,
        "asset_status",
        WORK_ASSET_STATUSES,
    )
    bindings = _normalize_bindings(candidate.bindings, asset_status=asset_status)
    now = updated_at or datetime.now(UTC)
    created = _utc_timestamp(created_at or now, "created_at")
    updated = _utc_timestamp(now, "updated_at")
    hash_projection = {
        "tenant_id": tenant_id,
        "work_asset_id": work_asset_id,
        "asset_type": asset_type,
        "actor_type": actor_type,
        "actor_ref": actor_ref,
        "agent_type_snapshot": agent_type,
        "project_ref": project_ref,
        "occurred_at": occurred_at,
        "classification": classification,
        "asset_status": asset_status,
        "bindings": [item.semantic_projection() for item in bindings],
    }
    return WorkAssetRecord(
        tenant_id=tenant_id,
        work_asset_id=work_asset_id,
        asset_type=asset_type,
        actor_type=actor_type,
        actor_ref=actor_ref,
        agent_type_snapshot=agent_type,
        project_ref=project_ref,
        occurred_at=occurred_at,
        classification=classification,
        asset_status=asset_status,
        asset_hash=semantic_sha256_hash_ref(hash_projection),
        version=version,
        created_at=created,
        updated_at=updated,
        bindings=bindings,
    )


class SqlAlchemyWorkAssetRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_or_update(self, candidate: WorkAssetInput) -> WorkAssetRecord:
        session = self._session_factory()
        try:
            stored = self.create_or_update_in_session(
                session,
                candidate,
                updated_at=self._clock(),
            )
            session.commit()
            return stored
        except WorkAssetError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise WorkAssetError(
                "WA_ASSET_INTEGRITY_CONFLICT",
                "WorkAsset binding integrity failed",
                409,
            ) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise WorkAssetError(
                "WA_ASSET_STORE_UNAVAILABLE",
                "WorkAsset persistence is unavailable",
                503,
            ) from exc
        finally:
            session.close()

    def create_or_update_in_session(
        self,
        session: Session,
        candidate: WorkAssetInput,
        *,
        updated_at: datetime | None = None,
    ) -> WorkAssetRecord:
        """Persist through a caller-owned transaction without settling it."""
        now = updated_at or self._clock()
        initial = build_work_asset(candidate, created_at=now, updated_at=now)
        self._require_evidence(session, initial)
        existing = self._select_asset(session, initial.tenant_id, initial.work_asset_id)
        if existing is not None and existing.asset_hash == initial.asset_hash:
            return existing
        stored = initial
        if existing is None:
            self._insert_asset(session, initial)
            self._replace_bindings(session, initial)
        else:
            stored = build_work_asset(
                candidate,
                version=existing.version + 1,
                created_at=_parse_timestamp(existing.created_at),
                updated_at=now,
            )
            result = session.execute(
                _UPDATE_ASSET,
                {
                    **_asset_database_params(session, stored),
                    "expected_version": existing.version,
                },
            )
            if result.rowcount != 1:
                raise WorkAssetError(
                    "WA_ASSET_CONCURRENT_UPDATE",
                    "WorkAsset changed concurrently",
                    409,
                )
            self._replace_bindings(session, stored)
        readback = self._select_asset(
            session,
            initial.tenant_id,
            initial.work_asset_id,
        )
        if readback is None:
            raise WorkAssetError(
                "WA_ASSET_STORE_UNAVAILABLE",
                "WorkAsset was not readable before local commit",
                503,
            )
        return readback

    def get(self, tenant_id: str, work_asset_id: str) -> WorkAssetRecord | None:
        normalized_tenant = _required_string(tenant_id, "tenant_id")
        normalized_id = _required_uuid(work_asset_id, "work_asset_id")
        try:
            with self._session_factory() as session:
                return self._select_asset(session, normalized_tenant, normalized_id)
        except SQLAlchemyError as exc:
            raise WorkAssetError(
                "WA_ASSET_STORE_UNAVAILABLE",
                "WorkAsset persistence is unavailable",
                503,
            ) from exc

    def _require_evidence(self, session: Session, record: WorkAssetRecord) -> None:
        expected_ids = {item.work_evidence_id for item in record.bindings}
        rows = session.execute(
            _SELECT_EVIDENCE_IDS,
            {
                "tenant_id": record.tenant_id,
                "work_evidence_ids": tuple(
                    _database_uuid(session, item) for item in sorted(expected_ids)
                ),
            },
        ).scalars()
        if {str(value) for value in rows} != expected_ids:
            raise WorkAssetError(
                "WA_ASSET_EVIDENCE_INVALID",
                "all WorkAsset evidence must exist in the same tenant",
                409,
            )

    def _insert_asset(self, session: Session, record: WorkAssetRecord) -> None:
        session.execute(_INSERT_ASSET, _asset_database_params(session, record))

    def _replace_bindings(self, session: Session, record: WorkAssetRecord) -> None:
        session.execute(
            _DELETE_BINDINGS,
            {
                "tenant_id": record.tenant_id,
                "work_asset_id": _database_uuid(session, record.work_asset_id),
            },
        )
        for binding in record.bindings:
            session.execute(
                _INSERT_BINDING,
                {
                    "tenant_id": record.tenant_id,
                    "work_asset_id": _database_uuid(session, record.work_asset_id),
                    "work_evidence_id": _database_uuid(
                        session, binding.work_evidence_id
                    ),
                    "binding_role": binding.binding_role,
                    "created_at": _parse_timestamp(binding.created_at),
                },
            )

    def _select_asset(
        self,
        session: Session,
        tenant_id: str,
        work_asset_id: str,
    ) -> WorkAssetRecord | None:
        row = session.execute(
            _SELECT_ASSET,
            {
                "tenant_id": tenant_id,
                "work_asset_id": _database_uuid(session, work_asset_id),
            },
        ).mappings().first()
        if row is None:
            return None
        bindings = tuple(
            WorkAssetBindingRecord(
                work_evidence_id=str(item["work_evidence_id"]),
                binding_role=str(item["binding_role"]),
                created_at=_row_timestamp(item["created_at"]),
            )
            for item in session.execute(
                _SELECT_BINDINGS,
                {
                    "tenant_id": tenant_id,
                    "work_asset_id": _database_uuid(session, work_asset_id),
                },
            ).mappings()
        )
        return _asset_from_row(row, bindings)


_ASSET_COLUMNS = """
    tenant_id,
    work_asset_id,
    asset_type,
    actor_type,
    actor_ref,
    agent_type_snapshot,
    project_ref,
    occurred_at,
    classification,
    asset_status,
    asset_hash,
    version,
    created_at,
    updated_at
"""
_SELECT_ASSET = text(
    f"SELECT {_ASSET_COLUMNS} FROM {WORK_ASSET_TABLE} "
    "WHERE tenant_id = :tenant_id AND work_asset_id = :work_asset_id"
)
_SELECT_BINDINGS = text(
    f"SELECT work_evidence_id, binding_role, created_at "
    f"FROM {WORK_ASSET_EVIDENCE_TABLE} "
    "WHERE tenant_id = :tenant_id AND work_asset_id = :work_asset_id "
    "ORDER BY binding_role, work_evidence_id"
)
_SELECT_EVIDENCE_IDS = text(
    "SELECT work_evidence_id FROM wa_work_evidence "
    "WHERE tenant_id = :tenant_id AND work_evidence_id IN :work_evidence_ids"
).bindparams(bindparam("work_evidence_ids", expanding=True))
_INSERT_ASSET = text(
    f"INSERT INTO {WORK_ASSET_TABLE} ({_ASSET_COLUMNS}) VALUES ("
    ":tenant_id, :work_asset_id, :asset_type, :actor_type, :actor_ref, "
    ":agent_type_snapshot, :project_ref, :occurred_at, :classification, "
    ":asset_status, :asset_hash, :version, :created_at, :updated_at)"
)
_UPDATE_ASSET = text(
    f"UPDATE {WORK_ASSET_TABLE} SET "
    "asset_type=:asset_type, actor_type=:actor_type, actor_ref=:actor_ref, "
    "agent_type_snapshot=:agent_type_snapshot, project_ref=:project_ref, "
    "occurred_at=:occurred_at, classification=:classification, "
    "asset_status=:asset_status, asset_hash=:asset_hash, version=:version, "
    "updated_at=:updated_at "
    "WHERE tenant_id=:tenant_id AND work_asset_id=:work_asset_id "
    "AND version=:expected_version"
)
_DELETE_BINDINGS = text(
    f"DELETE FROM {WORK_ASSET_EVIDENCE_TABLE} "
    "WHERE tenant_id=:tenant_id AND work_asset_id=:work_asset_id"
)
_INSERT_BINDING = text(
    f"INSERT INTO {WORK_ASSET_EVIDENCE_TABLE} ("
    "tenant_id, work_asset_id, work_evidence_id, binding_role, created_at) "
    "VALUES (:tenant_id, :work_asset_id, :work_evidence_id, :binding_role, :created_at)"
)


def _normalize_bindings(
    bindings: Iterable[WorkAssetBindingInput],
    *,
    asset_status: str,
) -> tuple[WorkAssetBindingRecord, ...]:
    normalized: list[WorkAssetBindingRecord] = []
    seen: set[str] = set()
    primary_count = 0
    for binding in bindings:
        evidence_id = _required_uuid(binding.work_evidence_id, "work_evidence_id")
        role = _choice(binding.binding_role, "binding_role", WORK_ASSET_BINDING_ROLES)
        if evidence_id in seen:
            raise _invalid("WorkEvidence cannot be bound to the same asset twice")
        seen.add(evidence_id)
        primary_count += role == "PRIMARY"
        normalized.append(
            WorkAssetBindingRecord(
                work_evidence_id=evidence_id,
                binding_role=role,
                created_at="",
            )
        )
    if primary_count > 1 or (asset_status == "ACTIVE" and primary_count != 1):
        raise WorkAssetError(
            "WA_ASSET_PRIMARY_INVALID",
            "ACTIVE WorkAsset requires exactly one PRIMARY binding",
            409,
        )
    now = _utc_timestamp(datetime.now(UTC), "binding created_at")
    return tuple(
        WorkAssetBindingRecord(item.work_evidence_id, item.binding_role, now)
        for item in sorted(
            normalized,
            key=lambda item: (item.binding_role, item.work_evidence_id),
        )
    )


def _asset_database_params(session: Session, record: WorkAssetRecord) -> dict[str, Any]:
    values = {
        key: value
        for key, value in record.to_dict().items()
        if key != "bindings"
    }
    for name in ("work_asset_id", "project_ref"):
        if values[name] is not None:
            values[name] = _database_uuid(session, str(values[name]))
    for name in ("occurred_at", "created_at", "updated_at"):
        values[name] = _parse_timestamp(str(values[name]))
    return values


def _asset_from_row(
    row: Any,
    bindings: tuple[WorkAssetBindingRecord, ...],
) -> WorkAssetRecord:
    return WorkAssetRecord(
        tenant_id=str(row["tenant_id"]),
        work_asset_id=str(row["work_asset_id"]),
        asset_type=str(row["asset_type"]),
        actor_type=str(row["actor_type"]),
        actor_ref=str(row["actor_ref"]),
        agent_type_snapshot=_optional_row_string(row["agent_type_snapshot"]),
        project_ref=_optional_row_string(row["project_ref"]),
        occurred_at=_row_timestamp(row["occurred_at"]),
        classification=str(row["classification"]),
        asset_status=str(row["asset_status"]),
        asset_hash=str(row["asset_hash"]),
        version=int(row["version"]),
        created_at=_row_timestamp(row["created_at"]),
        updated_at=_row_timestamp(row["updated_at"]),
        bindings=bindings,
    )


def _database_uuid(session: Session, value: str) -> str | UUID:
    bind = session.get_bind()
    return UUID(value) if bind is not None and bind.dialect.name == "postgresql" else value


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
    return None if value is None else _choice(value, field, allowed)


def _required_uuid(value: object, field: str) -> str:
    normalized = _required_string(value, field)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _optional_uuid(value: object, field: str) -> str | None:
    return None if value is None else _required_uuid(value, field)


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkAssetError(
            "WA_ASSET_STORE_UNAVAILABLE", "stored WorkAsset timestamp is invalid", 503
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return _utc_timestamp(value, "stored timestamp")
    if isinstance(value, str):
        return _utc_timestamp(_parse_timestamp(value), "stored timestamp")
    raise WorkAssetError(
        "WA_ASSET_STORE_UNAVAILABLE", "stored WorkAsset timestamp is invalid", 503
    )


def _optional_row_string(value: object) -> str | None:
    return None if value is None else str(value)


def _invalid(detail: str) -> WorkAssetError:
    return WorkAssetError("WA_ASSET_INVALID", detail, 422)
