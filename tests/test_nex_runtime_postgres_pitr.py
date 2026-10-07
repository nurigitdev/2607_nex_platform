from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nex_runtime.postgres_pitr import (
    PostgresPitrError,
    build_postgres_pitr_plan,
    pitr_plan_public_projection,
    validate_pitr_cutover,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy


POLICY = load_postgres_resilience_policy(Path("deployment/postgres/s145-policy.yaml"))


def _plan(tmp_path: Path, **overrides):
    values = {
        "policy": POLICY, "recovery_id": "pitr-20261008-001",
        "backup_root": tmp_path / "backup", "pg_basebackup_bin": Path("/usr/bin/pg_basebackup"),
        "service_file": tmp_path / "pg_service.conf", "passfile": tmp_path / ".pgpass",
        "recovery_target_time": datetime(2026, 10, 8, tzinfo=timezone.utc),
        "parent_environ": {"PATH": "/usr/bin", "PGPASSWORD": "secret"},
    }
    values.update(overrides)
    return build_postgres_pitr_plan(**values)


def test_pitr_plan_is_cold_recovery_and_value_free(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    projection = pitr_plan_public_projection(plan)
    assert "--dbname=service=nex-platform-cluster-backup" in plan.basebackup_command
    assert plan.environment["PGCONNECT_TIMEOUT"] == "10"
    assert "PGPASSWORD" not in plan.environment
    assert dict(plan.archive_settings)["archive_mode"] == "on"
    assert projection["recovery_target_action"] == "pause"
    assert projection["operator_cutover_required"] is True
    assert projection["automatic_promotion"] is False
    assert "path" not in str(projection).lower()


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"recovery_id": "bad"}, "recovery_id_invalid"),
        ({"pg_basebackup_bin": Path("pg_basebackup")}, "pg_basebackup_path_not_absolute"),
        ({"service_file": Path("relative")}, "credential_file_path_not_absolute"),
        ({"production": True}, "production_backup_mount_not_verified"),
        ({"production": True, "separate_mount_verified": True, "backup_root": Path("relative")}, "production_backup_mount_not_verified"),
        ({"recovery_target_time": datetime(2026, 1, 1)}, "recovery_target_not_timezone_aware"),
    ],
)
def test_pitr_plan_rejects_unsafe_configuration(tmp_path: Path, overrides: dict, code: str) -> None:
    with pytest.raises(PostgresPitrError, match=code):
        _plan(tmp_path, **overrides)


@pytest.mark.parametrize("failed_key", ["recovery_paused", "timeline_verified", "five_databases_verified", "migration_heads_verified"])
def test_cutover_rejects_incomplete_validation(failed_key: str) -> None:
    values = {"recovery_paused": True, "timeline_verified": True, "five_databases_verified": True, "migration_heads_verified": True, "operator_approved": False}
    values[failed_key] = False
    with pytest.raises(PostgresPitrError, match="pitr_recovery_validation_failed"):
        validate_pitr_cutover(**values)


def test_cutover_remains_paused_until_explicit_approval() -> None:
    values = {"recovery_paused": True, "timeline_verified": True, "five_databases_verified": True, "migration_heads_verified": True}
    assert validate_pitr_cutover(**values, operator_approved=False) == "PAUSED_AWAITING_OPERATOR"
    assert validate_pitr_cutover(**values, operator_approved=True) == "CUTOVER_APPROVED"
