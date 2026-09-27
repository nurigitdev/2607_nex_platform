from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_cx_mvp_integration_live_postgres_smoke as smoke


def _live_env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:db-secret@localhost/nex_cx_test"
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


def _execution() -> dict[str, object]:
    return {
        "database_identity": {
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
        },
        "provider_observation": {
            capability: {
                "model": model,
                "success_count": 1,
                "failure_count": 0,
            }
            for capability, model in smoke.EXPECTED_MODELS.items()
        },
        "lifecycle": {
            "handoff_status": "READY",
            "owner_scope_enforced": True,
        },
        "checks": {"end_to_end": True},
        "failed_checks": [],
    }


def _patch_database(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("0990",),
        applied=(),
        skipped=("0990",),
    )
    monkeypatch.setattr(
        smoke,
        "service_database_env",
        lambda *_args, **_kwargs: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: _live_env()["NEX_CX_TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: migration,
    )


def test_activation_profile_configuration_and_target_guards(monkeypatch) -> None:
    skipped = smoke.run_cx_mvp_integration_live_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    profile = smoke.run_cx_mvp_integration_live_postgres_smoke(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert profile["failure_code"] == "profile_not_allowed"

    invalid = _live_env()
    invalid["NEX_MO_REMOTE_RERANKER_API_KEY"] = ""
    configuration = smoke.run_cx_mvp_integration_live_postgres_smoke(invalid)
    assert configuration["failure_code"] == "configuration_invalid"
    assert configuration["detail"] == [
        {
            "error_code": "configuration_missing",
            "field": "NEX_MO_REMOTE_RERANKER_API_KEY",
        }
    ]

    monkeypatch.setattr(smoke, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: "postgresql://wrong@localhost/wrong",
    )
    target = smoke.run_cx_mvp_integration_live_postgres_smoke(_live_env())
    assert target["failure_code"] == "target_not_allowed"


def test_configuration_reports_missing_models_shapes_and_generation_url() -> None:
    env = _live_env(
        NEX_MO_VLLM_BASE_URL="",
        NEX_MO_REMOTE_EMBEDDING_MODEL="old-embedding",
        NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE="legacy",
    )

    issues = smoke.configuration_issues(env)

    assert {item["error_code"] for item in issues} == {
        "configuration_missing",
        "provider_model_mismatch",
        "provider_shape_mismatch",
    }
    assert any("CHAT_COMPLETIONS" in item["field"] for item in issues)


def test_successful_execution_builds_redacted_live_evidence(monkeypatch) -> None:
    _patch_database(monkeypatch)
    calls: list[dict[str, object]] = []

    def executor(**kwargs):
        calls.append(kwargs)
        return _execution()

    result = smoke.run_cx_mvp_integration_live_postgres_smoke(
        _live_env(),
        executor=executor,
    )

    assert result["status"] == "PASS"
    assert result["provider_path"] == "cx_to_mo_capability_alias_only"
    assert result["migration"] == {
        "planned_count": 1,
        "applied_count": 0,
        "skipped_count": 1,
    }
    assert calls[0]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert calls[0]["runtime_environ"]["NEX_MO_PROVIDER_MODE"] == "live"
    assert "db-secret" not in str(result)
    assert "generation-secret" not in str(result)
    assert smoke.summary_line(result) == (
        "cx_mvp_integration_live_postgres=pass checks=1/1 handoff=READY "
        "database=nex_cx_test providers=embedding,reranking,generation"
    )


def test_failed_checks_and_bounded_exceptions_are_safe(monkeypatch) -> None:
    _patch_database(monkeypatch)
    failed = smoke.run_cx_mvp_integration_live_postgres_smoke(
        _live_env(),
        executor=lambda **_kwargs: {
            "checks": {"handoff": False},
            "failed_checks": ["handoff"],
        },
    )
    assert failed["failure_code"] == "mvp_integration_live_checks_failed"
    assert failed["execution"]["failed_checks"] == ["handoff"]

    generic = smoke.run_cx_mvp_integration_live_postgres_smoke(
        _live_env(),
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert generic["failure_code"] == "execution_failed"
    assert generic["detail"] == "RuntimeError"

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("private")),
    )
    invalid = smoke.run_cx_mvp_integration_live_postgres_smoke(_live_env())
    assert invalid["failure_code"] == "configuration_invalid"
    assert invalid["detail"] == "ValueError"


def test_generation_payload_headers_and_provider_observation() -> None:
    package = {
        "retrieval_package_id": "package-1000",
        "package_hash": "a" * 64,
    }
    payload = smoke._generation_payload(package, "evidence-1000", "1" * 32)

    assert payload["execution_mode"] == "GROUNDED_ANSWER"
    assert payload["retrieval_package_ref"] == package
    assert payload["selected_evidence_ids"] == ["evidence-1000"]
    assert payload["reasoning_mode"] == "disabled"
    headers = smoke._headers("request-1000", "2" * 32, smoke.OWNER_ID)
    assert headers["X-NEX-Tenant-ID"] == smoke.TENANT_ID
    assert headers["X-NEX-Subject-ID"] == smoke.OWNER_ID

    telemetry = {
        "data": ["ignored"]
        + [
            {
                "capability": capability,
                "model_revision": model,
                "success_count": index + 1,
                "failure_count": 0,
            }
            for index, (capability, model) in enumerate(
                smoke.EXPECTED_MODELS.items()
            )
        ]
    }
    observation = smoke._provider_observation(telemetry)
    assert observation["embedding"]["success_count"] == 1
    assert observation["generation"]["model"] == "Qwen3.5-4B"
    assert smoke._provider_observation({})["reranking"] == {
        "model": None,
        "success_count": 0,
        "failure_count": 0,
    }


def test_storage_target_redaction_and_secret_helpers(tmp_path) -> None:
    storage = smoke._storage_config(tmp_path)
    assert storage.chunk_policy == "chunk_1000_100"
    assert storage.bm25_tokenizer == "mecab_ko"
    assert smoke._target_url_allowed(_live_env()["NEX_CX_TEST_DATABASE_URL"])
    assert not smoke._target_url_allowed("postgresql://wrong@localhost/dev")
    assert smoke._digest("stable") == smoke._digest("stable")

    smoke.assert_evidence_redacted({"safe": True}, _live_env())
    with pytest.raises(ValueError, match="private content"):
        smoke.assert_evidence_redacted({"value": smoke.SOURCE_MARKER}, _live_env())
    with pytest.raises(ValueError, match="storage path"):
        smoke.assert_evidence_redacted({"value": "cx-private://hidden"}, _live_env())
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "generation-secret"}, _live_env())

    assert smoke._secret_fragment("X", None) is None
    assert smoke._secret_fragment("X", "abc") is None
    assert smoke._secret_fragment("X", "abcd") == "abcd"
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL", "postgresql://user:secret@localhost/db"
    ) == "secret"
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL", "postgresql://user@localhost/db"
    ) is None


def test_summary_failure_and_main_paths(monkeypatch, tmp_path, capsys) -> None:
    failed = {"status": "FAIL", "failure_code": "boom"}
    assert smoke.summary_line(failed).endswith("error=boom")
    assert smoke.summary_line({}).endswith("error=unknown")

    skipped = {"status": "SKIPPED", "smoke_schema_version": smoke.SCHEMA_VERSION}
    monkeypatch.setattr(
        smoke,
        "run_cx_mvp_integration_live_postgres_smoke",
        lambda: skipped,
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert '"status": "SKIPPED"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_cx_mvp_integration_live_postgres_smoke",
        lambda: failed,
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
