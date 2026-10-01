from datetime import UTC, datetime

from nex_oa.sessions import build_browser_session_snapshot, build_session_record, refresh_session_for_introspection
from nex_runtime import issue_mock_user_token
import run_oa_secure_session_lifecycle as runner


def _record() -> dict[str, object]:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        issued_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        ttl_seconds=3600,
    )
    return build_session_record(issued.claims)


def test_random_ids_and_idle_lease_are_internal() -> None:
    first = _record()
    second = _record()
    assert first["session_id"] != second["session_id"]
    assert len(str(first["session_id"])) >= 43
    assert first["idle_expires_at"] == "2026-08-12T12:30:00Z"
    public = build_browser_session_snapshot(first)
    assert "last_seen_at" not in public
    assert "idle_expires_at" not in public


def test_refresh_handles_active_revoked_and_absolute_expired_states() -> None:
    record = _record()
    refreshed = refresh_session_for_introspection(
        record, now=datetime(2026, 8, 12, 12, 10, tzinfo=UTC)
    )
    assert refreshed["last_seen_at"] == "2026-08-12T12:10:00Z"
    assert refreshed["idle_expires_at"] == "2026-08-12T12:40:00Z"
    revoked = refresh_session_for_introspection(
        {**record, "status": "REVOKED", "revoked_at": "2026-08-12T12:01:00Z"},
        now=datetime(2026, 8, 12, 12, 10, tzinfo=UTC),
    )
    assert revoked["status"] == "REVOKED"
    expired = refresh_session_for_introspection(
        record, now=datetime(2026, 8, 12, 13, 1, tzinfo=UTC)
    )
    assert expired["status"] == "EXPIRED"


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_secure_session_lifecycle()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.main(["--summary"]) == 0
    assert "checks=7/7" in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_secure_session_lifecycle", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1

