from __future__ import annotations

from pathlib import Path

import run_platform_oa_ae_trust_path_audit as audit


def test_repository_oa_ae_trust_path_audit_passes_and_exposes_activation_gap() -> None:
    result = audit.run_platform_oa_ae_trust_path_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["findings"] == {
        "oa_internal_route_count": 4,
        "ae_facade_route_count": 3,
        "default_ae_auth_session_mode": "mock",
        "default_service_token_rollout_profile": "TEST_MOCK",
        "local_cookie_secure": False,
        "environment_example_materializes_oa_activation": False,
        "raw_browser_token_exposed": False,
        "browser_service_token_exposed": False,
    }
    assert result["decision"]["oa_is_identity_authority"] is True
    assert result["decision"]["production_trust_is_active_by_default"] is False
    assert result["decision"]["next_slice"] == "1306"


def test_audit_fails_closed_for_missing_repository_evidence(tmp_path: Path) -> None:
    result = audit.run_platform_oa_ae_trust_path_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["issues"]) == len(result["checks"])
    assert all(value is False for value in result["checks"].values())


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "oa_internal_route_count": 4,
            "ae_facade_route_count": 3,
            "default_ae_auth_session_mode": "mock",
            "default_service_token_rollout_profile": "TEST_MOCK",
            "environment_example_materializes_oa_activation": False,
        },
        "decision": {"next_slice": "1306"},
    }
    assert audit.summary_line(passing) == (
        "platform_oa_ae_trust_path=pass oa_routes=4 ae_routes=3 "
        "auth_default=mock token_default=TEST_MOCK "
        "profile_materialized=False next=1306"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1, 2]}) == (
        "platform_oa_ae_trust_path=fail issues=2"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1306"},
    }
    monkeypatch.setattr(audit, "run_platform_oa_ae_trust_path_audit", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "trust_path=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_platform_oa_ae_trust_path_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
