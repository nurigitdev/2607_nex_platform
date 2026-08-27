from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_web_repaired_response_review_diagnostics_postgres_smoke as smoke


def web_contents(overrides: dict[str, str] | None = None) -> dict[str, str]:
    contents = {
        label: "\n".join(anchors)
        for label, anchors in smoke.WEB_DIAGNOSTICS_ANCHORS.items()
    }
    contents.update(overrides or {})
    return contents


def decision_pass_evidence(
    raw_url: str = "postgresql://nex_ae_user:secret@host/nex_ae_test",
) -> dict[str, Any]:
    return {
        "smoke_schema_version": (
            "ae_web_repaired_response_decision_postgres_smoke.v1"
        ),
        "status": "PASS",
        "service_id": smoke.SERVICE_ID,
        "profile": smoke.DEFAULT_PROFILE,
        "database_env": "NEX_AE_TEST_DATABASE_URL",
        "redacted_database_url": raw_url.replace("secret", "***"),
        "web_boundary": {
            "ok": True,
            "anchors_present": 24,
            "anchors_required": 24,
        },
        "api_decision": {"status": "PASS"},
        "repaired_response_handoff_id": "handoff-001",
        "repaired_response_decision_id": "decision-001",
        "db_observations": {
            "row_count": 1,
            "handoff_row_count": 1,
            "decision_schema_version": "ae_repaired_response_decision.v1",
            "decision_action": "accept_repair",
        },
        "checks": {
            "web_boundary": True,
            "api_route_created_decision": True,
            "api_store_loaded_decision": True,
            "api_row_count": True,
            "api_cleanup": True,
        },
        "cleanup": {"deleted_decisions": 1, "deleted_handoffs": 1},
    }


def test_review_diagnostics_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_review_diagnostics_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_review_diagnostics_boundary_reports_all_anchors() -> None:
    boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary(
        web_contents()
    )

    assert boundary["ok"] is True
    assert boundary["files_checked"] == len(smoke.WEB_DIAGNOSTICS_FILES)
    assert boundary["anchors_present"] == boundary["anchors_required"]
    assert boundary["missing"] == []


def test_review_diagnostics_boundary_reads_runtime_files() -> None:
    boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary()

    assert boundary["ok"] is True
    assert boundary["files_checked"] == len(smoke.WEB_DIAGNOSTICS_FILES)
    assert boundary["anchors_present"] == boundary["anchors_required"]


def test_review_diagnostics_boundary_reports_missing_anchor() -> None:
    boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary(
        web_contents({"main": "buildWorkspaceRepairedResponseReviewReadModel"})
    )

    assert boundary["ok"] is False
    assert "main:repairedResponseReviewReadModel:" in boundary["missing"]
    assert any(item["label"] == "main" and item["missing"] for item in boundary["files"])


def test_review_diagnostics_smoke_fails_for_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_review_diagnostics_boundary",
        lambda: {
            "ok": False,
            "files_checked": 1,
            "anchors_present": 0,
            "anchors_required": 1,
            "missing": ["main:missing"],
            "files": [],
        },
    )

    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "diagnostics_boundary_invalid"
    assert evidence["diagnostics_boundary"]["missing"] == ["main:missing"]


def test_review_diagnostics_smoke_delegates_to_decision_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_url = "postgresql://nex_ae_user:secret@host/nex_ae_test"
    delegated_envs: list[dict[str, str]] = []
    inspect_boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_review_diagnostics_boundary",
        lambda: inspect_boundary(web_contents()),
    )

    def fake_decision_smoke(environ: dict[str, str]) -> dict[str, Any]:
        delegated_envs.append(environ)
        return decision_pass_evidence(raw_url)

    monkeypatch.setattr(
        smoke.decision_smoke,
        "run_ae_web_repaired_response_decision_postgres_smoke",
        fake_decision_smoke,
    )

    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": raw_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["diagnostics_boundary"]["ok"] is True
    assert evidence["decision_smoke"]["status"] == "PASS"
    assert evidence["checks"] == {key: True for key in evidence["checks"]}
    assert raw_url not in str(evidence)
    assert delegated_envs[0][smoke.decision_smoke.SMOKE_ENV] == "1"
    assert delegated_envs[0][smoke.decision_smoke.SMOKE_PROFILE_ENV] == (
        smoke.DEFAULT_PROFILE
    )
    assert smoke.summary_line(evidence).startswith(
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=pass"
    )


def test_review_diagnostics_smoke_reports_decision_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect_boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_review_diagnostics_boundary",
        lambda: inspect_boundary(web_contents()),
    )
    monkeypatch.setattr(
        smoke.decision_smoke,
        "run_ae_web_repaired_response_decision_postgres_smoke",
        lambda environ: {
            "smoke_schema_version": "ae_web_repaired_response_decision_postgres_smoke.v1",
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "configuration_invalid",
        },
    )

    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "decision_postgres_smoke_failed"
    assert evidence["decision_status"] == "FAIL"
    assert evidence["decision_failure_code"] == "configuration_invalid"


def test_review_diagnostics_smoke_reports_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_decision_evidence = decision_pass_evidence()
    bad_decision_evidence["cleanup"] = {
        "deleted_decisions": 0,
        "deleted_handoffs": 1,
    }
    inspect_boundary = smoke.inspect_ae_web_repaired_review_diagnostics_boundary
    monkeypatch.setattr(
        smoke,
        "inspect_ae_web_repaired_review_diagnostics_boundary",
        lambda: inspect_boundary(web_contents()),
    )
    monkeypatch.setattr(
        smoke.decision_smoke,
        "run_ae_web_repaired_response_decision_postgres_smoke",
        lambda environ: bad_decision_evidence,
    )

    evidence = smoke.run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": "postgresql://x:y@host/db"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "evidence_checks_failed"
    assert evidence["detail"] == "decision_cleanup"


def test_review_diagnostics_redaction_guard_rejects_raw_url_and_password() -> None:
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
    smoke.assert_smoke_evidence_redacted(
        "safe postgresql://nex_ae_user:***@host/nex_ae_test",
        {"NEX_AE_TEST_DATABASE_URL": raw_url},
    )


def test_review_diagnostics_safe_decision_failure_detail() -> None:
    assert smoke._safe_decision_failure_detail({"status": "FAIL"}) == (
        "decision_status=FAIL decision_failure_code=unknown"
    )


def test_review_diagnostics_summary_for_unknown_failure() -> None:
    assert smoke.summary_line({"status": "FAIL"}) == (
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=fail "
        "service=None reason=None"
    )


def test_review_diagnostics_helpers_cover_paths_and_missing_reads() -> None:
    assert smoke._relative_path(smoke.ROOT / "apps" / "nex-ae-web") == (
        "apps/nex-ae-web"
    )
    assert smoke._relative_path(smoke.ROOT.parent / "external") == (
        str(smoke.ROOT.parent / "external")
    )
    assert smoke._read_text(smoke.ROOT / "missing" / "nope.js") == ""


def test_review_diagnostics_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_repaired_response_review_diagnostics_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_web_repaired_response_review_diagnostics_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_web_repaired_response_review_diagnostics_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "execution_failed",
        },
    )

    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_summarize_decision_smoke_evidence_defaults_missing_fields() -> None:
    summary = smoke.summarize_decision_smoke_evidence(
        {"smoke_schema_version": "decision.v1", "status": "PASS"}
    )

    assert summary == {
        "smoke_schema_version": "decision.v1",
        "status": "PASS",
        "web_boundary": {
            "ok": False,
            "anchors_present": 0,
            "anchors_required": 0,
        },
        "checks": {
            "api_route_created_decision": False,
            "api_store_loaded_decision": False,
            "api_row_count": False,
            "api_cleanup": False,
        },
    }


def test_review_diagnostics_failure_helper_merges_extra_fields() -> None:
    evidence = smoke._failure(
        "boom",
        "bad",
        profile="test",
        extra=SimpleNamespace(value="context"),
    )

    assert evidence["failure_code"] == "boom"
    assert evidence["extra"].value == "context"
