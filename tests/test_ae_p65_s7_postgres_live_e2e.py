from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_p65_s7_postgres_live_e2e.py"
SPEC = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


SAFE_URL = "postgresql://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
SOURCE_REVISION = "3" * 40
WHEEL_SHA = "sha256:" + "4" * 64


def _enabled_environment(source: Path) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: SAFE_URL,
        smoke.NSL_SOURCE_ENV: str(source),
        "NEX_MO_VLLM_BASE_URL": "http://provider.invalid:9111",
        "NEX_MO_VLLM_API_KEY": "protected-generation-key",
    }


def _success_execution() -> dict[str, object]:
    return {
        "actual_postgres": True,
        "actual_remote_provider": True,
        "provider_mode": "live",
        "provider_profile": "general-llm-default",
        "model_ref": "model-revision-a",
        "deployment_id": "deployment-a",
        "provider_call_counts": {
            "readiness": 4,
            "generation": 3,
            "semantic_stages": ["INTENT", "CONTEXT", "PLAN"],
        },
        "database": smoke.EXPECTED_DATABASE,
        "role": smoke.EXPECTED_ROLE,
        "checks": {"database_zero_residue": True},
        "runtime_row_counts": {"ae_step_result": 2, "ae_agent_result": 1},
        "cleanup_counts": {"remaining": 0},
    }


def test_protected_e2e_is_skipped_by_default_and_guards_inputs(tmp_path) -> None:
    skipped = smoke.run_p65_s7_postgres_live_e2e({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert skipped["actual_remote_provider"] is False

    missing_database = smoke.run_p65_s7_postgres_live_e2e({smoke.SMOKE_ENV: "1"})
    assert missing_database["failure_code"] == "database_url_missing"

    wrong_target = smoke.run_p65_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:private@localhost/other",
        }
    )
    assert wrong_target["failure_code"] == "target_not_allowed"
    assert "private" not in str(wrong_target)

    missing_source = smoke.run_p65_s7_postgres_live_e2e(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: SAFE_URL}
    )
    assert missing_source["failure_code"] == "nsl_source_missing"

    source = tmp_path / "nsl"
    source.mkdir()
    missing_provider = smoke.run_p65_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: SAFE_URL,
            smoke.NSL_SOURCE_ENV: str(source),
        }
    )
    assert missing_provider["failure_code"] == "provider_configuration_missing"
    assert missing_provider["diagnostics"]["missing_env"] == [
        "NEX_MO_VLLM_API_KEY",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL",
    ]


def test_protected_e2e_composes_migration_execution_and_redaction(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps(
            {"source_revision": SOURCE_REVISION, "wheel_sha256": WHEEL_SHA}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock)
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("2205_ae_nsl_dual_profile", smoke.REQUIRED_MIGRATION),
            applied=(smoke.REQUIRED_MIGRATION,),
            skipped=("2205_ae_nsl_dual_profile",),
        ),
    )
    monkeypatch.setattr(smoke, "_platform_revision", lambda: "a" * 40)

    evidence = smoke.run_p65_s7_postgres_live_e2e(
        _enabled_environment(source),
        executor=lambda **_kwargs: _success_execution(),
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "migration_current": True,
        "database_zero_residue": True,
    }
    assert evidence["nsl_revision"] == SOURCE_REVISION
    assert evidence["nsl_wheel_sha256"] == WHEEL_SHA
    assert "secret" not in evidence["redacted_database_url"]
    assert "protected-generation-key" not in json.dumps(evidence)
    assert "checks=2/2" in smoke.summary_line(evidence)
    assert "generation_calls=3" in smoke.summary_line(evidence)


def test_protected_e2e_fails_closed_on_migration_and_check_failure(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps(
            {"source_revision": SOURCE_REVISION, "wheel_sha256": WHEEL_SHA}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock)
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(smoke, "_platform_revision", lambda: "a" * 40)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("2205_ae_nsl_dual_profile",),
            applied=(),
            skipped=("2205_ae_nsl_dual_profile",),
        ),
    )
    failed_execution = _success_execution()
    failed_execution["checks"] = {"database_zero_residue": False}

    evidence = smoke.run_p65_s7_postgres_live_e2e(
        _enabled_environment(source),
        executor=lambda **_kwargs: failed_execution,
    )
    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "p65_s7_acceptance_failed"
    assert evidence["checks"]["migration_current"] is False

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            smoke.MigrationError(SAFE_URL)
        ),
    )
    migration_failure = smoke.run_p65_s7_postgres_live_e2e(
        _enabled_environment(source), executor=lambda **_kwargs: _success_execution()
    )
    assert migration_failure["failure_code"] == "execution_failed"
    assert "secret" not in migration_failure["detail"]


def test_nsl_source_validation_failure_is_bounded(monkeypatch, tmp_path) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    lock = tmp_path / "lock.json"
    lock.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock)

    evidence = smoke.run_p65_s7_postgres_live_e2e(
        _enabled_environment(source)
    )
    assert evidence["failure_code"] == "nsl_source_invalid"
    assert evidence["detail"] == "JSONDecodeError"


def test_counting_client_and_in_process_requester_preserve_contract() -> None:
    class Delegate:
        def check_required_mode_readiness(self, **kwargs):
            return kwargs

        def generate_candidate(self, **kwargs):
            return kwargs

    counting = smoke.CountingGenerationClient(Delegate())
    assert counting.check_required_mode_readiness(
        request_id="request", trace_id="a" * 32
    )["request_id"] == "request"
    assert counting.generate_candidate(
        semantic_stage="PLAN",
        messages=({"role": "user", "content": "x"},),
        request_id="request",
        trace_id="a" * 32,
    )["semantic_stage"] == "PLAN"
    assert counting.readiness_calls == 1
    assert counting.generation_stages == ["PLAN"]

    app = FastAPI()

    @app.get("/")
    def root() -> dict[str, str]:
        return {"status": "root"}

    @app.post("/echo")
    def echo(payload: dict[str, object]) -> dict[str, object]:
        return payload

    with TestClient(app) as client:
        response = smoke.TestClientRequester(client)(
            "POST",
            "http://in-process/echo?mode=live",
            json={"status": "ok"},
            headers={"X-Test": "1"},
            timeout=1.0,
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    with TestClient(app) as client:
        root_response = smoke.TestClientRequester(client)(
            "GET",
            "http://in-process",
            json=None,
            headers={},
            timeout=1.0,
        )
    assert root_response.json() == {"status": "root"}


def test_trusted_resolver_cleanup_and_revision_helpers(monkeypatch) -> None:
    resolver = smoke.TrustedResolver("interaction-1")
    resolved = resolver.resolve(object())
    assert resolved.context_manifest[0]["source_ref"] == (
        "AE:INTERACTION:interaction-1"
    )
    assert resolved.context_manifest[0]["as_of"] == smoke.NOW

    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        for table in (
            "ae_semantic_candidate",
            "ae_executable_step",
            "ae_executable_plan",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (tenant_id TEXT NOT NULL)")
            )
            connection.execute(
                text(f"INSERT INTO {table} (tenant_id) VALUES (:tenant_id)"),
                {"tenant_id": "tenant-1"},
            )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(
        smoke,
        "_cleanup_planning",
        lambda *_args, **_kwargs: {"remaining": 0, "ae_workspaces": 1},
    )

    counts = smoke._cleanup(
        factory,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert counts["ae_semantic_candidate"] == 1
    assert counts["ae_executable_step"] == 1
    assert counts["ae_executable_plan"] == 1
    assert counts["remaining"] == 0
    assert len(smoke._platform_revision()) == 40


def test_dynamic_calibration_is_exact_and_model_agnostic() -> None:
    readiness = smoke.AeMoGenerationReadiness(
        provider_mode="live",
        readiness_status="READY",
        model_profile="alias-a",
        model_ref="revision-b",
        deployment_id="deployment-c",
        route_id="route-d",
        checked_at="2026-10-17T00:00:00Z",
        expires_at="2026-10-17T00:01:00Z",
        cache_status="FRESH",
        source="active_preflight",
    )
    registry = smoke._calibration_registry(readiness)
    assert {
        policy.semantic_stage for policy in registry.policies
    } == {"INTENT", "CONTEXT", "PLAN"}
    assert all(policy.model_ref == "revision-b" for policy in registry.policies)
    assert registry.select(
        semantic_stage="PLAN", model_profile="alias-a", model_ref="revision-b"
    ) is not None
    assert registry.select(
        semantic_stage="PLAN", model_profile="alias-a", model_ref="other"
    ) is None


def test_evidence_output_and_redaction_guard(tmp_path) -> None:
    output = Path("/tmp/p65-s7-live-test-evidence.json")
    smoke.write_evidence(output, {"status": "PASS"})
    assert output.read_text(encoding="utf-8").endswith("\n")
    output.unlink()

    with pytest.raises(ValueError):
        smoke.write_evidence(ROOT / "reports" / "outside.json", {"status": "PASS"})
    with pytest.raises(ValueError, match="NEX_MO_VLLM_API_KEY"):
        smoke._assert_evidence_redacted(
            {"leak": "protected-secret"},
            {"NEX_MO_VLLM_API_KEY": "protected-secret"},
        )


def test_main_renders_summary_and_failure(monkeypatch, capsys) -> None:
    passed = _success_execution()
    passed["status"] = "PASS"
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(smoke, "run_p65_s7_postgres_live_e2e", lambda: passed)
    assert smoke.main(["--summary"]) == 0
    assert "p65_s7_postgres_live_e2e=pass" in capsys.readouterr().out

    output = Path("/tmp/p65-s7-main-test-evidence.json")
    assert smoke.main(["--output", str(output)]) == 0
    assert output.exists()
    output.unlink()
    capsys.readouterr()

    monkeypatch.setattr(
        smoke, "run_p65_s7_postgres_live_e2e", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_skip_summary_and_partial_provider_configuration() -> None:
    skipped = smoke.run_p65_s7_postgres_live_e2e({})
    assert smoke.summary_line(skipped) == (
        f"p65_s7_postgres_live_e2e=skipped reason={smoke.SMOKE_ENV}"
    )
    assert smoke._missing_provider_configuration(
        {"NEX_MO_VLLM_BASE_URL": "http://provider.invalid"}
    ) == ["NEX_MO_VLLM_API_KEY"]
    assert smoke._missing_provider_configuration(
        {"NEX_MO_VLLM_API_KEY": "key"}
    ) == ["NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL"]


def test_http_error_type_is_safely_projected() -> None:
    error = smoke.AeMoGenerationClientError(
        status_code=503,
        error_code="PROVIDER_NOT_READY",
        detail="http://secret.internal",
    )
    assert smoke._safe_error_code(error) == "PROVIDER_NOT_READY"
    assert smoke._safe_error_code(httpx.ConnectError("private")) == "ConnectError"


def test_protected_actual_postgres_remote_provider_e2e() -> None:
    if os.environ.get(smoke.SMOKE_ENV) != "1":
        pytest.skip(f"{smoke.SMOKE_ENV}=1 is required")

    evidence = smoke.run_p65_s7_postgres_live_e2e()

    assert evidence["status"] == "PASS", evidence
    assert evidence["actual_postgres"] is True
    assert evidence["actual_remote_provider"] is True
    assert evidence["provider_call_counts"]["semantic_stages"] == [
        "INTENT",
        "CONTEXT",
        "PLAN",
    ]
    assert evidence["runtime_row_counts"]["ae_step_result"] == 2
    assert evidence["runtime_row_counts"]["ae_agent_result"] == 1
    assert evidence["runtime_row_counts"]["ae_result_delivery"] == 1
    assert evidence["cleanup_counts"]["remaining"] == 0
    assert evidence["runtime_cleanup_counts"]["s7_remaining"] == 0
