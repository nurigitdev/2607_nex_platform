from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_s136_permission_hybrid_live_postgres_smoke as smoke


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
        **smoke.protected_dgx_vllm_profile_defaults(),
        **overrides,
    }


def _execution(**overrides: object) -> dict[str, object]:
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
            for capability, model in smoke.DEFAULT_MODELS.items()
        },
        "lifecycle": {
            "ready_status": "READY",
            "low_confidence_status": "LOW_CONFIDENCE",
            "no_answer_status": "NO_ANSWER",
        },
        "checks": {"end_to_end": True},
        "failed_checks": [],
        **overrides,
    }


def _patch_database(monkeypatch) -> None:
    migration = SimpleNamespace(planned=("1350",), applied=(), skipped=("1350",))
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


def test_activation_configuration_and_database_guards(monkeypatch) -> None:
    skipped = smoke.run_s136_permission_hybrid_live_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    profile = smoke.run_s136_permission_hybrid_live_postgres_smoke(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert profile["failure_code"] == "profile_not_allowed"

    invalid = _live_env(NEX_MO_REMOTE_RERANKER_API_KEY="")
    result = smoke.run_s136_permission_hybrid_live_postgres_smoke(invalid)
    assert result["failure_code"] == "configuration_invalid"
    assert result["detail"] == [
        {
            "error_code": "configuration_missing",
            "field": "NEX_MO_REMOTE_RERANKER_API_KEY",
        }
    ]

    monkeypatch.setattr(smoke, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: "postgresql://wrong@localhost/dev",
    )
    target = smoke.run_s136_permission_hybrid_live_postgres_smoke(_live_env())
    assert target["failure_code"] == "target_not_allowed"


def test_configuration_accepts_model_change_and_rejects_missing_model_or_shape_drift() -> None:
    issues = smoke._configuration_issues(
        _live_env(
            NEX_MO_REMOTE_EMBEDDING_MODEL="replacement-embedding",
            NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE="legacy",
        )
    )
    assert issues == [
        {
            "error_code": "configuration_mismatch",
            "field": "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE",
        },
    ]
    assert smoke._configuration_issues(
        _live_env(NEX_MO_REMOTE_EMBEDDING_MODEL="")
    ) == [
        {
            "error_code": "configuration_missing",
            "field": "NEX_MO_REMOTE_EMBEDDING_MODEL",
        }
    ]


def test_success_builds_redacted_production_live_evidence(monkeypatch) -> None:
    _patch_database(monkeypatch)
    calls: list[dict[str, object]] = []

    def executor(**kwargs):
        calls.append(kwargs)
        return _execution()

    result = smoke.run_s136_permission_hybrid_live_postgres_smoke(
        _live_env(),
        executor=executor,
    )

    assert result["status"] == "PASS"
    assert result["provider_path"] == "cx_production_runtime_to_mo_live_alias"
    assert result["migration"] == {
        "planned_count": 1,
        "applied_count": 0,
        "skipped_count": 1,
    }
    assert calls[0]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert calls[0]["runtime_environ"]["NEX_MO_PROVIDER_MODE"] == "live"
    assert "db-secret" not in str(result)
    assert "embedding-secret" not in str(result)
    assert smoke.summary_line(result) == (
        "s136_permission_hybrid_live_postgres=pass checks=1/1 "
        "decisions=READY/LOW_CONFIDENCE/NO_ANSWER "
        "database=nex_cx_test providers=embedding,reranking"
    )


def test_failed_checks_and_exceptions_are_bounded(monkeypatch) -> None:
    _patch_database(monkeypatch)
    failed = smoke.run_s136_permission_hybrid_live_postgres_smoke(
        _live_env(),
        executor=lambda **_kwargs: _execution(
            checks={"live": False},
            failed_checks=["live"],
        ),
    )
    assert failed["failure_code"] == "live_acceptance_failed"
    assert failed["execution"]["failed_checks"] == ["live"]

    generic = smoke.run_s136_permission_hybrid_live_postgres_smoke(
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
    invalid = smoke.run_s136_permission_hybrid_live_postgres_smoke(_live_env())
    assert invalid["failure_code"] == "configuration_invalid"
    assert invalid["detail"] == "ValueError"


def test_provider_target_storage_headers_and_redaction_helpers(tmp_path) -> None:
    telemetry = {
        "data": [
            {
                "capability": capability,
                "model_revision": model,
                "success_count": index + 1,
                "failure_count": index,
            }
            for index, (capability, model) in enumerate(
                smoke.DEFAULT_MODELS.items()
            )
        ]
    }
    observation = smoke._provider_observation(telemetry)
    assert observation["embedding"]["model"] == "Qwen3-Embedding-4B"
    assert smoke._provider_counts(telemetry) == {
        "embedding": (1, 0),
        "reranking": (2, 1),
    }
    assert smoke._provider_observation({})["reranking"] == {
        "model": None,
        "success_count": 0,
        "failure_count": 0,
    }

    storage = smoke._storage_config(tmp_path)
    assert storage.chunk_policy == "chunk_1000_100"
    assert storage.bm25_tokenizer == "mecab_ko"
    headers = smoke._headers("request", "1" * 32, smoke.OWNER_ID)
    assert headers["X-NEX-Tenant-ID"] == smoke.TENANT_ID
    assert headers["X-NEX-Subject-ID"] == smoke.OWNER_ID
    assert smoke._target_url_allowed(_live_env()["NEX_CX_TEST_DATABASE_URL"])
    assert not smoke._target_url_allowed("postgresql://wrong@localhost/dev")
    assert not smoke._target_url_allowed("postgresql://%zz")
    assert not smoke._target_url_allowed("postgresql://nex_cx_user@[::1")
    assert smoke._digest("stable") == smoke._digest("stable")

    smoke._assert_redacted({"safe": True}, _live_env())
    with pytest.raises(ValueError, match="protected value"):
        smoke._assert_redacted({"value": smoke.SOURCE_MARKER}, _live_env())
    with pytest.raises(ValueError, match="protected value"):
        smoke._assert_redacted({"value": "db-secret"}, _live_env())
    smoke._assert_redacted(
        {"safe": True},
        _live_env(NEX_CX_TEST_DATABASE_URL="postgresql://nex_cx_user@[::1"),
    )


def test_multisignal_dataset_and_sample_collection_helpers(tmp_path) -> None:
    dataset = smoke._load_calibration_dataset(smoke.CALIBRATION_DATASET_PATH)
    assert len(dataset["calibration_cases"]) == 20

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset"):
        smoke._load_calibration_dataset(malformed)

    duplicate = json.loads(json.dumps(dataset))
    duplicate["calibration_cases"][1]["case_id"] = duplicate[
        "calibration_cases"
    ][0]["case_id"]
    malformed.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="case"):
        smoke._load_calibration_dataset(malformed)

    class Response:
        status_code = 200

        def __init__(self, package_id: str) -> None:
            self.package_id = package_id

        def json(self):
            return {
                "retrieval_package_id": self.package_id,
                "retrieval_profile": {
                    "embedding_profile": {
                        "model_revision": smoke.DEFAULT_MODELS["embedding"]
                    },
                    "reranker_profile": {
                        "model_revision": smoke.DEFAULT_MODELS["reranking"]
                    },
                },
                "evidence_items": [
                    {
                        "rank": 1,
                        "scores": {
                            "rerank_score": 0.9,
                            "rrf_normalized_score": 1.0,
                            "channel_support_score": 1.0,
                        },
                    }
                ],
            }

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            return Response(f"package-{self.calls}")

    samples, bindings, package_ids = smoke._collect_calibration_samples(
        Client(),  # type: ignore[arg-type]
        cases=dataset["calibration_cases"][:2],
        document_id="document-one",
        probe="probe",
        trace_id="1" * 32,
    )
    assert [sample["score"] for sample in samples] == [0.88, 0.88]
    assert bindings == {
        (
            smoke.DEFAULT_MODELS["embedding"],
            smoke.DEFAULT_MODELS["reranking"],
        )
    }
    assert package_ids == ["package-1", "package-2"]

    class PayloadClient:
        def __init__(self, payload=None, *, status_code: int = 200) -> None:
            self.payload = payload or {}
            self.status_code = status_code

        def post(self, *_args, **_kwargs):
            return SimpleNamespace(
                status_code=self.status_code,
                json=lambda: self.payload,
            )

    case = dataset["calibration_cases"][:1]
    with pytest.raises(ValueError, match="request failed"):
        smoke._collect_calibration_samples(
            PayloadClient(status_code=503),  # type: ignore[arg-type]
            cases=case,
            document_id="document-one",
            probe="probe",
            trace_id="1" * 32,
        )
    with pytest.raises(ValueError, match="evidence"):
        smoke._collect_calibration_samples(
            PayloadClient({"evidence_items": []}),  # type: ignore[arg-type]
            cases=case,
            document_id="document-one",
            probe="probe",
            trace_id="1" * 32,
        )

    payload = Response("package-one").json()
    payload["retrieval_package_id"] = ""
    with pytest.raises(ValueError, match="package ID"):
        smoke._collect_calibration_samples(
            PayloadClient(payload),  # type: ignore[arg-type]
            cases=case,
            document_id="document-one",
            probe="probe",
            trace_id="1" * 32,
        )

    payload = Response("package-one").json()
    payload["retrieval_profile"] = {}
    samples, bindings, package_ids = smoke._collect_calibration_samples(
        PayloadClient(payload),  # type: ignore[arg-type]
        cases=case,
        document_id="document-one",
        probe="probe",
        trace_id="1" * 32,
    )
    assert len(samples) == 1
    assert bindings == set()
    assert package_ids == ["package-one"]


def test_summary_failure_and_main_paths(monkeypatch, tmp_path, capsys) -> None:
    failed = {"status": "FAIL", "failure_code": "boom"}
    assert smoke.summary_line(failed).endswith("error=boom")
    assert smoke.summary_line({}).endswith("error=unknown")

    skipped = {"status": "SKIPPED", "smoke_schema_version": smoke.SCHEMA_VERSION}
    monkeypatch.setattr(
        smoke,
        "run_s136_permission_hybrid_live_postgres_smoke",
        lambda: skipped,
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert '"status": "SKIPPED"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_s136_permission_hybrid_live_postgres_smoke",
        lambda: failed,
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
