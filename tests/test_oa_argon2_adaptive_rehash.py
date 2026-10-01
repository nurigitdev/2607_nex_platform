import pytest

from nex_oa.credentials import (
    ARGON2ID_PASSWORD_HASH_ALGORITHM,
    InMemoryOaCredentialRegistry,
    OaCredentialError,
    PASSWORD_HASH_ALGORITHM,
    hash_password,
    password_hash_algorithm,
    password_hash_needs_rehash,
    verify_password,
)
import run_oa_argon2_adaptive_rehash as runner


def test_argon2_is_default_and_pbkdf2_remains_compatible() -> None:
    modern = hash_password("Nuri1004!")
    legacy = hash_password("Nuri1004!", salt=b"1234567890123456", iterations=10)
    assert password_hash_algorithm(modern) == ARGON2ID_PASSWORD_HASH_ALGORITHM
    assert password_hash_algorithm(legacy) == PASSWORD_HASH_ALGORITHM
    assert verify_password("Nuri1004!", password_hash=modern)
    assert verify_password("Nuri1004!", password_hash=legacy)
    assert password_hash_needs_rehash(modern) is False
    assert password_hash_needs_rehash(legacy) is True


def test_successful_login_upgrades_legacy_hash_without_password_timestamp_change() -> None:
    registry = InMemoryOaCredentialRegistry()
    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password_hash": hash_password(
                "Nuri1004!", salt=b"1234567890123456", iterations=10
            ),
        }
    )
    record = registry.credentials[("tenant-a", "emp-001")]
    changed_at = record["password_changed_at"]
    registry.verify_credential(
        {"tenant_id": "tenant-a", "employee_id": "EMP-001", "password": "Nuri1004!"}
    )
    assert record["password_hash_algorithm"] == ARGON2ID_PASSWORD_HASH_ALGORITHM
    assert record["password_changed_at"] == changed_at


def test_argon2_mismatch_and_malformed_hash_fail_closed() -> None:
    password_hash = hash_password("Nuri1004!")
    with pytest.raises(OaCredentialError) as mismatch:
        verify_password("Wrong1004!", password_hash=password_hash)
    assert mismatch.value.error_code == "oa.credential_not_verified"
    with pytest.raises(OaCredentialError) as malformed:
        password_hash_algorithm("$argon2id$invalid")
    assert malformed.value.error_code == "oa.password_hash_invalid"


def test_runner_and_cli(monkeypatch, capsys) -> None:
    result = runner.run_oa_argon2_adaptive_rehash()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert runner.main(["--summary"]) == 0
    assert "checks=7/7" in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_argon2_adaptive_rehash", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1

