from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_gb2_s20qe_v3_calibration_collection as smoke


def _live_env(**overrides: str) -> dict[str, str]:
    return {
        **smoke.protected_dgx_vllm_profile_defaults(),
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:db-secret@localhost/nex_cx_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.test:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        **overrides,
    }


def _execution(**overrides: object) -> dict[str, object]:
    return {
        "database_identity": {
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
        },
        "dataset": {
            "dataset_id": "s136-retrieval-package-confidence-public-v3",
            "partition": smoke.CALIBRATION_PARTITION,
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "collection": {"sample_count": 40},
        "feature_diagnostics": {"status": "DIAGNOSED"},
        "checks": {"end_to_end": True},
        "failed_checks": [],
        **overrides,
    }


def _patch_database(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _package() -> dict[str, object]:
    revision = _live_env()["NEX_MO_REMOTE_RERANKER_MODEL_REVISION"]
    return {
        "retrieval_profile": {
            "embedding_profile": {"model_revision": "Qwen3-Embedding-4B"},
            "reranker_profile": {"model_revision": revision},
            "quality_policy": {"policy_id": "weighted_rrf_vector_bm25_v1"},
            "bm25_tokenizer_profile": {
                "requested": "mecab_ko",
                "effective": "mecab_ko",
            },
            "chunk_policy": "chunk_1000_100",
        },
        "evidence_items": [
            {
                "content_object_id": f"document-{rank}",
                "rank": rank,
                "scores": {
                    "bm25_rank": rank,
                    "vector_rank": rank,
                    "rrf_normalized_score": 1.0 - rank * 0.1,
                    "channel_support_score": 1.0,
                    "rerank_score": 1.0 - rank * 0.1,
                },
                "text": "must not be projected",
            }
            for rank in range(1, 5)
        ],
    }


def test_activation_configuration_target_and_bounded_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skipped = smoke.run_gb2_s20qe_v3_calibration_collection({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("skipped")

    disallowed = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert disallowed["failure_code"] == "profile_not_allowed"

    invalid = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(NEX_MO_REMOTE_RERANKER_API_KEY="")
    )
    assert invalid["failure_code"] == "configuration_invalid"
    assert invalid["detail"] == [
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
    target = smoke.run_gb2_s20qe_v3_calibration_collection(_live_env())
    assert target["failure_code"] == "target_not_allowed"

    _patch_database(monkeypatch)
    failed = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(),
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert failed["failure_code"] == "execution_failed"
    assert failed["detail"] == {"exception": "RuntimeError", "error_code": None}


def test_success_projection_failed_checks_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_database(monkeypatch)
    calls: list[dict[str, object]] = []

    def executor(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return _execution()

    result = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(), executor=executor
    )
    assert result["status"] == "PASS"
    assert result["migration"] == {
        "planned_count": 1,
        "applied_count": 0,
        "skipped_count": 1,
    }
    assert result["provider_path"] == "cx_production_runtime_to_mo_live_alias"
    assert calls[0]["runtime_environ"]["NEX_MO_PROVIDER_MODE"] == "live"  # type: ignore[index]
    assert calls[0]["repeat_count"] == 1
    assert "samples=40 diagnostics=DIAGNOSED holdout=sealed" in smoke.summary_line(
        result
    )
    serialized = json.dumps(result)
    assert "db-secret" not in serialized
    assert "embedding-secret" not in serialized
    assert "reranker-secret" not in serialized

    failed = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(),
        executor=lambda **_kwargs: _execution(
            checks={"holdout": False}, failed_checks=["holdout"]
        ),
    )
    assert failed["failure_code"] == "live_collection_failed"
    assert failed["execution"]["failed_checks"] == ["holdout"]

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted({"leak": "reranker-secret"}, _live_env())


def test_v3_partition_selection_keeps_holdout_out_of_collection() -> None:
    dataset = smoke._load_dataset(smoke.DEFAULT_V3_PATH)
    calibration, holdout_values = smoke._calibration_cases(dataset)

    assert len(calibration) == 40
    assert len({case["scenario_id"] for case in calibration}) == 20
    assert all(case["partition"] == "CALIBRATION" for case in calibration)
    assert len(holdout_values) == 100
    assert not any(case["query"] in holdout_values for case in calibration)

    crossed = deepcopy(dataset)
    scenario = crossed["cases"][0]["scenario_id"]
    partner = next(
        case
        for case in crossed["cases"][1:]
        if case["scenario_id"] == scenario
    )
    partner["partition"] = "HOLDOUT"
    with pytest.raises(ValueError, match="crossed partitions"):
        smoke._calibration_cases(crossed)

    malformed = deepcopy(dataset)
    malformed["cases"][0] = "bad"
    with pytest.raises(TypeError, match="case is invalid"):
        smoke._calibration_cases(malformed)


def test_dataset_loader_and_configuration_shape_guards(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "dataset_schema_version": "wrong",
                "dataset_id": "dataset",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dataset is invalid"):
        smoke._load_dataset(invalid)

    issues = smoke._configuration_issues(
        _live_env(NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE="wrong")
    )
    assert issues == [
        {
            "error_code": "configuration_mismatch",
            "field": "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE",
        }
    ]

    invalid_repeat = smoke.run_gb2_s20qe_v3_calibration_collection(
        _live_env(**{smoke.REPEAT_COUNT_ENV: "6"})
    )
    assert invalid_repeat == {
        "evidence_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "configuration_invalid",
        "detail": smoke.REPEAT_COUNT_ENV,
    }


def test_repeat_projection_is_integrity_bound_and_count_is_bounded() -> None:
    observation = {
        "sample_id": "scenario:positive",
        "rank": 1,
        "observation_hash": "sha256:" + "a" * 64,
    }
    sample = {"sample_id": "scenario:positive", "sample_hash": "sha256:" + "b" * 64}
    projected = smoke._repeat_run_projection(
        repeat_index=0,
        samples=[sample],
        observations=[observation],
    )
    assert projected["repeat_index"] == 0
    assert projected["candidate_observation_count"] == 1
    assert str(projected["run_hash"]).startswith("sha256:")
    assert smoke._repeat_count("5") == 5
    for invalid in (True, "0", "1.0", "bad"):
        with pytest.raises((TypeError, ValueError), match="repeat count"):
            smoke._repeat_count(invalid)


def test_holdout_request_guard_counts_safe_calls_and_blocks_leaks() -> None:
    calls: list[tuple[str, str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> str:
        calls.append((method, url, kwargs.get("json")))
        return "response"

    guarded, counts = smoke._holdout_guarded_requester(
        requester,
        holdout_values=("sealed query", "sealed candidate"),
        environ=_live_env(),
    )
    assert guarded(
        "POST",
        _live_env()["NEX_MO_REMOTE_EMBEDDING_URL"],
        json={"input": ["calibration text"]},
    ) == "response"
    assert counts == {
        "total": 1,
        "embedding": 1,
        "reranking": 0,
        "holdout_blocked": 0,
    }

    with pytest.raises(ValueError, match="holdout content"):
        guarded(
            "POST",
            _live_env()["NEX_MO_REMOTE_RERANKER_URL"],
            json={"query": "sealed query"},
        )
    assert counts["holdout_blocked"] == 1
    assert len(calls) == 1


def test_numeric_evidence_and_feature_binding_are_complete_and_text_free() -> None:
    package = _package()
    mapping = {f"document-{rank}": f"candidate-{rank}" for rank in range(1, 5)}
    evidence = smoke._numeric_mixed_evidence(package, mapping)

    assert [item["candidate_id"] for item in evidence] == [
        "candidate-1",
        "candidate-2",
        "candidate-3",
        "candidate-4",
    ]
    assert "must not be projected" not in str(evidence)
    binding = smoke._feature_binding(package, _live_env())
    assert binding["embedding_model_revision"] == "Qwen3-Embedding-4B"
    assert binding["reranker_model_revision"].startswith("hf:")
    assert binding["tokenizer_policy_id"].startswith(
        smoke.TOKENIZER_POLICY_PREFIX + "sha256:"
    )

    missing = deepcopy(package)
    missing["evidence_items"].pop()
    with pytest.raises(ValueError, match="exactly four"):
        smoke._numeric_mixed_evidence(missing, mapping)

    escaped = deepcopy(package)
    escaped["evidence_items"][0]["content_object_id"] = "other"
    with pytest.raises(ValueError, match="escaped"):
        smoke._numeric_mixed_evidence(escaped, mapping)

    drift = deepcopy(package)
    drift["retrieval_profile"]["reranker_profile"]["model_revision"] = "wrong"
    with pytest.raises(ValueError, match="binding drifted"):
        smoke._feature_binding(drift, _live_env())


def test_summary_failure_and_main_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert "error=broken" in smoke.summary_line(smoke._failure("broken"))
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qe_v3_calibration_collection",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "SKIPPED"}
