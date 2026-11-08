from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

from operational_recovery_harness import (
    backup_catalog_verified,
    fail_only_exit_code,
    object_cleanup_evidence,
    object_version_delete_batch,
    recovery_acceptance_checks,
    recovery_target_coverage_valid,
    strict_gate_exit_code,
    trust_denial_evidence,
)


def test_object_version_delete_batch_normalizes_versions_and_markers() -> None:
    assert object_version_delete_batch(
        {
            "Versions": [{"Key": "a", "VersionId": "v1"}],
            "DeleteMarkers": [{"Key": "b", "VersionId": "v2"}],
        }
    ) == [
        {"Key": "a", "VersionId": "v1"},
        {"Key": "b", "VersionId": "v2"},
    ]
    assert object_version_delete_batch({}) == []


@pytest.mark.parametrize(
    "page",
    (
        {"Versions": "not-a-sequence"},
        {"Versions": ["not-an-object"]},
        {"Versions": [{"VersionId": "v1"}]},
        {"Versions": [{"Key": "a"}]},
    ),
)
def test_object_version_delete_batch_rejects_malformed_inventory(page) -> None:
    with pytest.raises((TypeError, ValueError)):
        object_version_delete_batch(page)


def test_object_cleanup_evidence_is_bounded() -> None:
    assert object_cleanup_evidence(bucket_count=2, deleted_version_count=4) == {
        "status": "PASS",
        "bucket_count": 2,
        "deleted_version_count": 4,
        "named_volume_removed": True,
    }


def test_recovery_target_and_catalog_admission_fail_closed() -> None:
    assert recovery_target_coverage_valid(("oa", "ae"), ("ae", "oa"))
    assert not recovery_target_coverage_valid(("oa",), ("oa", "ae"))

    verified = SimpleNamespace(
        issues=(), partials=(), entries=(SimpleNamespace(state="VERIFIED"),)
    )
    assert backup_catalog_verified(verified)
    assert not backup_catalog_verified(
        SimpleNamespace(
            issues=("bad",),
            partials=(),
            entries=(SimpleNamespace(state="VERIFIED"),),
        )
    )
    assert not backup_catalog_verified(
        SimpleNamespace(issues=(), partials=("partial",), entries=())
    )
    assert not backup_catalog_verified(
        SimpleNamespace(
            issues=(), partials=(), entries=(SimpleNamespace(state="PENDING"),)
        )
    )
    assert not backup_catalog_verified(SimpleNamespace())


def test_recovery_acceptance_checks_detect_fingerprint_and_cutover_drift() -> None:
    source = {str(index): {"digest": index} for index in range(5)}
    checks = recovery_acceptance_checks(
        source_fingerprints=source,
        restored_fingerprints=dict(source),
        pitr_fingerprints=dict(source),
        physical_basebackup_exists=True,
        wal_segment_count=1,
        cutover="PAUSED_AWAITING_OPERATOR",
        temporary_clusters_stopped=True,
    )
    assert all(checks.values())

    rejected = recovery_acceptance_checks(
        source_fingerprints={"only": {}},
        restored_fingerprints={},
        pitr_fingerprints={},
        physical_basebackup_exists=False,
        wal_segment_count=0,
        cutover="PROMOTED",
        temporary_clusters_stopped=False,
    )
    assert rejected["actual_five_test_databases"] is False
    assert rejected["logical_backup_restore"] is False
    assert rejected["wal_archive_replay"] is False
    assert rejected["pitr_paused_without_promotion"] is False
    assert rejected["temporary_cluster_stopped"] is False


def test_trust_denial_and_exit_codes_are_deterministic() -> None:
    assert trust_denial_evidence("expired", "nex-cx", {}) == {
        "scenario": "expired",
        "service_id": "nex-cx",
        "status_code": 401,
        "error_code": "denied",
        "failed_closed": True,
    }
    assert (
        trust_denial_evidence(
            "revoked", "nex-cx", {"status": 403, "error_code": "inactive"}
        )["status_code"]
        == 403
    )

    assert strict_gate_exit_code({"status": "PASS"}, skip_statuses=("SKIP",)) == 0
    assert strict_gate_exit_code({"status": "SKIP"}, skip_statuses=("SKIP",)) == 0
    assert strict_gate_exit_code({"status": "FAIL"}, skip_statuses=("SKIP",)) == 1
    assert fail_only_exit_code({"status": "SKIPPED"}) == 0
    assert fail_only_exit_code({"status": "FAIL"}) == 1
