from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_mo.model_rollout import ModelRolloutError

ROLLOUT_EVENT_TYPES = frozenset(
    {
        "rollout.registered",
        "rollout.validation_started",
        "rollout.ready",
        "rollout.canary_started",
        "rollout.canary_evaluated",
        "rollout.activated",
        "rollout.blocked",
        "rollout.rolled_back",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ModelRolloutEvent:
    event_id: str
    rollout_id: str
    event_type: str
    from_state: str | None
    to_state: str
    state_revision: int
    evidence_digest: str | None
    failure_code: str | None
    occurred_at: str

    def __post_init__(self) -> None:
        for field_name in ("event_id", "rollout_id", "to_state"):
            _identifier(getattr(self, field_name), field_name)
        if self.from_state is not None:
            _identifier(self.from_state, "from_state")
        if self.event_type not in ROLLOUT_EVENT_TYPES:
            raise ModelRolloutError(
                "mo.rollout_event_type_invalid",
                "unsupported rollout event type",
            )
        if self.state_revision < 1:
            raise ModelRolloutError(
                "mo.rollout_event_revision_invalid",
                "rollout event revision must be positive",
            )
        if self.evidence_digest is not None:
            _digest(self.evidence_digest, "evidence_digest")
        if self.failure_code is not None:
            _identifier(self.failure_code, "failure_code")
        _timestamp(self.occurred_at, "occurred_at")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "mo_model_rollout_event.v1",
            "event_id": self.event_id,
            "rollout_id": self.rollout_id,
            "event_type": self.event_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "state_revision": self.state_revision,
            "evidence_digest": self.evidence_digest,
            "failure_code": self.failure_code,
            "occurred_at": self.occurred_at,
        }


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a SHA-256 digest",
        )
    return value


def _timestamp(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be ISO 8601",
        ) from exc
    if parsed.tzinfo is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed.astimezone(UTC)
