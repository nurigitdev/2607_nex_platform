from datetime import UTC, datetime, timedelta

import pytest

from nex_oa.credentials import (
    InMemoryOaCredentialRegistry,
    MAX_FAILED_LOGIN_ATTEMPTS,
    OaCredentialError,
    build_failed_login_state,
    build_successful_login_state,
)
import run_oa_atomic_login_lockout as runner


def _registry() -> InMemoryOaCredentialRegistry:
    registry = InMemoryOaCredentialRegistry()
    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        }
    )
    return registry


def test_failed_logins_lock_and_success_after_expiry_resets_state() -> None:
    registry = _registry()
    payload = {"tenant_id": "tenant-a", "employee_id": "EMP-001"}
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        with pytest.raises(OaCredentialError) as failed:
            registry.verify_credential({**payload, "password": "Wrong1004!"})
        assert failed.value.error_code == "oa.credential_not_verified"
    record = registry.credentials[("tenant-a", "emp-001")]
    assert record["status"] == "LOCKED"
    with pytest.raises(OaCredentialError) as locked:
        registry.verify_credential({**payload, "password": "Nuri1004!"})
    assert locked.value.error_code == "oa.credential_not_verified"
    record["locked_at"] = (
        datetime.now(UTC) - timedelta(seconds=901)
    ).isoformat().replace("+00:00", "Z")
    registry.verify_credential({**payload, "password": "Nuri1004!"})
    assert record["status"] == "ACTIVE"
    assert record["failed_attempt_count"] == 0
    assert record["locked_at"] is None


def test_lockout_state_helpers_cover_threshold_and_noop_success() -> None:
    record = {"status": "ACTIVE", "failed_attempt_count": 3, "locked_at": None}
    fourth = build_failed_login_state(record)
    fifth = build_failed_login_state(fourth)
    assert fourth["status"] == "ACTIVE"
    assert fifth["status"] == "LOCKED"
    assert fifth["locked_at"] is not None
    reset = build_successful_login_state(fifth)
    assert reset["status"] == "ACTIVE"
    assert reset["failed_attempt_count"] == 0
    clean = {**reset, "updated_at": "stable"}
    assert build_successful_login_state(clean) == clean


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_atomic_login_lockout()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.main(["--summary"]) == 0
    assert "checks=6/6" in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_atomic_login_lockout", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1

