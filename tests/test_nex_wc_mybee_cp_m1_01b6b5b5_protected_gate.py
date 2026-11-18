from __future__ import annotations

import json
import os

import pytest
import run_mybee_w70_cp_m1_e2e_fx_01b6b5b5_protected_gate as smoke


def test_gate_is_explicit_and_rejects_non_test_database_targets() -> None:
    skipped = smoke.run_protected_gate({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_protected_gate({smoke.SMOKE_ENV: "1"})
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "database_url_missing"

    wrong = smoke.run_protected_gate(
        {
            smoke.SMOKE_ENV: "1",
            smoke.WC_DATABASE_ENV: "postgresql://nex_wc_user:secret@db/nex_wc_dev",
            smoke.AE_DATABASE_ENV: "postgresql://nex_ae_user:secret@db/nex_ae_test",
            smoke.OA_DATABASE_ENV: "postgresql://nex_oa_user:secret@db/nex_oa_test",
        }
    )
    assert wrong["status"] == "FAIL"
    assert wrong["failure_code"] == "target_not_allowed"
    assert "nex_wc_user:secret" not in json.dumps(wrong)


def test_gate_summary_reports_checks_handoffs_and_zero_residue() -> None:
    line = smoke.summary_line(
        {
            "status": "PASS",
            "checks": {"a": True, "b": True},
            "row_counts": {"assignment": 1, "handoff_inbox": 1},
            "cleanup_counts": {
                "wc_remaining": 0,
                "ae_remaining": 0,
                "oa_remaining": 0,
            },
        }
    )
    assert line == (
        "mybee_w70_01b6b5b5_gate=pass checks=2/2 assignments=1 "
        "handoffs=1 remaining=0"
    )


def test_target_guard_and_failure_redaction_are_fail_closed() -> None:
    url = "postgresql+psycopg://nex_wc_user:secret@127.0.0.1/nex_wc_test"
    assert smoke._target_url_allowed(url, "nex_wc_user", "nex_wc_test") is True
    assert smoke._target_url_allowed(url, "nex_wc_user", "nex_wc_dev") is False
    assert smoke._target_url_allowed("sqlite://", "nex_wc_user", "nex_wc_test") is False
    redacted = smoke._redact_detail(f"failed to connect to {url}", database_urls=(url,))
    assert "secret" not in redacted
    assert "***" in redacted


def test_bridge_rejects_unadmitted_hosts_without_network_contact() -> None:
    bridge = smoke._MultiAppUrlOpen({})

    class _Request:
        full_url = "http://unadmitted.local/path"
        data = None

        @staticmethod
        def get_method() -> str:
            return "GET"

        @staticmethod
        def header_items():
            return []

    with pytest.raises(OSError, match="not admitted"):
        bridge(_Request(), timeout=1.0)
    assert bridge.attempts == []


@pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in (
            smoke.WC_DATABASE_ENV,
            smoke.AE_DATABASE_ENV,
            smoke.OA_DATABASE_ENV,
        )
    ),
    reason="actual WC/AE/OA PostgreSQL URLs are required",
)
def test_actual_protected_postgres_gate() -> None:
    evidence = smoke.run_protected_gate(
        {
            **os.environ,
            smoke.SMOKE_ENV: "1",
        }
    )
    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["remote_provider_contacted"] is False
    assert all(evidence["checks"].values())
