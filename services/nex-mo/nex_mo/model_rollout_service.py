from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import uuid4

from nex_mo.model_rollout_persistence import ModelRolloutEvent
from nex_mo.model_rollout_repository import (
    ModelRolloutRepository,
    ModelRolloutRepositoryError,
)
from nex_mo.model_rollout_state import ModelRolloutRecord


class ModelRolloutServiceError(RuntimeError):
    def __init__(self, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


class ModelRolloutService:
    def __init__(
        self,
        repository: ModelRolloutRepository,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def register(self, record: ModelRolloutRecord) -> ModelRolloutRecord:
        if record.state != "REGISTERED" or record.state_revision != 1:
            raise ModelRolloutServiceError(
                409,
                "MO_ROLLOUT_REGISTRATION_INVALID",
                "Only an initial REGISTERED rollout may be persisted.",
            )
        event = self._event(
            record,
            event_type="rollout.registered",
            from_state=None,
            evidence_digest=None,
        )
        try:
            return self._repository.insert(record, event)
        except ModelRolloutRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def persist_transition(
        self,
        record: ModelRolloutRecord,
        *,
        expected_state_revision: int,
        event_type: str,
        evidence_digest: str | None = None,
    ) -> ModelRolloutRecord:
        current = self.get(record.rollout_id)
        event = self._event(
            record,
            event_type=event_type,
            from_state=current.state,
            evidence_digest=evidence_digest,
        )
        try:
            return self._repository.update(
                record,
                event,
                expected_state_revision=expected_state_revision,
            )
        except ModelRolloutRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def get(self, rollout_id: str) -> ModelRolloutRecord:
        try:
            record = self._repository.get(rollout_id)
        except ModelRolloutRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        if record is None:
            raise ModelRolloutServiceError(
                404,
                "MO_ROLLOUT_NOT_FOUND",
                "Model rollout was not found.",
            )
        return record

    def list(
        self,
        *,
        capability: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> Sequence[ModelRolloutRecord]:
        try:
            return self._repository.list(
                capability=capability,
                state=state,
                limit=limit,
            )
        except ModelRolloutRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def list_events(self, rollout_id: str) -> Sequence[ModelRolloutEvent]:
        try:
            return self._repository.list_events(rollout_id)
        except ModelRolloutRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def _event(
        self,
        record: ModelRolloutRecord,
        *,
        event_type: str,
        from_state: str | None,
        evidence_digest: str | None,
    ) -> ModelRolloutEvent:
        return ModelRolloutEvent(
            event_id=f"event:{self._id_factory()}",
            rollout_id=record.rollout_id,
            event_type=event_type,
            from_state=from_state,
            to_state=record.state,
            state_revision=record.state_revision,
            evidence_digest=evidence_digest,
            failure_code=record.failure_code,
            occurred_at=record.updated_at,
        )


def _map_repository_error(
    error: ModelRolloutRepositoryError,
) -> ModelRolloutServiceError:
    mappings = {
        "mo.rollout_not_found": (404, "MO_ROLLOUT_NOT_FOUND"),
        "mo.rollout_conflict": (409, "MO_ROLLOUT_CONFLICT"),
        "mo.rollout_revision_conflict": (409, "MO_ROLLOUT_REVISION_CONFLICT"),
        "mo.rollout_immutable_drift": (409, "MO_ROLLOUT_IMMUTABLE_DRIFT"),
        "mo.rollout_event_mismatch": (409, "MO_ROLLOUT_EVENT_MISMATCH"),
        "mo.rollout_filter_invalid": (422, "MO_ROLLOUT_FILTER_INVALID"),
    }
    status_code, error_code = mappings.get(
        error.error_code,
        (503, "MO_ROLLOUT_PERSISTENCE_UNAVAILABLE"),
    )
    detail = (
        error.detail
        if error.error_code in mappings
        else "Model rollout persistence is temporarily unavailable."
    )
    return ModelRolloutServiceError(status_code, error_code, detail)
