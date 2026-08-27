from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_web_repaired_response_decision_postgres_smoke as smoke


def web_contents(overrides: dict[str, str] | None = None) -> dict[str, str]:
    contents = {
        label: "\n".join(anchors)
        for label, anchors in smoke.WEB_BOUNDARY_ANCHORS.items()
    }
    contents.update(overrides or {})
    return contents


def api_pass_evidence(raw_url: str = "postgresql://nex_ae_user:secret@host/db") -> dict[str, Any]:
    return {
        "smoke_schema_version": "ae_repaired_response_decision_postgres_smoke.v1",
        "status": "PASS",
        "service_id": smoke.SERVICE_ID,
        "profile": smoke.DEFAULT_PROFILE,
        "database_env": "NEX_AE_TEST_DATABASE_URL",
        "redacted_database_url": raw_url.replace("secret", "***"),
        "migration": {
            "planned": ["0387_ae_repaired_response_decision_persistence"],
            "applied": [],
            "skipped": ["0387_ae_repaired_response_decision_persistence"],
        },
        "request_id": "request-001",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "repaired_response_handoff_id": "handoff-001",
        "repaired_response_decision_id": "decision-001",
        "decision_request_id": "decision-request-001",
        "db_observations": {
            "row_count": 1,
            "handoff_row_count": 1,
            "decision_schema_version": "ae_repaired_response_decision.v1",
            "decision_action": "accept_repair",
        },
        "checks": {
            "route_created_decision": True,
            "route_listed_decision": True,
            "route_loaded_decision": True,
            "store_loaded_decision": True,
            "store_list_scoped": True,
            "row_count": True,
            "raw_sensitive_absent": True,
        },
        "cleanup": {"deleted_decisions": 1, "deleted_handoffs": 1},
    }


def test_ae_web_repaired_decision_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ae_web_repaired_response_decision_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_web_repaired_decision_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_web_repaired_response_decision_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_web_repaired_decision_boundary_reports_all_anchors() -> None:
    boundary = smoke.inspect_ae_web_repaired_decision_boundary(web_contents())

    assert boundary["ok"] is True
    assert boundary["files_checked"] == len(smoke.WEB_BOUNDARY_FILES)
    assert boundary["anchors_present"] == boundary["anchors_required"]
    assert boundary["missing"] == []


def test_ae_web_repaired_decision_boundary_reports_missing_anchor() -> None:
    boundary = smoke.inspect_ae_web_repaired_decision_boundary(
        web_contents({"main": "submitRepairedResponseDecision"})
    )

    assert boundary["ok"] is False
    assert "main:buildRepairedResponseDecisionRequest" in boundary["missing"]
    assert any(item["label"] == "main" and item["missing"] for item in boundary["files"])


def test_ae_web_repaired_decision_postgres_smoke_fails_for_web_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_decision_boundary",
        lambda: {
            "ok": False,
            "files_checked": 1,
            "anchors_present": 0,
            "anchors_required": 1,
            "missing": ["main:missing"],
            "files": [],
        },
    )

    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "web_boundary_invalid"
    assert evidence["web_boundary"]["missing"] == ["main:missing"]


def test_ae_web_repaired_decision_postgres_smoke_delegates_to_api_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_url = "postgresql://nex_ae_user:secret@host/nex_ae_test"
    delegated_envs: list[dict[str, str]] = []
    inspect_boundary = smoke.inspect_ae_web_repaired_decision_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_decision_boundary",
        lambda: inspect_boundary(web_contents()),
    )

    def fake_api_smoke(environ: dict[str, str]) -> dict[str, Any]:
        delegated_envs.append(environ)
        return api_pass_evidence(raw_url)

    monkeypatch.setattr(
        smoke.api_smoke,
        "run_ae_repaired_response_decision_postgres_smoke",
        fake_api_smoke,
    )

    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": raw_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["web_boundary"]["ok"] is True
    assert evidence["api_decision"]["status"] == "PASS"
    assert evidence["checks"] == {key: True for key in evidence["checks"]}
    assert raw_url not in str(evidence)
    assert delegated_envs[0][smoke.api_smoke.SMOKE_ENV] == "1"
    assert delegated_envs[0][smoke.api_smoke.SMOKE_PROFILE_ENV] == smoke.DEFAULT_PROFILE
    assert smoke.summary_line(evidence).startswith(
        "ae_web_repaired_response_decision_postgres_smoke=pass"
    )


def test_ae_web_repaired_decision_postgres_smoke_reports_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect_boundary = smoke.inspect_ae_web_repaired_decision_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_decision_boundary",
        lambda: inspect_boundary(web_contents()),
    )
    monkeypatch.setattr(
        smoke.api_smoke,
        "run_ae_repaired_response_decision_postgres_smoke",
        lambda environ: {
            "smoke_schema_version": "ae_repaired_response_decision_postgres_smoke.v1",
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "configuration_invalid",
        },
    )

    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "api_decision_smoke_failed"
    assert evidence["api_status"] == "FAIL"
    assert evidence["api_failure_code"] == "configuration_invalid"


def test_ae_web_repaired_decision_postgres_smoke_reports_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_api_evidence = api_pass_evidence()
    bad_api_evidence["cleanup"] = {"deleted_decisions": 0, "deleted_handoffs": 1}
    inspect_boundary = smoke.inspect_ae_web_repaired_decision_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_decision_boundary",
        lambda: inspect_boundary(web_contents()),
    )
    monkeypatch.setattr(
        smoke.api_smoke,
        "run_ae_repaired_response_decision_postgres_smoke",
        lambda environ: bad_api_evidence,
    )

    evidence = smoke.run_ae_web_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "evidence_checks_failed"
    assert evidence["detail"] == "api_cleanup"


def test_ae_web_repaired_decision_redaction_guard_rejects_raw_url_and_password() -> None:
    raw_url = "postgresql://nex_ae_user:secret@host/nex_ae_test"

    with pytest.raises(ValueError, match="raw database URL"):
        smoke.assert_smoke_evidence_redacted(
            f"unsafe {raw_url}",
            {"NEX_AE_TEST_DATABASE_URL": raw_url},
        )
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted(
            "unsafe nuri1004",
            {"NEX_AE_TEST_DATABASE_URL": raw_url},
        )


def test_ae_web_repaired_decision_safe_api_failure_detail() -> None:
    assert smoke._safe_api_failure_detail({"status": "FAIL"}) == (
        "api_status=FAIL api_failure_code=unknown"
    )


def test_ae_web_repaired_decision_relative_path_handles_external_path() -> None:
    assert smoke._relative_path(smoke.ROOT / "apps" / "nex-ae-web") == (
        "apps/nex-ae-web"
    )
    assert smoke._relative_path(smoke.ROOT.parent / "external") == (
        str(smoke.ROOT.parent / "external")
    )


def test_ae_web_repaired_decision_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_repaired_response_decision_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_web_repaired_response_decision_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_web_repaired_response_decision_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "execution_failed",
        },
    )

    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_summarize_api_decision_evidence_filters_known_checks() -> None:
    evidence = api_pass_evidence()
    evidence["checks"]["extra"] = True

    summary = smoke.summarize_api_decision_evidence(evidence)

    assert summary == {
        "smoke_schema_version": "ae_repaired_response_decision_postgres_smoke.v1",
        "status": "PASS",
        "migration": evidence["migration"],
        "checks": {
            name: True for name in smoke.API_CHECKS_REPORTED
        },
        "request_id": "request-001",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "decision_request_id": "decision-request-001",
    }


def test_failure_helper_merges_extra_fields() -> None:
    evidence = smoke._failure(
        "boom",
        "bad",
        profile="test",
        extra=SimpleNamespace(value="context"),
    )

    assert evidence["failure_code"] == "boom"
    assert evidence["extra"].value == "context"
