from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.model_rollout import MODEL_CAPABILITIES, ModelRevisionIdentity
from nex_mo.model_rollout_persistence import ModelRolloutEvent
from nex_mo.model_rollout_state import ROLLOUT_STATES, ModelRolloutRecord


class ModelRolloutRepositoryError(RuntimeError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


class ModelRolloutRepository(Protocol):
    def insert(
        self, record: ModelRolloutRecord, event: ModelRolloutEvent
    ) -> ModelRolloutRecord: ...
    def get(self, rollout_id: str) -> ModelRolloutRecord | None: ...
    def list(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> Sequence[ModelRolloutRecord]: ...
    def update(
        self,
        record: ModelRolloutRecord,
        event: ModelRolloutEvent,
        *,
        expected_state_revision: int,
    ) -> ModelRolloutRecord: ...
    def list_events(self, rollout_id: str) -> Sequence[ModelRolloutEvent]: ...


class InMemoryModelRolloutRepository:
    def __init__(self) -> None:
        self._records: dict[str, ModelRolloutRecord] = {}
        self._events: dict[str, list[ModelRolloutEvent]] = {}
        self._lock = RLock()

    def insert(
        self,
        record: ModelRolloutRecord,
        event: ModelRolloutEvent,
    ) -> ModelRolloutRecord:
        with self._lock:
            if record.rollout_id in self._records:
                raise ModelRolloutRepositoryError(
                    "mo.rollout_conflict",
                    "rollout identity conflicts with durable state",
                )
            _validate_event(record, event)
            self._records[record.rollout_id] = record
            self._events[record.rollout_id] = [event]
            return record

    def get(self, rollout_id: str) -> ModelRolloutRecord | None:
        with self._lock:
            return self._records.get(rollout_id)

    def list(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[ModelRolloutRecord]:
        _validate_filters(capability, state, limit)
        with self._lock:
            records = [
                record
                for record in self._records.values()
                if (
                    capability is None
                    or record.identity.provider_capability == capability
                )
                and (state is None or record.state == state)
            ]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]

    def update(
        self,
        record: ModelRolloutRecord,
        event: ModelRolloutEvent,
        *,
        expected_state_revision: int,
    ) -> ModelRolloutRecord:
        with self._lock:
            current = self._records.get(record.rollout_id)
            if current is None:
                raise ModelRolloutRepositoryError(
                    "mo.rollout_not_found",
                    "rollout was not found",
                )
            _validate_update(current, record, event, expected_state_revision)
            self._records[record.rollout_id] = record
            self._events[record.rollout_id].append(event)
            return record

    def list_events(self, rollout_id: str) -> list[ModelRolloutEvent]:
        with self._lock:
            if rollout_id not in self._records:
                raise ModelRolloutRepositoryError(
                    "mo.rollout_not_found",
                    "rollout was not found",
                )
            return list(self._events[rollout_id])


class SqlAlchemyModelRolloutRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert(
        self,
        record: ModelRolloutRecord,
        event: ModelRolloutEvent,
    ) -> ModelRolloutRecord:
        _validate_event(record, event)
        session = self._session_factory()
        try:
            try:
                session.execute(text(_INSERT_ROLLOUT_SQL), _rollout_params(record))
                session.execute(text(_INSERT_EVENT_SQL), _event_params(event))
                session.commit()
                return record
            except Exception:
                session.rollback()
                raise
        except IntegrityError as exc:
            raise ModelRolloutRepositoryError(
                "mo.rollout_conflict",
                "rollout insert conflicts with durable state",
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def get(self, rollout_id: str) -> ModelRolloutRecord | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_SELECT_ROLLOUT_SQL + " WHERE rollout_id = :rollout_id"),
                        {"rollout_id": rollout_id},
                    )
                    .mappings()
                    .first()
                )
            return None if row is None else _rollout_from_mapping(row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def list(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[ModelRolloutRecord]:
        _validate_filters(capability, state, limit)
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if capability is not None:
            clauses.append("capability = :capability")
            params["capability"] = capability
        if state is not None:
            clauses.append("rollout_state = :rollout_state")
            params["rollout_state"] = state
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _SELECT_ROLLOUT_SQL
                            + where
                            + " ORDER BY updated_at DESC LIMIT :limit"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [_rollout_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def update(
        self,
        record: ModelRolloutRecord,
        event: ModelRolloutEvent,
        *,
        expected_state_revision: int,
    ) -> ModelRolloutRecord:
        session = self._session_factory()
        try:
            try:
                current_row = (
                    session.execute(
                        text(_SELECT_ROLLOUT_SQL + " WHERE rollout_id = :rollout_id"),
                        {"rollout_id": record.rollout_id},
                    )
                    .mappings()
                    .first()
                )
                if current_row is None:
                    raise ModelRolloutRepositoryError(
                        "mo.rollout_not_found",
                        "rollout was not found",
                    )
                current = _rollout_from_mapping(current_row)
                _validate_update(current, record, event, expected_state_revision)
                params = _rollout_params(record)
                params["expected_state_revision"] = expected_state_revision
                result = session.execute(text(_UPDATE_ROLLOUT_SQL), params)
                if int(result.rowcount or 0) != 1:
                    raise ModelRolloutRepositoryError(
                        "mo.rollout_revision_conflict",
                        "rollout changed during update",
                    )
                session.execute(text(_INSERT_EVENT_SQL), _event_params(event))
                session.commit()
                return record
            except Exception:
                session.rollback()
                raise
        except ModelRolloutRepositoryError:
            raise
        except IntegrityError as exc:
            raise ModelRolloutRepositoryError(
                "mo.rollout_revision_conflict",
                "rollout update conflicts with durable state",
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def list_events(self, rollout_id: str) -> list[ModelRolloutEvent]:
        if self.get(rollout_id) is None:
            raise ModelRolloutRepositoryError(
                "mo.rollout_not_found",
                "rollout was not found",
            )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _SELECT_EVENT_SQL
                            + " WHERE rollout_id = :rollout_id ORDER BY state_revision ASC"
                        ),
                        {"rollout_id": rollout_id},
                    )
                    .mappings()
                    .all()
                )
            return [_event_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc


def _validate_filters(capability: str | None, state: str | None, limit: int) -> None:
    if capability is not None and capability not in MODEL_CAPABILITIES:
        raise ModelRolloutRepositoryError(
            "mo.rollout_filter_invalid",
            "unsupported rollout capability filter",
        )
    if state is not None and state not in ROLLOUT_STATES:
        raise ModelRolloutRepositoryError(
            "mo.rollout_filter_invalid",
            "unsupported rollout state filter",
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ModelRolloutRepositoryError(
            "mo.rollout_filter_invalid",
            "rollout limit must be between 1 and 200",
        )


def _validate_event(record: ModelRolloutRecord, event: ModelRolloutEvent) -> None:
    if (
        event.rollout_id != record.rollout_id
        or event.to_state != record.state
        or event.state_revision != record.state_revision
    ):
        raise ModelRolloutRepositoryError(
            "mo.rollout_event_mismatch",
            "rollout event does not match persisted state",
        )


def _validate_update(
    current: ModelRolloutRecord,
    record: ModelRolloutRecord,
    event: ModelRolloutEvent,
    expected_state_revision: int,
) -> None:
    if current.state_revision != expected_state_revision:
        raise ModelRolloutRepositoryError(
            "mo.rollout_revision_conflict",
            "rollout revision does not match expected revision",
        )
    if (
        record.state_revision != expected_state_revision + 1
        or record.identity.fingerprint != current.identity.fingerprint
        or record.created_at != current.created_at
        or record.last_known_good_binding_id != current.last_known_good_binding_id
        or record.last_known_good_identity_fingerprint
        != current.last_known_good_identity_fingerprint
    ):
        raise ModelRolloutRepositoryError(
            "mo.rollout_immutable_drift",
            "rollout identity, lineage, or revision has drifted",
        )
    if event.from_state != current.state:
        raise ModelRolloutRepositoryError(
            "mo.rollout_event_mismatch",
            "rollout event source state does not match durable state",
        )
    _validate_event(record, event)


def _rollout_params(record: ModelRolloutRecord) -> dict[str, Any]:
    identity = record.identity
    return {
        "rollout_id": record.rollout_id,
        "capability": identity.provider_capability,
        "alias": identity.alias,
        "catalog_id": identity.catalog_id,
        "model_revision": identity.model_revision,
        "deployment_id": identity.deployment_id,
        "artifact_digest": identity.artifact_digest,
        "runtime_engine": identity.runtime_engine,
        "precision": identity.precision,
        "request_shape_hash": identity.request_shape_hash,
        "identity_fingerprint": identity.fingerprint,
        "rollout_state": record.state,
        "state_revision": record.state_revision,
        "lkg_binding_id": record.last_known_good_binding_id,
        "lkg_identity_fingerprint": record.last_known_good_identity_fingerprint,
        "readiness_digest": record.readiness_evidence_digest,
        "calibration_profile_id": record.calibration_profile_id,
        "calibration_profile_hash": record.calibration_profile_hash,
        "reservation_id": record.reservation_id,
        "canary_policy_hash": record.canary_policy_hash,
        "canary_status": record.canary_status,
        "activated_binding_id": record.activated_binding_id,
        "failure_code": record.failure_code,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _event_params(event: ModelRolloutEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "rollout_id": event.rollout_id,
        "event_type": event.event_type,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "state_revision": event.state_revision,
        "evidence_digest": event.evidence_digest,
        "failure_code": event.failure_code,
        "occurred_at": event.occurred_at,
    }


def _rollout_from_mapping(row: Any) -> ModelRolloutRecord:
    identity = ModelRevisionIdentity(
        provider_capability=str(row["capability"]),
        alias=str(row["alias"]),
        catalog_id=str(row["catalog_id"]),
        model_revision=str(row["model_revision"]),
        deployment_id=str(row["deployment_id"]),
        artifact_digest=str(row["artifact_digest"]),
        runtime_engine=str(row["runtime_engine"]),
        precision=str(row["precision"]),
        request_shape_hash=str(row["request_shape_hash"]),
    )
    if identity.fingerprint != str(row["identity_fingerprint"]):
        raise ValueError("persisted rollout identity fingerprint does not match")
    return ModelRolloutRecord(
        rollout_id=str(row["rollout_id"]),
        identity=identity,
        state=str(row["rollout_state"]),
        state_revision=int(row["state_revision"]),
        last_known_good_binding_id=str(row["lkg_binding_id"]),
        last_known_good_identity_fingerprint=str(row["lkg_identity_fingerprint"]),
        readiness_evidence_digest=_optional(row["readiness_digest"]),
        calibration_profile_id=_optional(row["calibration_profile_id"]),
        calibration_profile_hash=_optional(row["calibration_profile_hash"]),
        reservation_id=_optional(row["reservation_id"]),
        canary_policy_hash=_optional(row["canary_policy_hash"]),
        canary_status=_optional(row["canary_status"]),
        activated_binding_id=_optional(row["activated_binding_id"]),
        failure_code=_optional(row["failure_code"]),
        created_at=_timestamp_text(row["created_at"]),
        updated_at=_timestamp_text(row["updated_at"]),
    )


def _event_from_mapping(row: Any) -> ModelRolloutEvent:
    return ModelRolloutEvent(
        event_id=str(row["event_id"]),
        rollout_id=str(row["rollout_id"]),
        event_type=str(row["event_type"]),
        from_state=_optional(row["from_state"]),
        to_state=str(row["to_state"]),
        state_revision=int(row["state_revision"]),
        evidence_digest=_optional(row["evidence_digest"]),
        failure_code=_optional(row["failure_code"]),
        occurred_at=_timestamp_text(row["occurred_at"]),
    )


def _optional(value: Any) -> str | None:
    return None if value is None else str(value)


def _timestamp_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _unavailable() -> ModelRolloutRepositoryError:
    return ModelRolloutRepositoryError(
        "mo.rollout_persistence_unavailable",
        "model rollout persistence is unavailable",
    )


_SELECT_ROLLOUT_SQL = """
SELECT rollout_id, capability, alias, catalog_id, model_revision, deployment_id,
       artifact_digest, runtime_engine, precision, request_shape_hash,
       identity_fingerprint, rollout_state, state_revision, lkg_binding_id,
       lkg_identity_fingerprint, readiness_digest, calibration_profile_id,
       calibration_profile_hash, reservation_id, canary_policy_hash,
       canary_status, activated_binding_id, failure_code, created_at, updated_at
FROM mo_model_rollouts
"""

_INSERT_ROLLOUT_SQL = """
INSERT INTO mo_model_rollouts (
    rollout_id, capability, alias, catalog_id, model_revision, deployment_id,
    artifact_digest, runtime_engine, precision, request_shape_hash,
    identity_fingerprint, rollout_state, state_revision, lkg_binding_id,
    lkg_identity_fingerprint, readiness_digest, calibration_profile_id,
    calibration_profile_hash, reservation_id, canary_policy_hash,
    canary_status, activated_binding_id, failure_code, created_at, updated_at
) VALUES (
    :rollout_id, :capability, :alias, :catalog_id, :model_revision, :deployment_id,
    :artifact_digest, :runtime_engine, :precision, :request_shape_hash,
    :identity_fingerprint, :rollout_state, :state_revision, :lkg_binding_id,
    :lkg_identity_fingerprint, :readiness_digest, :calibration_profile_id,
    :calibration_profile_hash, :reservation_id, :canary_policy_hash,
    :canary_status, :activated_binding_id, :failure_code, :created_at, :updated_at
)
"""

_UPDATE_ROLLOUT_SQL = """
UPDATE mo_model_rollouts
SET rollout_state = :rollout_state,
    state_revision = :state_revision,
    readiness_digest = :readiness_digest,
    calibration_profile_id = :calibration_profile_id,
    calibration_profile_hash = :calibration_profile_hash,
    reservation_id = :reservation_id,
    canary_policy_hash = :canary_policy_hash,
    canary_status = :canary_status,
    activated_binding_id = :activated_binding_id,
    failure_code = :failure_code,
    updated_at = :updated_at
WHERE rollout_id = :rollout_id
  AND state_revision = :expected_state_revision
"""

_SELECT_EVENT_SQL = """
SELECT event_id, rollout_id, event_type, from_state, to_state, state_revision,
       evidence_digest, failure_code, occurred_at
FROM mo_rollout_events
"""

_INSERT_EVENT_SQL = """
INSERT INTO mo_rollout_events (
    event_id, rollout_id, event_type, from_state, to_state, state_revision,
    evidence_digest, failure_code, occurred_at
) VALUES (
    :event_id, :rollout_id, :event_type, :from_state, :to_state, :state_revision,
    :evidence_digest, :failure_code, :occurred_at
)
"""
