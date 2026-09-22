from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_cx_document_intelligence_live_postgres_smoke as smoke


def _live_env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:db-secret@localhost/nex_cx_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.test:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": (
            "http://dgx.test:12000/v1/chat/completions"
        ),
        "NEX_MO_VLLM_API_KEY": "generation-secret",
        **overrides,
    }


def _execution() -> dict[str, object]:
    return {
        "database_identity": {
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
        },
        "document_observation": {
            "ready_count": 2,
            "vector_dimensions": [2560, 2560],
        },
        "similarity_observation": {"candidate_count": 1},
        "checks": {"all_live_checks": True},
    }


def test_activation_profile_and_configuration_guards() -> None:
    skipped = smoke.run_cx_document_intelligence_live_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).startswith(
        "cx_document_intelligence_live_postgres=skipped"
    )

    profile = smoke.run_cx_document_intelligence_live_postgres_smoke(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert profile["failure_code"] == "profile_not_allowed"

    invalid = smoke.run_cx_document_intelligence_live_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert invalid["failure_code"] == "configuration_invalid"
    assert "NEX_CX_TEST_DATABASE_URL" in invalid["diagnostics"]["missing_env"]
    assert (
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL"
        in invalid["diagnostics"]["missing_env"]
    )


def test_successful_protected_execution_builds_redacted_evidence(monkeypatch) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("0955",),
        applied=(),
        skipped=("0955",),
        dry_run=False,
    )
    monkeypatch.setattr(smoke, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: _live_env()["NEX_CX_TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: migration)
    calls: list[dict[str, object]] = []

    def executor(**kwargs):
        calls.append(kwargs)
        return _execution()

    evidence = smoke.run_cx_document_intelligence_live_postgres_smoke(
        _live_env(), executor=executor
    )

    assert evidence["status"] == "PASS"
    assert evidence["redacted_database_url"].endswith("@localhost/nex_cx_test")
    assert evidence["migration"]["skipped_count"] == 1
    assert calls[0]["database_env"] == "DB"
    runtime = calls[0]["runtime_environ"]
    assert runtime["NEX_MO_PROVIDER_MODE"] == "live"
    assert runtime["NEX_MO_REMOTE_RERANKER_MODEL"] == "Qwen3-Reranker-4B"
    assert "db-secret" not in str(evidence)
    assert "generation-secret" not in str(evidence)
    assert smoke.summary_line(evidence) == (
        "cx_document_intelligence_live_postgres=pass "
        "db=nex_cx_test ready=2 vector_dim=2560 candidates=1"
    )


def test_execution_failures_are_bounded(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: _live_env()["NEX_CX_TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(),
    )

    def staged(**_kwargs):
        raise smoke.LiveRagSmokeStageError(
            stage="document_alpha",
            error_code="safe_live_failure",
            detail="Safe bounded detail.",
            status_code=503,
            retryable=True,
            stage_status={"document_alpha": "FAIL"},
        )

    failed = smoke.run_cx_document_intelligence_live_postgres_smoke(
        _live_env(), executor=staged
    )
    assert failed["failure_code"] == "execution_failed"
    assert failed["diagnostics"]["stage"] == "document_alpha"
    assert smoke.summary_line(failed).endswith("stage=document_alpha")

    generic = smoke.run_cx_document_intelligence_live_postgres_smoke(
        _live_env(),
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert generic["detail"] == "RuntimeError"
    assert smoke.summary_line(generic).endswith("stage=unknown")

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad target")),
    )
    invalid = smoke.run_cx_document_intelligence_live_postgres_smoke(_live_env())
    assert invalid["failure_code"] == "configuration_invalid"


def test_evidence_redaction_rejects_source_secret_and_path() -> None:
    env = _live_env()
    smoke.assert_evidence_redacted({"safe": True}, env)

    with pytest.raises(ValueError, match="private source"):
        smoke.assert_evidence_redacted(
            {"value": smoke.FORBIDDEN_SOURCE_MARKERS[0]}, env
        )
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "embedding-secret"}, env)
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "db-secret"}, env)
    with pytest.raises(ValueError, match="storage path"):
        smoke.assert_evidence_redacted(
            {"value": "/tmp/nex-cx-s96-live-abc/private-summary"}, env
        )


def test_configuration_and_safe_provider_helpers() -> None:
    assert smoke._missing_configuration(
        _live_env(NEX_MO_VLLM_CHAT_COMPLETIONS_URL="", NEX_MO_VLLM_BASE_URL="http://v")
    ) == []
    assert smoke._secret_fragment("X", "value") is None
    assert smoke._secret_fragment("NEX_MO_VLLM_API_KEY", "key-value") == "key-value"
    assert smoke._secret_fragment("NEX_CX_TEST_DATABASE_URL", "sqlite:///tmp.db") is None
    assert (
        smoke._secret_fragment("NEX_CX_TEST_DATABASE_URL", "user:plain@host/db")
        == "plain"
    )
    assert smoke._secret_fragment("NEX_CX_TEST_DATABASE_URL", None) is None

    observed = smoke._safe_provider_observation(
        {
            "data": [
                {"capability": "generation", "success_count": 2, "failure_count": 0},
                {"capability": "embedding", "success_count": 3, "failure_count": 1},
                "ignored",
            ]
        }
    )
    assert observed == {
        "generation": {"success_count": 2, "failure_count": 0},
        "embedding": {"success_count": 3, "failure_count": 1},
    }
    assert smoke._safe_provider_observation({})["generation"]["success_count"] == 0


def test_main_prints_summary_and_writes_output(monkeypatch, tmp_path, capsys) -> None:
    evidence = {
        "status": "SKIPPED",
        "smoke_schema_version": smoke.SCHEMA_VERSION,
    }
    monkeypatch.setattr(
        smoke,
        "run_cx_document_intelligence_live_postgres_smoke",
        lambda: evidence,
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert '"status": "SKIPPED"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_cx_document_intelligence_live_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "failed"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
