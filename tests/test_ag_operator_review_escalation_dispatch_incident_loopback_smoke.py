from __future__ import annotations

import os

import pytest

import run_ag_operator_review_escalation_dispatch_incident_loopback_smoke as smoke


def test_incident_loopback_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_incident_loopback_smoke(
        {}
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "skipped" in smoke.summary_line(evidence)


def test_incident_loopback_smoke_executes_local_server() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_incident_loopback_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["slice"] == "0736"
    assert evidence["transport"] == "local_loopback_http_server"
    assert evidence["provider_category"] == "external_incident"
    assert evidence["request_plan"]["endpoint_hint"].startswith(
        "http://127.0.0.1:"
    )
    assert evidence["request_plan"]["endpoint_hint"].endswith("/<redacted>")
    assert evidence["request_plan"]["authorization_header_configured"] is True
    assert evidence["request_plan"]["withheld_header_names"] == ["Authorization"]
    assert evidence["result"]["execution_status"] == "SUCCEEDED"
    assert evidence["result"]["provider_mode"] == "live_http"
    assert evidence["result"]["http_status_code"] == 201
    assert evidence["result"]["response_body_hash"]
    assert evidence["observations"]["request_count"] == 1
    assert evidence["observations"]["authorization_header_seen"] is True
    assert evidence["observations"]["body_provider_category"] == "external_incident"
    assert evidence["observations"]["body_request_hash_matches"] is True
    assert evidence["observations"]["incident_payload_hash_matches"] is True
    assert evidence["observations"]["target_id_hashed"] is True
    assert all(evidence["checks"].values())

    serialized = str(evidence)
    assert smoke.LOOPBACK_TOKEN not in serialized
    assert smoke.TARGET_ID not in serialized
    assert "/dispatch/incident" not in serialized
    assert "status_code=201" in smoke.summary_line(evidence)


def test_incident_loopback_smoke_main_summary(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(smoke.SMOKE_ENV, "1")

    assert smoke.main(["--summary"]) == 0

    output = capsys.readouterr().out
    assert "incident_loopback_smoke=pass" in output
    assert "requests=1" in output


def test_incident_loopback_smoke_main_json_skip(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv(smoke.SMOKE_ENV, raising=False)

    assert smoke.main([]) == 0

    output = capsys.readouterr().out
    assert '"status": "SKIPPED"' in output
    assert smoke.SMOKE_ENV in output
    assert smoke.SMOKE_ENV not in os.environ


def test_incident_loopback_smoke_redaction_and_failure_paths(
    monkeypatch,
    capsys,
) -> None:
    with pytest.raises(AssertionError):
        smoke._assert_evidence_redacted(
            {"leak": f"http://127.0.0.1:12345/dispatch/incident"},
            12345,
        )

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_incident_loopback_smoke",
        lambda: {
            "status": "FAIL",
            "transport": "local_loopback_http_server",
            "observations": {"request_count": 0},
            "result": {"http_status_code": None},
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "incident_loopback_smoke=fail" in capsys.readouterr().out
