from __future__ import annotations

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression as privacy


def test_dispatch_daemon_api_privacy_regression_passes() -> None:
    evidence = (
        privacy.run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression()
    )

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == privacy.SCHEMA_VERSION
    assert evidence["slice"] == "0755"
    assert evidence["surface_count"] == 3
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    assert all(not surface["forbidden_key_paths"] for surface in evidence["surfaces"])
    summary = privacy.summary_line(evidence)
    assert "daemon_api_privacy_regression=pass" in summary
    assert "raw_fields_absent=True" in summary


def test_dispatch_daemon_api_privacy_regression_detects_forbidden_values() -> None:
    assert privacy._redaction_flags_safe({"redaction": {"tokens_included": False}})
    assert not privacy._redaction_flags_safe(
        {"redaction": {"tokens_included": True}}
    )

    with pytest.raises(ValueError):
        privacy._assert_no_forbidden_values(privacy.RAW_PROVIDER_PAYLOAD)


def test_dispatch_daemon_api_privacy_regression_detects_forbidden_keys() -> None:
    payload = {
        "safe": [
            {
                "nested": {
                    "provider_payload": "raw",
                    "redaction": {"provider_payloads_included": False},
                }
            }
        ]
    }

    paths = privacy._forbidden_key_paths(payload, privacy.FORBIDDEN_KEYS)

    assert paths == ["safe[0].nested.provider_payload"]
    assert privacy._contains_forbidden_keys(payload, privacy.FORBIDDEN_KEYS)
    assert not privacy._contains_forbidden_keys(
        {"redaction": {"provider_payloads_included": False}},
        privacy.FORBIDDEN_KEYS,
    )


def test_dispatch_daemon_api_privacy_regression_summary_and_main(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        privacy,
        "run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression",
        lambda: {
            "audit_schema_version": privacy.SCHEMA_VERSION,
            "status": "PASS",
            "surface_count": 3,
            "checks": {
                "no_forbidden_values": True,
                "raw_fields_absent": True,
            },
        },
    )

    assert privacy.main(["--summary"]) == 0
    assert "daemon_api_privacy_regression=pass" in capsys.readouterr().out

    assert privacy.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    assert privacy.summary_line(
        {"status": "FAIL", "failure_code": "checks_failed"}
    ).endswith("failure=checks_failed")

    monkeypatch.setattr(
        privacy,
        "run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert privacy.main(["--summary"]) == 1
