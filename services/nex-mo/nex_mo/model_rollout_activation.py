from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_mo.catalog_lifecycle import AliasBinding, ModelCatalogEntry
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService
from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity, ModelRolloutError
from nex_mo.model_rollout_state import (
    ModelRolloutRecord,
    mark_rollout_active,
    mark_rollout_rolled_back,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class RolloutAliasResult:
    operation: str
    record: ModelRolloutRecord
    binding: AliasBinding
    reservation: CapacityReservation
    decision_digest: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "mo_rollout_alias_result.v1",
            "operation": self.operation,
            "rollout_id": self.record.rollout_id,
            "state": self.record.state,
            "state_revision": self.record.state_revision,
            "identity_fingerprint": self.record.identity.fingerprint,
            "binding_id": self.binding.binding_id,
            "binding_revision": self.binding.binding_revision,
            "reservation_id": self.reservation.reservation_id,
            "reservation_state": self.reservation.state,
            "decision_digest": self.decision_digest,
        }


def activate_rollout_alias(
    record: ModelRolloutRecord,
    canary_decision: Mapping[str, Any],
    reservation: CapacityReservation,
    last_known_good_identity: ModelRevisionIdentity,
    catalog_service: CatalogLifecycleService,
    *,
    changed_by: str,
    changed_at: str,
) -> RolloutAliasResult:
    _validate_promotion(record, canary_decision, reservation)
    stable = _active_binding(catalog_service, record.identity)
    _validate_last_known_good(record, stable, last_known_good_identity)
    candidate = catalog_service.get_catalog_entry(record.identity.catalog_id)
    _validate_catalog_identity(record.identity, candidate)

    binding = catalog_service.activate_alias(
        alias=record.identity.alias,
        capability=record.identity.provider_capability,
        catalog_id=record.identity.catalog_id,
        expected_binding_revision=stable.binding_revision,
        change_reason="Model rollout canary passed",
        changed_by=changed_by,
    )
    updated = mark_rollout_active(
        record,
        activated_binding_id=binding.binding_id,
        changed_at=changed_at,
    )
    return RolloutAliasResult(
        operation="ACTIVATED",
        record=updated,
        binding=binding,
        reservation=reservation,
        decision_digest=_digest(canary_decision),
    )


def rollback_rollout_alias(
    record: ModelRolloutRecord,
    reservation: CapacityReservation,
    last_known_good_identity: ModelRevisionIdentity,
    last_known_good_readiness: Mapping[str, Any],
    catalog_service: CatalogLifecycleService,
    *,
    failure_code: str,
    changed_by: str,
    changed_at: str,
) -> RolloutAliasResult:
    if record.state != "ACTIVE" or record.activated_binding_id is None:
        raise ModelRolloutError(
            "mo.rollout_rollback_not_available",
            "an active rollout binding is required before rollback",
        )
    _validate_reservation(record, reservation)
    current = _active_binding(catalog_service, record.identity)
    if (
        current.binding_id != record.activated_binding_id
        or current.catalog_id != record.identity.catalog_id
    ):
        raise ModelRolloutError(
            "mo.rollout_active_binding_drift",
            "active alias no longer matches the rollout binding",
        )
    _validate_last_known_good_readiness(
        record,
        last_known_good_identity,
        last_known_good_readiness,
    )
    history = catalog_service.list_alias_bindings(
        alias=record.identity.alias,
        capability=record.identity.provider_capability,
    )
    stable = next(
        (item for item in history if item.binding_id == record.last_known_good_binding_id),
        None,
    )
    if stable is None:
        raise ModelRolloutError(
            "mo.rollout_last_known_good_missing",
            "last-known-good alias binding was not found",
        )
    _validate_last_known_good(record, stable, last_known_good_identity)

    binding = catalog_service.rollback_alias(
        alias=record.identity.alias,
        capability=record.identity.provider_capability,
        expected_binding_revision=current.binding_revision,
        change_reason="Model rollout rollback",
        changed_by=changed_by,
    )
    if binding.catalog_id != stable.catalog_id:
        raise ModelRolloutError(
            "mo.rollout_rollback_target_drift",
            "rollback did not restore the exact last-known-good catalog",
        )
    released = reservation.release()
    updated = mark_rollout_rolled_back(
        record,
        failure_code=failure_code,
        changed_at=changed_at,
    )
    return RolloutAliasResult(
        operation="ROLLED_BACK",
        record=updated,
        binding=binding,
        reservation=released,
        decision_digest=_digest(last_known_good_readiness),
    )


def _validate_promotion(
    record: ModelRolloutRecord,
    decision: Mapping[str, Any],
    reservation: CapacityReservation,
) -> None:
    if record.state != "CANARY" or record.canary_status != "PASSED":
        raise ModelRolloutError(
            "mo.rollout_promotion_not_admitted",
            "a passing canary is required before alias activation",
        )
    if (
        decision.get("status") != "PASS"
        or decision.get("promotable") is not True
        or decision.get("identity_fingerprint") != record.identity.fingerprint
        or decision.get("policy_hash") != record.canary_policy_hash
        or _SHA256.fullmatch(str(decision.get("metrics_digest") or "")) is None
    ):
        raise ModelRolloutError(
            "mo.rollout_canary_decision_invalid",
            "matching promotable canary evidence is required",
        )
    _validate_reservation(record, reservation)


def _validate_reservation(
    record: ModelRolloutRecord,
    reservation: CapacityReservation,
) -> None:
    if (
        reservation.reservation_id != record.reservation_id
        or reservation.rollout_id != record.rollout_id
        or reservation.identity_fingerprint != record.identity.fingerprint
        or reservation.state != "RESERVED"
    ):
        raise ModelRolloutError(
            "mo.rollout_reservation_drift",
            "the candidate capacity reservation is missing or mismatched",
        )


def _active_binding(
    catalog_service: CatalogLifecycleService,
    identity: ModelRevisionIdentity,
) -> AliasBinding:
    bindings = catalog_service.list_alias_bindings(
        alias=identity.alias,
        capability=identity.provider_capability,
        state="ACTIVE",
    )
    if len(bindings) != 1:
        raise ModelRolloutError(
            "mo.rollout_active_binding_invalid",
            "exactly one active alias binding is required",
        )
    return bindings[0]


def _validate_last_known_good(
    record: ModelRolloutRecord,
    binding: AliasBinding,
    identity: ModelRevisionIdentity,
) -> None:
    if (
        binding.binding_id != record.last_known_good_binding_id
        or binding.catalog_id != identity.catalog_id
        or binding.alias != identity.alias
        or binding.provider_capability != identity.provider_capability
        or identity.fingerprint != record.last_known_good_identity_fingerprint
    ):
        raise ModelRolloutError(
            "mo.rollout_last_known_good_drift",
            "last-known-good alias lineage or identity has drifted",
        )


def _validate_last_known_good_readiness(
    record: ModelRolloutRecord,
    identity: ModelRevisionIdentity,
    readiness: Mapping[str, Any],
) -> None:
    if (
        identity.fingerprint != record.last_known_good_identity_fingerprint
        or readiness.get("status") != "READY"
        or readiness.get("identity_fingerprint") != identity.fingerprint
        or _SHA256.fullmatch(str(readiness.get("evidence_digest") or "")) is None
    ):
        raise ModelRolloutError(
            "mo.rollout_last_known_good_not_ready",
            "exact last-known-good readiness evidence is required",
        )


def _validate_catalog_identity(
    identity: ModelRevisionIdentity,
    entry: ModelCatalogEntry,
) -> None:
    if (
        entry.catalog_id != identity.catalog_id
        or entry.provider_capability != identity.provider_capability
        or entry.model_revision != identity.model_revision
        or entry.deployment_id != identity.deployment_id
        or entry.precision.casefold() != identity.precision.casefold()
    ):
        raise ModelRolloutError(
            "mo.rollout_catalog_identity_drift",
            "candidate catalog metadata does not match rollout identity",
        )


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
