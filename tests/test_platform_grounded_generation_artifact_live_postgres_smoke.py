from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_platform_grounded_generation_artifact_live_postgres_smoke as smoke


def _env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_AE_TEST_DATABASE_URL": "ae-db-secret",
        "NEX_CX_TEST_DATABASE_URL": "cx-db-secret",
        "NEX_MO_VLLM_API_KEY": "provider-secret",
        **overrides,
    }


def _source(*, extension_ok: bool = True) -> dict:
    extension_checks = {
        "response_lineage_bound": extension_ok,
        "grounded_artifact_admitted": extension_ok,
        "restart_worker_completed": extension_ok,
        "artifact_ready_with_exact_lineage": extension_ok,
        "owner_preview_ready": extension_ok,
        "owner_download_ready": extension_ok,
        "cross_owner_hidden": extension_ok,
        "metadata_only_postgres": extension_ok,
        "artifact_cleanup_complete": extension_ok,
    }
    return {
        "status": "PASS",
        "actual_postgres": True,
        "evidence_mode": "single_correlated_browser_request",
        "failed_checks": [],
        "checks": {
            "actual_ae_test_database": True,
            "actual_cx_test_database": True,
            "cx_retrieval_persisted": True,
            "cx_generation_persisted": True,
            "all_live_provider_capabilities_called": True,
            "ae_chat_persisted": True,
            **extension_checks,
        },
        "extension_observation": {
            "artifact_status": "READY",
            "rendered_file_count": 2,
            "private_payload_included": False,
            "checks": extension_checks,
        },
    }


def _zero_residue(_env: dict[str, str]) -> dict[str, int]:
    return {
        "ae_chat": 0,
        "ae_workspaces": 0,
        "ae_artifacts": 0,
        "ae_handoffs": 0,
        "cx_generations": 0,
        "cx_retrieval_packages": 0,
        "cx_jobs": 0,
    }


def test_protected_smoke_is_opt_in_and_test_profile_only() -> None:
    skipped = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        {}
    )
    blocked = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        _env(**{smoke.PROFILE_ENV: "dev"})
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert blocked["failure_code"] == "profile_not_allowed"


def test_protected_smoke_composes_correlated_live_evidence() -> None:
    calls: list[dict[str, str]] = []

    result = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        _env(),
        source_runner=lambda env: calls.append(env) or _source(),
        residue_reader=_zero_residue,
    )

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "check_count": 8,
        "passed_check_count": 8,
        "provider_capability_count": 3,
        "database_count": 2,
    }
    assert result["artifact_observation"] == {
        "artifact_status": "READY",
        "rendered_file_count": 2,
        "private_payload_included": False,
    }
    assert calls[0][smoke.base.SMOKE_ENV] == "1"
    assert calls[0]["NEX_MO_PROVIDER_MODE"] == "live"


def test_protected_smoke_fails_closed_for_source_or_residue() -> None:
    source_failure = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        _env(),
        source_runner=lambda _env: {
            "status": "FAIL",
            "failure_code": "provider-offline",
            "failed_checks": ["live"],
        },
        residue_reader=_zero_residue,
    )
    bad_residue = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        _env(),
        source_runner=lambda _env: _source(extension_ok=False),
        residue_reader=lambda _env: {"ae_artifacts": 1},
    )

    assert source_failure["failure_code"] == "source_journey_failed"
    assert source_failure["detail"] == "provider-offline"
    assert source_failure["source_status"]["failed_check_count"] == 1
    assert bad_residue["status"] == "FAIL"
    assert "cleanup_residue_free" in bad_residue["failed_checks"]
    assert "artifact_admitted_and_rendered" in bad_residue["failed_checks"]


def test_source_adapter_and_helpers(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        smoke.TestClientCxArtifactSourceClient,
        "_get",
        lambda self, path, **kwargs: calls.append((path, kwargs)) or {"ok": True},
    )
    adapter = smoke.TestClientCxArtifactSourceClient(object())
    kwargs = {
        "tenant_id": "tenant",
        "owner_user_id": "owner",
        "request_id": "request",
        "trace_id": "1" * 32,
    }

    assert adapter.get_generation("generation", **kwargs) == {"ok": True}
    assert adapter.get_structured_draft("generation", **kwargs) == {"ok": True}
    assert calls[0][0] == "/api/v1/generations/generation"
    assert calls[1][0].endswith("/structured-draft")
    assert smoke._mapping(None) == {}
    assert smoke._bool_mapping({"yes": True, "no": 1}) == {
        "yes": True,
        "no": False,
    }
    assert smoke._source_status({"status": "PASS"})["failed_check_count"] == 0
    assert smoke._source_status({"detail": "safe.stage"})["detail"] == "safe.stage"

    class Result:
        @staticmethod
        def scalar_one():
            return 2

    class Connection:
        @staticmethod
        def execute(*_args, **_kwargs):
            return Result()

    assert smoke._count(Connection(), "table", "column", None) == 0
    assert smoke._count(Connection(), "table", "column", "value") == 2
    assert smoke._owner_count(Connection(), "table", "column", "owner") == 2

    run = smoke.base.build_live_ingestion_index_run(
        saved={
            "extraction": {"job_id": "job-1"},
            "upload_id": "upload-1",
            "created_at": "2026-10-06T00:00:00Z",
        },
        extraction={"updated_at": "2026-10-06T00:00:01Z"},
        document_id="document-1",
        request_id="request-1",
        trace_id="1" * 32,
    )
    assert run["job_id"] == "job-1"
    assert run["idempotency_key"] == "upload-1"
    assert run["created_at"] < run["updated_at"]

    smoke._require_success(SimpleNamespace(status_code=202), "admit")
    with pytest.raises(smoke.ArtifactJourneySmokeError) as error:
        smoke._require_success(
            SimpleNamespace(
                status_code=409,
                json=lambda: {"error_code": "ae.lineage_mismatch"},
            ),
            "admit",
        )
    assert error.value.smoke_stage == "admit.ae.lineage_mismatch"
    with pytest.raises(smoke.ArtifactJourneySmokeError) as unreadable:
        smoke._require_success(
            SimpleNamespace(
                status_code=502,
                json=lambda: (_ for _ in ()).throw(ValueError("invalid body")),
            ),
            "read",
        )
    assert unreadable.value.smoke_stage == "read"
    assert smoke._safe_identifier(None) is None
    assert smoke._safe_identifier("   ") is None
    assert smoke._safe_identifier("a" * 97) is None
    assert smoke._safe_identifier("unsafe detail!") is None


def test_redaction_and_source_delegation(monkeypatch) -> None:
    with pytest.raises(AssertionError):
        smoke._assert_redacted({"value": "provider-secret"}, _env())
    with pytest.raises(AssertionError):
        smoke._assert_redacted({"value": smoke.base.SOURCE_TEXT}, {})
    with pytest.raises(AssertionError):
        smoke._assert_redacted({"value": "Authorization: Bearer x"}, {})

    calls = []
    monkeypatch.setattr(
        smoke.base,
        "run_ae_web_grounded_generation_playwright_postgres_smoke",
        lambda env, executor: calls.append((env, executor)) or {"status": "PASS"},
    )
    monkeypatch.setattr(
        smoke.base,
        "_execute_live_browser_smoke",
        lambda **kwargs: kwargs,
    )
    result = smoke._run_source_journey({"enabled": "yes"})
    assert result == {"status": "PASS"}
    assert calls[0][0] == {"enabled": "yes"}
    assert calls[0][1](value=1)["journey_hook"] is smoke._execute_artifact_journey


def test_summary_and_cli(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_grounded_generation_artifact_live_postgres_smoke(
        _env(),
        source_runner=lambda _env: _source(),
        residue_reader=_zero_residue,
    )
    assert smoke.summary_line({"status": "SKIPPED"}).startswith(
        "platform_grounded_artifact_live=skipped"
    )
    assert "code=broken" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "broken"}
    )
    assert smoke.summary_line(passing) == (
        "platform_grounded_artifact_live=pass checks=8/8 "
        "providers=3 databases=2 residue=0"
    )

    monkeypatch.setattr(
        smoke,
        "run_platform_grounded_generation_artifact_live_postgres_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_grounded_generation_artifact_live_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "broken"},
    )
    assert smoke.main([]) == 1
