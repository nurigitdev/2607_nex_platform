from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_cx_grounded_generation_live_postgres_smoke as smoke


def _live_env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:db-secret@localhost/nex_cx_test"
        ),
        "NEX_MO_VLLM_BASE_URL": "http://dgx.test:9111",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
        **overrides,
    }


def _execution() -> dict[str, object]:
    return {
        "database_identity": {
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
        },
        "generation_observation": {
            "status": "COMPLETED",
            "provider_model": smoke.EXPECTED_GENERATION_MODEL,
        },
        "provider_observation": {"success_count": 1, "failure_count": 0},
        "checks": {"all_live_checks": True},
    }


def _patch_database(monkeypatch) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("0965", "0966"),
        applied=(),
        skipped=("0965", "0966"),
        dry_run=False,
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


def test_activation_profile_configuration_and_model_guards() -> None:
    skipped = smoke.run_cx_grounded_generation_live_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    profile = smoke.run_cx_grounded_generation_live_postgres_smoke(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert profile["failure_code"] == "profile_not_allowed"

    missing = smoke.run_cx_grounded_generation_live_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert missing["failure_code"] == "configuration_invalid"
    assert missing["diagnostics"]["missing_env"] == [
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_MO_VLLM_API_KEY",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL",
    ]

    mismatch = smoke.run_cx_grounded_generation_live_postgres_smoke(
        _live_env(NEX_MO_VLLM_MODEL="old-model")
    )
    assert mismatch["failure_code"] == "generation_model_mismatch"
    assert mismatch["diagnostics"]["expected_model"] == "Qwen3.5-4B"


def test_successful_execution_builds_redacted_evidence(monkeypatch) -> None:
    _patch_database(monkeypatch)
    calls: list[dict[str, object]] = []

    def executor(**kwargs):
        calls.append(kwargs)
        return _execution()

    evidence = smoke.run_cx_grounded_generation_live_postgres_smoke(
        _live_env(),
        executor=executor,
    )

    assert evidence["status"] == "PASS"
    assert evidence["generation_model"] == "Qwen3.5-4B"
    assert evidence["migration"]["skipped_count"] == 2
    assert evidence["redacted_database_url"].endswith("@localhost/nex_cx_test")
    assert calls[0]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    runtime = calls[0]["runtime_environ"]
    assert runtime["NEX_MO_PROVIDER_MODE"] == "live"
    assert runtime["NEX_MO_VLLM_MODEL"] == "Qwen3.5-4B"
    assert "db-secret" not in str(evidence)
    assert "generation-secret" not in str(evidence)
    assert smoke.summary_line(evidence) == (
        "cx_grounded_generation_live_postgres=pass db=nex_cx_test "
        "generation=COMPLETED model=Qwen3.5-4B provider_calls=1"
    )


def test_bounded_execution_and_configuration_failures(monkeypatch) -> None:
    _patch_database(monkeypatch)

    def staged(**_kwargs):
        raise smoke.LiveRagSmokeStageError(
            stage="generation",
            error_code="safe_generation_failure",
            detail="Bounded failure.",
            status_code=502,
            retryable=False,
            stage_status={"generation": "FAIL"},
        )

    failed = smoke.run_cx_grounded_generation_live_postgres_smoke(
        _live_env(),
        executor=staged,
    )
    assert failed["failure_code"] == "execution_failed"
    assert failed["diagnostics"]["stage"] == "generation"
    assert smoke.summary_line(failed).endswith("stage=generation")

    generic = smoke.run_cx_grounded_generation_live_postgres_smoke(
        _live_env(),
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert generic["detail"] == "RuntimeError"
    assert smoke.summary_line(generic).endswith("stage=unknown")

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad target")),
    )
    invalid = smoke.run_cx_grounded_generation_live_postgres_smoke(_live_env())
    assert invalid["failure_code"] == "configuration_invalid"


def test_retrieval_package_payload_headers_and_static_store() -> None:
    package = smoke._retrieval_package()
    store = smoke.StaticRetrievalPackageStore(package)
    loaded = store.get_retrieval_package(smoke.RETRIEVAL_PACKAGE_ID)
    assert loaded == package
    assert loaded is not package
    assert store.get_retrieval_package("missing") is None

    payload = smoke._generation_payload()
    assert payload["execution_mode"] == "GROUNDED_ANSWER"
    assert payload["retrieval_package_ref"]["package_hash"] == "9" * 64
    assert payload["selected_evidence_ids"] == [smoke.EVIDENCE_ID]
    assert payload["reasoning_mode"] == "disabled"
    assert payload["max_output_tokens"] == 128

    without_key = smoke._headers(smoke.OWNER_ID)
    with_key = smoke._headers(
        smoke.OWNER_ID,
        idempotency_key=smoke.IDEMPOTENCY_KEY,
    )
    assert "Idempotency-Key" not in without_key
    assert with_key["Idempotency-Key"] == smoke.IDEMPOTENCY_KEY
    context = smoke._smoke_access_context()
    assert context.caller_service_id == "nex-ae-api"
    assert context.ownership_key == (smoke.TENANT_ID, smoke.OWNER_ID)


def test_safe_observations_and_checks_cover_success_and_failure() -> None:
    observation = smoke._safe_generation_observation(
        {
            "cx_generation_id": "generation-1",
            "status": "COMPLETED",
        },
        {
            "cx_generation_id": "generation-1",
            "status": "COMPLETED",
        },
        {
            "metadata": {
                "read_model_schema_version": "cx_generation_read_model.v1",
                "content_ref": {"content_sha256": "a" * 64},
            },
            "content": {
                "content_schema_version": "cx_generation_content.v1",
                "content_sha256": "a" * 64,
                "size_bytes": 12,
                "owner_scope_enforced": True,
            },
        },
        {"model_revision": smoke.EXPECTED_GENERATION_MODEL},
    )
    assert observation["content_hash_matches"] is True
    assert smoke._safe_generation_observation({}, {}, {"metadata": {}, "content": {}}, None)[
        "provider_model"
    ] is None

    provider = smoke._safe_provider_observation(
        {
            "data": [
                "ignored",
                {"capability": "embedding", "success_count": 9},
                {
                    "capability": "generation",
                    "success_count": 1,
                    "failure_count": 0,
                },
            ]
        }
    )
    assert provider == {"success_count": 1, "failure_count": 0}
    assert smoke._safe_provider_observation({}) == {
        "success_count": 0,
        "failure_count": 0,
    }

    checks = smoke._checks(
        identity={"database": "nex_cx_test", "role": "nex_cx_user"},
        generation=observation,
        owner_isolation={"metadata_status_code": 404, "content_status_code": 404},
        provider=provider,
        database={
            "execution_count": 1,
            "execution_status": "COMPLETED",
            "owner_subject_ref_id": smoke.OWNER_ID,
            "output_sha256": "a" * 64,
            "output_size_bytes": 12,
            "admission_count": 1,
            "admission_status": "COMPLETED",
            "retrieval_package_count": 1,
        },
        events={"completed_count": 1, "replayed_count": 1, "metadata_only": True},
    )
    assert all(checks.values())
    failed = smoke._checks(
        identity={},
        generation={},
        owner_isolation={},
        provider={},
        database={},
        events={},
    )
    assert not any(failed.values())


def test_evidence_redaction_and_secret_helpers() -> None:
    env = _live_env()
    smoke.assert_evidence_redacted({"safe": True}, env)

    for private_value in (
        smoke.PRIVATE_EVIDENCE_MARKER,
        smoke.PRIVATE_PROMPT_MARKER,
    ):
        with pytest.raises(ValueError, match="private grounded content"):
            smoke.assert_evidence_redacted({"value": private_value}, env)
    with pytest.raises(ValueError, match="storage location"):
        smoke.assert_evidence_redacted({"value": "cx-private://hidden"}, env)
    with pytest.raises(ValueError, match="storage location"):
        smoke.assert_evidence_redacted({"value": "nex-cx-s97-live-hidden"}, env)
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "generation-secret"}, env)
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"value": "db-secret"}, env)

    assert smoke._secret_fragment("X", None) is None
    assert smoke._secret_fragment("X", "abc") is None
    assert smoke._secret_fragment("X", "abcd") == "abcd"
    assert smoke._secret_fragment("NEX_CX_TEST_DATABASE_URL", "sqlite:///tmp") is None
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL",
        "postgresql://user:x@localhost/db",
    ) is None
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL",
        "postgresql://user@localhost/db",
    ) is None
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL",
        "postgresql://user:secret@localhost/db",
    ) == "secret"
    assert smoke._secret_fragment(
        "NEX_CX_TEST_DATABASE_URL",
        "user:secret@localhost/db",
    ) == "secret"


def test_missing_configuration_accepts_explicit_chat_url() -> None:
    env = _live_env(NEX_MO_VLLM_BASE_URL="")
    env["NEX_MO_VLLM_CHAT_COMPLETIONS_URL"] = (
        "http://dgx.test:9111/v1/chat/completions"
    )
    assert smoke._missing_configuration(env) == []
    assert smoke._failure("code", "detail", profile="test")["detail"] == "detail"


def test_main_prints_summary_and_writes_output(monkeypatch, tmp_path, capsys) -> None:
    skipped = {"status": "SKIPPED", "smoke_schema_version": smoke.SCHEMA_VERSION}
    monkeypatch.setattr(
        smoke,
        "run_cx_grounded_generation_live_postgres_smoke",
        lambda: skipped,
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert '"status": "SKIPPED"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_cx_grounded_generation_live_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "failed"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
