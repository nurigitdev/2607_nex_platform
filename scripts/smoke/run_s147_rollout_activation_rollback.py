#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    RegisterCatalogEntry,
)
from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.model_rollout_activation import (
    activate_rollout_alias,
    rollback_rollout_alias,
)
from nex_mo.model_rollout_state import (
    CanaryMetrics,
    CanaryPolicy,
    begin_validation,
    evaluate_canary,
    mark_rollout_ready,
    register_rollout,
    start_canary,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcdef"]


def run_rollout_activation_rollback() -> dict[str, Any]:
    identifiers = iter(("candidate", "activation", "rollback"))
    service = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: "2026-10-08T00:00:00Z",
        id_factory=lambda: next(identifiers),
    )
    service.ensure_bootstrap()
    stable_binding = next(
        item
        for item in service.list_alias_bindings(state="ACTIVE")
        if item.provider_capability == "generation"
    )
    stable_entry = service.get_catalog_entry(stable_binding.catalog_id)
    stable = _identity(
        stable_binding.alias,
        stable_entry.catalog_id,
        stable_entry.model_revision,
        stable_entry.deployment_id,
        stable_entry.precision,
        DIGESTS[0],
    )
    candidate_entry = service.register_catalog_entry(
        RegisterCatalogEntry(
            provider_capability="generation",
            model_name="Candidate",
            model_revision="candidate-v2",
            deployment_id="candidate-generation-v2",
            runtime_profile="candidate",
            precision="bfloat16",
            provider_type="openai-compatible",
            supports_response_formats=("text", "json_object"),
            max_input_tokens=8192,
            max_output_tokens=1024,
        )
    )
    candidate_entry = service.transition_catalog_entry(
        candidate_entry.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    candidate = _identity(
        stable.alias,
        candidate_entry.catalog_id,
        candidate_entry.model_revision,
        candidate_entry.deployment_id,
        candidate_entry.precision,
        DIGESTS[2],
    )
    record = register_rollout(
        candidate,
        rollout_id="rollout:generation:2",
        last_known_good_binding_id=stable_binding.binding_id,
        last_known_good_identity_fingerprint=stable.fingerprint,
        created_at="2026-10-08T00:00:00Z",
    )
    record = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    reservation = CapacityReservation(
        "reservation:generation:2",
        record.rollout_id,
        candidate.fingerprint,
        "node:one",
        1,
        20_000,
        2,
        False,
    )
    record = mark_rollout_ready(
        record,
        {"status": "READY", "identity_fingerprint": candidate.fingerprint, "evidence_digest": DIGESTS[3]},
        {"status": "CALIBRATED", "identity_fingerprint": candidate.fingerprint, "profile_id": "calibration:generation:2", "profile_hash": DIGESTS[4]},
        reservation,
        changed_at="2026-10-08T00:02:00Z",
    )
    policy = CanaryPolicy(10, 300, 100, 0.02, 0.85, 2_000)
    record = start_canary(record, policy, changed_at="2026-10-08T00:03:00Z")
    record, decision = evaluate_canary(
        record,
        policy,
        CanaryMetrics(candidate.fingerprint, 120, 0.01, 0.9, 1_500, 360, "2026-10-08T00:09:00Z"),
        changed_at="2026-10-08T00:09:00Z",
    )
    activated = activate_rollout_alias(
        record,
        decision,
        reservation,
        stable,
        service,
        changed_by="operator:smoke",
        changed_at="2026-10-08T00:10:00Z",
    )
    rolled_back = rollback_rollout_alias(
        activated.record,
        reservation,
        stable,
        {"status": "READY", "identity_fingerprint": stable.fingerprint, "evidence_digest": DIGESTS[5]},
        service,
        failure_code="quality_regression",
        changed_by="operator:smoke",
        changed_at="2026-10-08T00:11:00Z",
    )
    history = service.list_alias_bindings(alias=stable.alias, capability="generation")
    checks = {
        "canary_promoted_atomically": activated.record.state == "ACTIVE" and activated.binding.binding_revision == 2,
        "activation_bound_to_candidate": activated.binding.catalog_id == candidate.catalog_id,
        "last_known_good_lineage_preserved": activated.binding.previous_binding_id == stable_binding.binding_id,
        "rollback_restored_exact_catalog": rolled_back.binding.catalog_id == stable.catalog_id,
        "rollback_state_terminal": rolled_back.record.state == "ROLLED_BACK",
        "candidate_capacity_released": rolled_back.reservation.state == "RELEASED",
        "candidate_artifact_preserved": service.get_catalog_entry(candidate.catalog_id).catalog_state == "ACTIVE",
        "alias_history_preserved": len(history) == 3,
        "one_active_alias": sum(item.binding_state == "ACTIVE" for item in history) == 1,
        "candidate_binding_marked_rolled_back": any(item.binding_state == "ROLLED_BACK" for item in history),
        "metadata_only_result": "model_name" not in rolled_back.to_wire() and "endpoint" not in rolled_back.to_wire(),
        "decision_digest_bound": rolled_back.decision_digest.startswith("sha256:"),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_rollout_activation_rollback.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "binding_count": len(history),
            "active_count": sum(item.binding_state == "ACTIVE" for item in history),
            "released_count": int(rolled_back.reservation.state == "RELEASED"),
            "check_count": len(checks),
        },
        "next_slice": "1470" if passed else "blocked",
    }


def _identity(alias, catalog_id, revision, deployment, precision, artifact):
    return ModelRevisionIdentity(
        provider_capability="generation",
        alias=alias,
        catalog_id=catalog_id,
        model_revision=revision,
        deployment_id=deployment,
        artifact_digest=artifact,
        runtime_engine="openai-compatible",
        precision=precision,
        request_shape_hash=DIGESTS[1],
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"rollout_activation_rollback={str(result.get('status') or 'FAIL').lower()} "
        f"bindings={summary.get('binding_count', 0)} "
        f"active={summary.get('active_count', 0)} "
        f"released={summary.get('released_count', 0)} "
        f"checks={summary.get('check_count', 0)}/12 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_rollout_activation_rollback()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
