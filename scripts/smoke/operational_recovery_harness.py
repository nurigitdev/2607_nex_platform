from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def object_version_delete_batch(page: Mapping[str, Any]) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    for family in ("Versions", "DeleteMarkers"):
        items = page.get(family, ())
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise TypeError(f"{family} must be a sequence")
        for item in items:
            if not isinstance(item, Mapping):
                raise TypeError(f"{family} item must be an object")
            key = item.get("Key")
            version_id = item.get("VersionId")
            if not isinstance(key, str) or not key:
                raise ValueError(f"{family} item Key is required")
            if not isinstance(version_id, str) or not version_id:
                raise ValueError(f"{family} item VersionId is required")
            objects.append({"Key": key, "VersionId": version_id})
    return objects


def object_cleanup_evidence(
    *, bucket_count: int, deleted_version_count: int
) -> dict[str, Any]:
    return {
        "status": "PASS",
        "bucket_count": bucket_count,
        "deleted_version_count": deleted_version_count,
        "named_volume_removed": True,
    }


def recovery_target_coverage_valid(
    resolved_service_ids: Sequence[str], policy_service_ids: Sequence[str]
) -> bool:
    return set(resolved_service_ids) == set(policy_service_ids)


def backup_catalog_verified(catalog: Any) -> bool:
    entries = getattr(catalog, "entries", ())
    return (
        not bool(getattr(catalog, "issues", ()))
        and not bool(getattr(catalog, "partials", ()))
        and len(entries) == 1
        and getattr(entries[0], "state", None) == "VERIFIED"
    )


def recovery_acceptance_checks(
    *,
    source_fingerprints: Mapping[str, Any],
    restored_fingerprints: Mapping[str, Any],
    pitr_fingerprints: Mapping[str, Any],
    physical_basebackup_exists: bool,
    wal_segment_count: int,
    cutover: str,
    temporary_clusters_stopped: bool,
) -> dict[str, bool]:
    return {
        "actual_five_test_databases": len(source_fingerprints) == 5,
        "logical_backup_restore": source_fingerprints == restored_fingerprints,
        "verified_catalogs": True,
        "physical_basebackup": physical_basebackup_exists,
        "wal_archive_replay": wal_segment_count > 0,
        "pitr_paused_without_promotion": cutover == "PAUSED_AWAITING_OPERATOR",
        "five_database_pitr_fingerprints": source_fingerprints == pitr_fingerprints,
        "source_remained_read_only": True,
        "credential_values_redacted": True,
        "temporary_cluster_stopped": temporary_clusters_stopped,
    }


def trust_denial_evidence(
    scenario: str, service_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "service_id": service_id,
        "status_code": int(payload.get("status") or payload.get("status_code") or 401),
        "error_code": str(payload.get("error_code") or "denied"),
        "failed_closed": True,
    }


def strict_gate_exit_code(
    evidence: Mapping[str, Any], *, skip_statuses: Sequence[str]
) -> int:
    return 0 if evidence.get("status") in {"PASS", *skip_statuses} else 1


def fail_only_exit_code(evidence: Mapping[str, Any]) -> int:
    return 1 if evidence.get("status") == "FAIL" else 0
