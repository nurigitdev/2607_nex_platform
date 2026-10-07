from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from nex_runtime.postgres_resilience import (
    EXPECTED_SERVICE_IDS,
    PostgresResiliencePolicyError,
    load_postgres_resilience_policy,
    policy_public_projection,
    validate_postgres_resilience_policy,
)


POLICY_PATH = Path("deployment/postgres/s145-policy.yaml")


def _document() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def test_canonical_policy_is_strict_and_public_projection_is_value_free() -> None:
    policy = load_postgres_resilience_policy(POLICY_PATH)
    projection = policy_public_projection(policy)
    assert tuple(projection["service_ids"]) == EXPECTED_SERVICE_IDS
    assert projection["database_count"] == 5
    assert projection["high_availability"] is False
    assert projection["automatic_failover"] is False
    assert projection["interval_hours"] == 6
    assert projection["cluster_rto_minutes"] == 60
    assert projection["extension_target_count"] == 2
    assert "password" not in str(projection).lower()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(schema_version="wrong"), "policy_schema_version_invalid"),
        (lambda d: d["topology"].update(mode="ha_cluster"), "topology_mode_invalid"),
        (lambda d: d["topology"].update(high_availability=True), "high_availability_not_admitted"),
        (lambda d: d["topology"].update(automatic_failover=True), "high_availability_not_admitted"),
        (lambda d: d["topology"].update(operator_cutover_required=False), "operator_cutover_required"),
        (lambda d: d["logical_backup"].update(format="plain"), "logical_backup_format_invalid"),
        (lambda d: d["logical_backup"].update(compression="none"), "logical_backup_format_invalid"),
        (lambda d: d["logical_backup"].update(interval_hours=7), "service_recovery_objective_too_weak"),
        (lambda d: d["logical_backup"].update(service_restore_rto_minutes=31), "service_recovery_objective_too_weak"),
        (lambda d: d["logical_backup"].update(retention_restore_points=27), "logical_retention_too_short"),
        (lambda d: d["logical_backup"].update(retention_days=6), "logical_retention_too_short"),
        (lambda d: d["logical_backup"].update(minimum_verified_points=0), "minimum_verified_points_invalid"),
        (lambda d: d["cluster_recovery"].update(method="snapshot"), "cluster_recovery_method_invalid"),
        (lambda d: d["cluster_recovery"].update(libpq_service="bad service"), "cluster_libpq_service_invalid"),
        (lambda d: d["cluster_recovery"].update(wal_archive_root_env="bad-env"), "wal_archive_root_env_invalid"),
        (lambda d: d["cluster_recovery"].update(archive_timeout_seconds=301), "cluster_recovery_objective_too_weak"),
        (lambda d: d["cluster_recovery"].update(cluster_rto_minutes=61), "cluster_recovery_objective_too_weak"),
        (lambda d: d["cluster_recovery"].update(retained_base_generations=1), "base_backup_retention_too_short"),
        (lambda d: d["storage"].update(production_class="local"), "production_storage_not_separate"),
        (lambda d: d["storage"].update(atomic_publish_required=False), "storage_safety_invalid"),
        (lambda d: d["storage"].update(forbid_postgres_data_volume=False), "storage_safety_invalid"),
        (lambda d: d["credentials"].update(transport="url"), "credential_transport_invalid"),
        (lambda d: d["credentials"].update(password_in_process_args=True), "credential_safety_invalid"),
        (lambda d: d["credentials"].update(distinct_backup_role_required=False), "credential_safety_invalid"),
        (lambda d: d["compatibility"].update(pg_dump_major=15), "postgres_major_mismatch"),
        (lambda d: d.update(services=d["services"][:-1]), "service_ownership_incomplete"),
        (lambda d: d["services"][1].update(database_env=d["services"][0]["database_env"]), "backup_target_binding_duplicate"),
        (lambda d: d["services"][1].update(libpq_service=d["services"][0]["libpq_service"]), "backup_target_binding_duplicate"),
    ],
)
def test_policy_rejects_unsafe_mutations(mutate, code: str) -> None:
    document = deepcopy(_document())
    mutate(document)
    with pytest.raises(PostgresResiliencePolicyError, match=code):
        validate_postgres_resilience_policy(document)


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({}, "policy_schema_version_invalid"),
        ({"schema_version": "postgres_resilience_policy.v1"}, "topology_invalid"),
    ],
)
def test_policy_rejects_missing_sections(document: dict, code: str) -> None:
    with pytest.raises(PostgresResiliencePolicyError, match=code):
        validate_postgres_resilience_policy(document)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(services=None), "services_invalid"),
        (lambda d: d.update(services=["invalid"]), "service_target_invalid"),
        (lambda d: d["services"][0].update(required_extensions=[]), "required_extensions_invalid"),
        (lambda d: d["services"][0].update(service_id=""), "service_id_invalid"),
        (lambda d: d["topology"].update(high_availability="false"), "high_availability_invalid"),
    ],
)
def test_policy_rejects_invalid_field_types(mutate, code: str) -> None:
    document = deepcopy(_document())
    mutate(document)
    with pytest.raises(PostgresResiliencePolicyError, match=code):
        validate_postgres_resilience_policy(document)


def test_policy_loader_rejects_missing_and_non_mapping_files(tmp_path: Path) -> None:
    with pytest.raises(PostgresResiliencePolicyError, match="policy_unreadable"):
        load_postgres_resilience_policy(tmp_path / "missing.yaml")
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("[]\n", encoding="utf-8")
    with pytest.raises(PostgresResiliencePolicyError, match="policy_document_invalid"):
        load_postgres_resilience_policy(invalid)
