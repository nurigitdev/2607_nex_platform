from __future__ import annotations

import json

import run_oa_signed_token_failure_audit as smoke


def test_failure_audit_smoke_passes() -> None:
    result = smoke.run_oa_signed_token_failure_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "scenario_count": 4,
        "event_count": 4,
        "service_auth_failure_count": 2,
        "token_validation_failure_count": 2,
        "raw_material_exposure_count": 0,
    }
    assert result["next_slice"] == "1294"


def test_failure_events_and_operations_are_bounded() -> None:
    result = smoke.run_oa_signed_token_failure_audit()

    assert result["event_types"] == [
        "SERVICE_AUTH_FAILED",
        "SERVICE_AUTH_FAILED",
        "TOKEN_VALIDATION_FAILED",
        "TOKEN_VALIDATION_FAILED",
    ]
    assert result["operations"] == [
        "service_token_exchange",
        "token_introspection_authorization",
        "token_introspection",
        "token_revocation",
    ]


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_signed_token_failure_audit()
    assert smoke.summary_line(passing) == (
        "oa_signed_token_failure_audit=pass scenarios=4 events=4 "
        "service_auth=2 token_validation=2 exposure=0 next=1294"
    )
    monkeypatch.setattr(
        smoke, "run_oa_signed_token_failure_audit", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "next=1294" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        smoke, "run_oa_signed_token_failure_audit", lambda: failing
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
