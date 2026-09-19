from __future__ import annotations

import json

import pytest

import run_ag_recovery_notification_live_loopback_smoke as smoke


def test_live_loopback_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_recovery_notification_live_loopback_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "skipped" in smoke.summary_line(evidence)


def test_live_loopback_smoke_executes_full_recovery_path() -> None:
    evidence = smoke.run_ag_recovery_notification_live_loopback_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["slice"] == "0857"
    assert evidence["transport"] == "local_loopback_http_server"
    assert evidence["delivery"] == {
        "channel_type": "NOTIFICATION",
        "provider_profile": "notification-webhook-default",
        "dispatch_status": "SUCCEEDED",
        "execution_status": "COMPLETED",
        "provider_invocation_performed": True,
    }
    assert evidence["projection"]["provider_mode"] == "live_http"
    assert evidence["projection"]["http_status_code"] == 202
    assert evidence["projection"]["provider_result_hash_present"] is True
    assert evidence["projection"]["response_body_hash_present"] is True
    assert evidence["loopback"]["request_count"] == 1
    assert evidence["loopback"]["authorization_header_seen"] is True
    assert evidence["loopback"]["safe_payload_present"] is True
    assert evidence["loopback"]["request_hash_present"] is True
    assert all(evidence["checks"].values())
    assert not any(evidence["redaction"].values())
    serialized = json.dumps(evidence)
    assert smoke.LOOPBACK_TOKEN not in serialized
    assert "/recovery-notification" not in serialized


def test_live_loopback_server_empty_observations() -> None:
    server = smoke._RecoveryNotificationLoopbackServer()
    server.start()
    try:
        assert server.observations() == {
            "request_count": 0,
            "method_seen": None,
            "path_hash": None,
            "authorization_header_seen": False,
            "provider_category": None,
            "safe_payload_present": False,
            "request_hash_present": False,
        }
    finally:
        server.stop()


def test_live_loopback_redaction_and_summary_failure() -> None:
    with pytest.raises(AssertionError):
        smoke._assert_evidence_redacted(
            {"endpoint": "http://127.0.0.1:18557/recovery-notification"},
            "http://127.0.0.1:18557/recovery-notification",
        )

    summary = smoke.summary_line(
        {
            "status": "FAIL",
            "transport": "local_loopback_http_server",
            "loopback": {"request_count": 0},
            "delivery": {"dispatch_status": "PENDING"},
        }
    )
    assert "live_loopback_smoke=fail" in summary
    assert "requests=0" in summary


def test_live_loopback_main_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(smoke.SMOKE_ENV, "1")
    assert smoke.main(["--summary"]) == 0
    assert "live_loopback_smoke=pass" in capsys.readouterr().out

    monkeypatch.delenv(smoke.SMOKE_ENV, raising=False)
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_recovery_notification_live_loopback_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "live_loopback_smoke=fail" in capsys.readouterr().out
