from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression as privacy


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-env-0728@127.0.0.1/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-test-0728@127.0.0.1/nex_ag_test"
        ),
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": "https://notify.invalid/hook/env-0728",
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "notify-env-token-0728",
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": "https://incident.invalid/env-0728",
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": "incident-env-token-0728",
    }


def test_live_provider_privacy_regression_passes() -> None:
    evidence = (
        privacy.run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression()
    )

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == privacy.SCHEMA_VERSION
    assert evidence["slice"] == "0728"
    assert evidence["surface_count"] == 8
    assert all(evidence["checks"].values())
    assert {surface["name"] for surface in evidence["surfaces"]} == {
        "provider_config",
        "notification_request",
        "incident_request",
        "notification_result",
        "incident_result",
        "http_client_result",
        "result_metadata",
        "operations_dashboard_dispatches",
    }
    assert all(surface["redacted"] for surface in evidence["surfaces"])

    summary = privacy.summary_line(evidence)
    assert "ag_operator_review_escalation_dispatch_live_provider_privacy=pass" in (
        summary
    )
    assert "surfaces=8" in summary
    assert "values=True" in summary
    assert "keys=True" in summary
    assert "flags=True" in summary


def test_live_provider_privacy_regression_redacts_protected_env() -> None:
    env = protected_env()

    evidence = (
        privacy.run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression(
            env
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["protected_env"] == {
        key: True for key in privacy.PROTECTED_ENV_KEYS
    }
    for value in env.values():
        assert value not in serialized
    with pytest.raises(ValueError, match="NEX_AG_NOTIFICATION_SERVICE_TOKEN"):
        privacy.assert_evidence_redacted("notify-env-token-0728", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        privacy.assert_evidence_redacted(privacy.RAW_PROVIDER_PAYLOAD, {})


def test_live_provider_privacy_check_detects_values_keys_and_flags() -> None:
    surface = privacy.SurfacePayload(
        "leaky",
        {
            "items": [
                {
                    "raw_provider_payload": privacy.RAW_PROVIDER_PAYLOAD,
                    "redaction": {"tokens_included": True},
                }
            ]
        },
    )

    check = privacy._surface_privacy_check(surface)

    assert check["redacted"] is False
    assert check["leak_labels"] == ["raw_provider_payload"]
    assert check["forbidden_key_paths"] == ["items[0].raw_provider_payload"]
    assert check["unsafe_flag_paths"] == ["items[0].redaction.tokens_included"]


def test_live_provider_privacy_summary_failure_line() -> None:
    summary = privacy.summary_line(
        {
            "status": "FAIL",
            "failure_code": (
                "ag_operator_review_escalation_dispatch_live_provider_privacy_failed"
            ),
        }
    )

    assert "ag_operator_review_escalation_dispatch_live_provider_privacy=fail" in (
        summary
    )
    assert "live_provider_privacy_failed" in summary


def test_live_provider_privacy_main_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py", "--summary"],
    )
    privacy.main()
    assert "live_provider_privacy=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py"],
    )
    privacy.main()
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        privacy,
        "run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression",
        lambda: {
            "status": "FAIL",
            "failure_code": "privacy_failed",
            "checks": {},
            "surface_count": 0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py", "--summary"],
    )
    with pytest.raises(SystemExit):
        privacy.main()


def test_live_provider_privacy_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py", "--summary"],
    )

    runpy.run_path(
        str(
            ROOT
            / "scripts"
            / "smoke"
            / "run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py"
        ),
        run_name="__main__",
    )

    assert "live_provider_privacy=pass" in capsys.readouterr().out
