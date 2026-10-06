from __future__ import annotations

from pathlib import Path

import run_platform_production_configuration_audit as audit


def test_repository_audit_freezes_production_configuration_gaps() -> None:
    result = audit.run_platform_production_configuration_audit()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "required_environment_count": 25,
        "database_environment_count": 5,
        "service_endpoint_count": 6,
        "signed_trust_environment_count": 8,
        "live_provider_environment_count": 6,
        "config_gap_count": 10,
    }
    assert len(result["config_gaps"]) == 10
    assert all(item["state"] == "NOT_ADMITTED" for item in result["config_gaps"])
    assert result["decision"] == {
        "environment_values_are_control_evidence": False,
        "production_admission_complete": False,
        "production_connection_required": False,
        "next_slice": "1406",
    }


def test_empty_repository_fails_source_and_documentation_checks(
    tmp_path: Path,
) -> None:
    result = audit.run_platform_production_configuration_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == [
        "all_gap_evidence_present",
        "all_gaps_documented_owned_targeted",
    ]
    assert result["decision"]["next_slice"] == "blocked"


def test_profile_rejected_covers_accept_and_reject_paths() -> None:
    required_names = (
        *audit.DATABASE_ENV_NAMES,
        *audit.SERVICE_ENDPOINT_ENV_NAMES,
        *audit.SIGNED_TRUST_ENV_NAMES,
        *audit.LIVE_PROVIDER_ENV_NAMES,
    )
    valid = {name: "configured-value" for name in required_names}
    valid.update(audit.runtime_profile_environment_overlay("production"))

    assert audit._profile_rejected(valid) is False
    valid[required_names[0]] = "changeme"
    assert audit._profile_rejected(valid) is True


def test_profile_evidence_detects_resolver_that_accepts_missing_environment(
    monkeypatch,
) -> None:
    real_resolver = audit.resolve_runtime_profile
    required_names = (
        *audit.DATABASE_ENV_NAMES,
        *audit.SERVICE_ENDPOINT_ENV_NAMES,
        *audit.SIGNED_TRUST_ENV_NAMES,
        *audit.LIVE_PROVIDER_ENV_NAMES,
    )
    valid = {name: "configured-value" for name in required_names}
    valid.update(audit.runtime_profile_environment_overlay("production"))
    valid_resolution = real_resolver("production", environ=valid)

    def permissive_resolver(profile, *, environ):
        if environ == {}:
            return valid_resolution
        return real_resolver(profile, environ=environ)

    monkeypatch.setattr(audit, "resolve_runtime_profile", permissive_resolver)
    assert audit._production_profile_evidence()["missing_error_count"] == 0


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert audit._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("present", encoding="utf-8")
    assert audit._read_text(source) == "present"

    passing = audit.run_platform_production_configuration_audit()
    assert audit.summary_line(passing) == (
        "platform_production_configuration_audit=pass required=25 db=5 "
        "endpoints=6 trust=8 providers=6 gaps=10 next=1406"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert audit.summary_line(failing) == (
        "platform_production_configuration_audit=fail issues=1"
    )

    monkeypatch.setattr(
        audit, "run_platform_production_configuration_audit", lambda: passing
    )
    assert audit.main(["--summary"]) == 0
    assert "audit=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_production_configuration_audit",
        lambda: failing,
    )
    assert audit.main([]) == 1
