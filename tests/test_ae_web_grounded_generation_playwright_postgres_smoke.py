from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

import run_ae_web_grounded_generation_playwright_postgres_smoke as smoke


def enabled_env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.AE_DATABASE_ENV: (
            "postgresql+psycopg://nex_ae_user:ae-secret@localhost/nex_ae_test"
        ),
        smoke.CX_DATABASE_ENV: (
            "postgresql+psycopg://nex_cx_user:cx-secret@localhost/nex_cx_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.test:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.test:9111",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
        **smoke.protected_dgx_vllm_profile_defaults(),
        **overrides,
    }


def source_pass(_env: dict[str, str]) -> dict[str, str]:
    return {"status": "PASS"}


def execution_pass(**_kwargs) -> dict[str, object]:
    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "ae": {"database": smoke.AE_DATABASE, "role": smoke.AE_ROLE},
            "cx": {"database": smoke.CX_DATABASE, "role": smoke.CX_ROLE},
        },
        "browser_observation": {
            "display_mode": "VERIFIED_RESPONSE",
            "timeline_event_count": 6,
        },
        "provider_observation": {
            capability: {
                "model": model,
                "success_count": 1,
                "failure_count": 0,
            }
            for capability, model in smoke.EXPECTED_MODELS.items()
        },
        "checks": {"integrated_path": True},
        "failed_checks": [],
    }


def patch_migrations(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("1089", "1090"),
            applied=(),
            skipped=("1089", "1090"),
        ),
    )


def test_activation_profile_and_configuration_guards() -> None:
    skipped = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    profile = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert profile["failure_code"] == "profile_not_allowed"

    missing = enabled_env()
    missing[smoke.AE_DATABASE_ENV] = ""
    invalid = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        missing
    )
    assert invalid["failure_code"] == "configuration_invalid"
    assert any(item["field"] == smoke.AE_DATABASE_ENV for item in invalid["detail"])

    wrong = enabled_env(
        **{
            smoke.CX_DATABASE_ENV: (
                "postgresql+psycopg://nex_cx_user:secret@localhost/nex_cx_dev"
            )
        }
    )
    issues = smoke.configuration_issues(wrong)
    assert any(item["error_code"] == "database_target_not_allowed" for item in issues)


def test_preflight_and_readiness_fail_closed() -> None:
    preflight = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=lambda _env: {"status": "FAIL", "failure_code": "offline"},
    )
    assert preflight["failure_code"] == "live_provider_preflight_failed"
    assert preflight["source_smokes"]["live_provider_preflight"]["status"] == "FAIL"

    readiness = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=source_pass,
        readiness_runner=lambda _env: {"status": "FAIL", "failure_code": "browser"},
    )
    assert readiness["failure_code"] == "playwright_readiness_failed"
    assert readiness["source_smokes"]["playwright_readiness"]["status"] == "FAIL"


def test_success_builds_redacted_correlated_evidence(monkeypatch) -> None:
    patch_migrations(monkeypatch)
    calls = []

    def executor(**kwargs):
        calls.append(kwargs)
        return execution_pass()

    result = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=source_pass,
        readiness_runner=source_pass,
        executor=executor,
    )
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert result["actual_postgres"] is True
    assert result["evidence_mode"] == "single_correlated_browser_request"
    assert result["migrations"]["ae"]["planned_count"] == 2
    assert result["checks"]["integrated_path"] is True
    assert calls[0]["runtime_environ"]["NEX_MO_PROVIDER_MODE"] == "live"
    assert "ae-secret" not in serialized
    assert "generation-secret" not in serialized
    assert smoke.summary_line(result) == (
        "ae_web_grounded_generation_live=pass checks=3/3 "
        "display=VERIFIED_RESPONSE providers=3/3 databases=ae,cx"
    )


def test_failed_checks_and_bounded_exceptions(monkeypatch) -> None:
    patch_migrations(monkeypatch)
    failed = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=source_pass,
        readiness_runner=source_pass,
        executor=lambda **_kwargs: {"checks": {"browser": False}},
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "grounded_generation_live_checks_failed"

    invalid = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=source_pass,
        readiness_runner=source_pass,
        executor=lambda **_kwargs: (_ for _ in ()).throw(ValueError("private")),
    )
    assert invalid["failure_code"] == "configuration_invalid"
    assert invalid["detail"] == "ValueError"

    generic = smoke.run_ae_web_grounded_generation_playwright_postgres_smoke(
        enabled_env(),
        preflight_runner=source_pass,
        readiness_runner=source_pass,
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert generic["failure_code"] == "execution_failed"
    assert generic["detail"] == "RuntimeError"

    staged = RuntimeError("private")
    staged.smoke_stage = "admit_artifact.lineage_invalid"
    assert smoke._safe_exception_detail(staged) == (
        "RuntimeError:admit_artifact.lineage_invalid"
    )
    staged.smoke_stage = "unsafe detail!"
    assert smoke._safe_exception_detail(staged) == "RuntimeError"


def test_protected_oa_fixture_login_introspection_and_revoke() -> None:
    fixture = smoke.ProtectedOaSessionFixture(
        smoke.TENANT_ID,
        smoke.OWNER_ID,
        smoke.EMPLOYEE_ID,
        smoke.LOGIN_PASSWORD,
    )
    request = {
        "tenant_id": smoke.TENANT_ID,
        "employee_id": smoke.EMPLOYEE_ID,
        "password": smoke.LOGIN_PASSWORD,
        "requested_scopes": ["workspace:use", "documents:upload"],
    }
    session = fixture.login_with_credentials(
        request,
        request_id="request-1090",
        trace_id="1" * 32,
    )["session"]
    assert session["subject_ref"]["id"] == smoke.OWNER_ID
    assert fixture.introspect_session(
        session["session_id"],
        request_id="request-1090",
        trace_id="1" * 32,
    )["active"] is True
    assert fixture.revoke_session(
        session["session_id"],
        request_id="request-1090",
        trace_id="1" * 32,
    )["session"]["status"] == "REVOKED"
    with pytest.raises(smoke.OaUserSessionClientError):
        fixture.login_with_credentials(
            {**request, "password": "wrong"},
            request_id="request-1090",
            trace_id="1" * 32,
        )
    with pytest.raises(AssertionError):
        fixture.issue_session({})


def test_live_worker_adapter_delegates_and_executes_worker(monkeypatch) -> None:
    calls = []

    class Base:
        def admit_generation(self, payload, **kwargs):
            calls.append(("admit", payload, kwargs))
            return {"job": {"job_id": "job-1090"}}

        def get_handoff(self, *args, **kwargs):
            return {"handoff": True}

        def get_job(self, *args, **kwargs):
            return {"job": True}

        def cancel_job(self, *args, **kwargs):
            return {"cancel": True}

    monkeypatch.setattr(smoke, "_test_client_adapter", lambda _client: Base())
    monkeypatch.setattr(
        smoke,
        "run_bounded_worker_batch",
        lambda **kwargs: {"succeeded_count": 1, "worker_id": kwargs["worker_id"]},
    )
    adapter = smoke.LiveWorkerCxAsyncClient(
        object(),
        job_queue=object(),
        leases=object(),
        generation_runtime=object(),
        private_store=object(),
        generation_client=object(),
    )
    admitted = adapter.admit_generation(
        {"prompt": "private"},
        request_id="request-1090",
        trace_id="2" * 32,
        idempotency_key="key-1090",
    )
    assert admitted["job"]["job_id"] == "job-1090"
    assert adapter.worker_results[0]["succeeded_count"] == 1
    assert adapter.get_handoff("job") == {"handoff": True}
    assert adapter.get_job("job") == {"job": True}
    assert adapter.cancel_job("job") == {"cancel": True}


def test_node_runner_helpers_and_redaction(monkeypatch) -> None:
    payload = {"status": "PASS", "interaction_ref": "interaction-1090"}
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(payload), stderr=""
        ),
    )
    result = smoke.run_node_playwright_smoke(
        {smoke.CHROMIUM_ENV: "/usr/bin/google-chrome"},
        web_url="http://127.0.0.1:1090/",
        document_id="7d88f119-d9c7-4c8a-a310-c3eea6613f64",
        workspace_id="7f4c34be-6d3f-4296-884d-b823904cf5df",
        chat_document_id="6ba55095-00c3-42c5-9f67-f0699dd99617",
    )
    assert result["interaction_ref"] == "interaction-1090"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="not-json", stderr="private"
        ),
    )
    failed = smoke.run_node_playwright_smoke(
        {},
        web_url="http://local/",
        document_id="document",
        workspace_id="workspace",
        chat_document_id="chat-document",
    )
    assert failed["failure_code"] == "node_playwright_failed"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(["not", "an", "object"]), stderr=""
        ),
    )
    invalid_payload = smoke.run_node_playwright_smoke(
        {},
        web_url="http://local/",
        document_id="document",
        workspace_id="workspace",
        chat_document_id="chat-document",
    )
    assert invalid_payload["failure_code"] == "node_payload_invalid"

    env = enabled_env()
    smoke.assert_evidence_redacted({"safe": True}, env)
    with pytest.raises(ValueError, match="private content"):
        smoke.assert_evidence_redacted({"value": smoke.SOURCE_TEXT}, env)
    with pytest.raises(ValueError, match="storage path"):
        smoke.assert_evidence_redacted({"value": "cx-private/path"}, env)
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "generation-secret"}, env)


def test_misc_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    assert smoke._target_url_allowed(
        enabled_env()[smoke.AE_DATABASE_ENV],
        role=smoke.AE_ROLE,
        database=smoke.AE_DATABASE,
    )
    assert not smoke._target_url_allowed(
        "postgresql://wrong@localhost/dev", role=smoke.AE_ROLE, database=smoke.AE_DATABASE
    )
    assert not smoke._target_url_allowed(
        "postgresql://user:secret@[::1/test",
        role=smoke.AE_ROLE,
        database=smoke.AE_DATABASE,
    )
    assert smoke._migration_current(
        SimpleNamespace(planned=("1", "2"), applied=("1",), skipped=("2",))
    )
    assert not smoke._migration_current(SimpleNamespace())
    assert smoke._migration_summary(SimpleNamespace())["latest_version"] is None
    assert smoke._source_status({}) == {"status": "UNKNOWN"}
    assert smoke._source_failure_detail({}) == "unknown"
    assert smoke._safe_exception_detail(RuntimeError("private")) == "RuntimeError"
    constrained = RuntimeError("private")
    constrained.orig = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="safe_constraint_1090")
    )
    assert smoke._safe_exception_detail(constrained) == (
        "RuntimeError:safe_constraint_1090"
    )
    assert smoke._digest("stable") == smoke._digest("stable")
    assert smoke._source_failure_detail({"skip_reason": "disabled"}) == "disabled"
    assert smoke._secret_fragment("X", "short") is None
    assert smoke._secret_fragment(smoke.CHROMIUM_ENV, "/browser") is None
    assert smoke._secret_fragment(
        smoke.AE_DATABASE_ENV,
        enabled_env()[smoke.AE_DATABASE_ENV],
    ) == "ae-secret"
    assert smoke._secret_fragment(
        smoke.AE_DATABASE_ENV,
        "postgresql://user:secret@[::1/test",
    ) == "postgresql://user:secret@[::1/test"
    failed = {"status": "FAIL", "checks": {}}
    assert "providers=0/3" in smoke.summary_line(failed)

    monkeypatch.setattr(
        smoke,
        "run_ae_web_grounded_generation_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    monkeypatch.setattr(smoke, "assert_evidence_redacted", lambda *_args: None)
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_grounded_generation_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_default_source_runners_delegate(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_protected_dgx_live_profile",
        lambda env, profile_name: {
            "status": "PASS",
            "env": env,
            "profile_name": profile_name,
        },
    )
    monkeypatch.setattr(
        smoke,
        "run_ae_web_playwright_readiness",
        lambda env, require_installed: {
            "status": "PASS",
            "env": env,
            "require_installed": require_installed,
        },
    )
    env = {"SAFE": "value"}
    assert smoke._run_live_preflight(env)["profile_name"] == smoke.DGX_PROFILE_NAME
    assert smoke._run_playwright_readiness(env)["require_installed"] is True


def test_worker_observation_is_bounded() -> None:
    assert smoke._worker_observation({}) == {
        "stop_reason": None,
        "claimed_count": 0,
        "succeeded_count": 0,
        "retry_scheduled_count": 0,
        "dead_lettered_count": 0,
        "latest_state": None,
        "latest_error_code": None,
    }
    result = smoke._worker_observation(
        {
            "stop_reason": "FAILURE",
            "claimed_count": 1,
            "succeeded_count": 0,
            "retry_scheduled_count": 1,
            "dead_lettered_count": 0,
            "executions": [
                {"state": "RETRY_SCHEDULED", "error_code": "safe.error"}
            ],
        }
    )
    assert result["latest_state"] == "RETRY_SCHEDULED"
    assert result["latest_error_code"] == "safe.error"


def test_stale_ae_runtime_cleanup_is_owner_scoped() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_chat_interactions ("
                "chat_interaction_id TEXT, user_id TEXT, trace_id TEXT, "
                "request_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_prompt_render_events (chat_interaction_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE service_operational_events ("
                "trace_id TEXT, request_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_workspaces (workspace_id TEXT, owner_user_id TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_chat_interactions VALUES "
                "('target-chat', :owner, 'target-trace', 'target-request'), "
                "('other-chat', 'other-owner', 'other-trace', 'other-request')"
            ),
            {"owner": smoke.OWNER_ID},
        )
        connection.execute(
            text(
                "INSERT INTO ae_prompt_render_events VALUES "
                "('target-chat'), ('other-chat')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_operational_events VALUES "
                "('target-trace', 'target-request'), "
                "('other-trace', 'other-request')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_workspaces VALUES "
                "('target-workspace', :owner), "
                "('other-workspace', 'other-owner')"
            ),
            {"owner": smoke.OWNER_ID},
        )

    deleted = smoke._cleanup_stale_s109_ae_runtime(engine)

    assert deleted == {
        "events": 1,
        "render_events": 1,
        "chat": 1,
        "workspaces": 1,
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM ae_chat_interactions")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM ae_prompt_render_events")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM service_operational_events")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM ae_workspaces")
        ).scalar_one() == 1
    engine.dispose()
