from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_gb2_s20q_multisignal_live_holdout as smoke
from nex_cx.retrieval_confidence_multisignal import (
    build_multisignal_feature_package,
    evaluate_multisignal_calibration,
)

RERANKER_REVISION = "hf:" + "2" * 40


def _live_env(**overrides: str) -> dict[str, str]:
    return {
        **smoke.protected_dgx_vllm_profile_defaults(),
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:db-secret@localhost/nex_cx_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": ("http://dgx.test:9112/v1/embeddings"),
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": RERANKER_REVISION,
        **overrides,
    }


def _execution(**overrides: object) -> dict[str, object]:
    return {
        "database_identity": {
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
        },
        "dataset": {
            "dataset_id": "s136-reranker-relevance-public-v2",
            "pair_count": 120,
        },
        "calibration": {
            "status": "PASSED",
            "selected_threshold": 0.7,
            "sample_count": 40,
        },
        "holdout": {"status": "PASSED", "sample_count": 20},
        "profile": {"status": "ACTIVE"},
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


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "Qwen3-Embedding-4B",
        "reranker_model_revision": RERANKER_REVISION,
        "ranking_policy_id": "cx_hybrid_rrf_v1",
        "tokenizer_policy_id": "cx-tokenizer-profile:sha256:" + "a" * 64,
        "chunk_policy_id": "chunk_1000_100",
    }


def _feature_package(*, ready: bool) -> dict[str, object]:
    if ready:
        scores = (0.95, 0.75, 0.95, 1.0)
    else:
        scores = (0.2, 0.15, 0.2, 0.5)
    top, second, rrf, channel = scores
    return build_multisignal_feature_package(
        [
            {
                "rank": 1,
                "scores": {
                    "bm25_rank": 1,
                    "vector_rank": 1,
                    "rrf_normalized_score": rrf,
                    "channel_support_score": channel,
                    "rerank_score": top,
                },
            },
            {
                "rank": 2,
                "scores": {
                    "bm25_rank": 2,
                    "vector_rank": 2,
                    "rrf_normalized_score": max(0.0, rrf - 0.1),
                    "channel_support_score": channel,
                    "rerank_score": second,
                },
            },
        ],
        binding=_binding(),
    )


def _holdout_samples() -> list[dict[str, object]]:
    return [
        {
            "sample_id": f"sample-{index}",
            "expected_ready": index < 10,
            "feature_package": _feature_package(ready=index < 10),
        }
        for index in range(20)
    ]


def _retrieval_package() -> dict[str, object]:
    return {
        "retrieval_profile": {
            "embedding_profile": {"model_revision": "Qwen3-Embedding-4B"},
            "reranker_profile": {"model_revision": RERANKER_REVISION},
            "quality_policy": {"policy_id": "cx_hybrid_rrf_v1"},
            "bm25_tokenizer_profile": {
                "requested": "mecab_ko",
                "effective": "mecab_ko",
            },
            "chunk_policy": "chunk_1000_100",
        },
        "evidence_items": [
            {
                "rank": 1,
                "scores": {
                    "bm25_rank": 1,
                    "vector_rank": 1,
                    "rrf_normalized_score": 1.0,
                    "channel_support_score": 1.0,
                    "rerank_score": 0.9,
                },
                "private_text": "must not be projected",
            },
            {
                "rank": 2,
                "scores": {
                    "bm25_rank": 2,
                    "vector_rank": 2,
                    "rrf_normalized_score": 0.9,
                    "channel_support_score": 1.0,
                    "rerank_score": 0.7,
                },
            },
        ],
    }


def test_activation_configuration_database_and_redaction_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skipped = smoke.run_gb2_s20q_multisignal_live_holdout({})
    assert skipped["status"] == "SKIPPED"
    assert "skipped" in smoke.summary_line(skipped)

    disallowed = smoke.run_gb2_s20q_multisignal_live_holdout(
        _live_env(**{smoke.PROFILE_ENV: "dev"})
    )
    assert disallowed["failure_code"] == "profile_not_allowed"

    invalid = smoke.run_gb2_s20q_multisignal_live_holdout(
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
    target = smoke.run_gb2_s20q_multisignal_live_holdout(_live_env())
    assert target["failure_code"] == "target_not_allowed"

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "reranker-secret"},
            _live_env(),
        )


def test_success_failed_checks_and_bounded_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_database(monkeypatch)
    calls: list[dict[str, object]] = []

    def executor(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return _execution()

    result = smoke.run_gb2_s20q_multisignal_live_holdout(_live_env(), executor=executor)
    assert result["status"] == "PASS"
    assert result["migration"] == {
        "planned_count": 1,
        "applied_count": 0,
        "skipped_count": 1,
    }
    assert result["provider_path"] == "cx_production_runtime_to_mo_live_alias"
    assert calls[0]["runtime_environ"]["NEX_MO_PROVIDER_MODE"] == "live"  # type: ignore[index]
    serialized = json.dumps(result)
    assert "db-secret" not in serialized
    assert "embedding-secret" not in serialized
    assert "reranker-secret" not in serialized
    assert "holdout=PASSED" in smoke.summary_line(result)

    failed = smoke.run_gb2_s20q_multisignal_live_holdout(
        _live_env(),
        executor=lambda **_kwargs: _execution(
            checks={"holdout": False}, failed_checks=["holdout"]
        ),
    )
    assert failed["failure_code"] == "live_acceptance_failed"
    assert failed["execution"]["failed_checks"] == ["holdout"]

    generic = smoke.run_gb2_s20q_multisignal_live_holdout(
        _live_env(),
        executor=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert generic["failure_code"] == "execution_failed"
    assert generic["detail"] == {
        "exception": "RuntimeError",
        "error_code": None,
    }

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("private")),
    )
    invalid = smoke.run_gb2_s20q_multisignal_live_holdout(_live_env())
    assert invalid["failure_code"] == "configuration_invalid"


def test_frozen_dataset_partitions_and_malformed_variants() -> None:
    dataset = smoke._load_dataset(smoke.DEFAULT_V2_PATH)
    partitions = smoke._partition_cases(dataset)
    assert len(partitions[smoke.CALIBRATION_PARTITION]) == 20
    assert len(partitions[smoke.HOLDOUT_PARTITION]) == 10
    assert not (
        {item["case_id"] for item in partitions[smoke.CALIBRATION_PARTITION]}
        & {item["case_id"] for item in partitions[smoke.HOLDOUT_PARTITION]}
    )

    path = smoke.DEFAULT_V2_PATH
    with pytest.raises(FileNotFoundError):
        smoke._load_dataset(path.with_name("missing.json"))

    duplicate = deepcopy(dataset)
    duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
    with pytest.raises(ValueError, match="case is invalid"):
        smoke._partition_cases(duplicate)

    labels = deepcopy(dataset)
    labels["cases"][0]["documents"][0]["expected_ready"] = False
    with pytest.raises(ValueError, match="labels are invalid"):
        smoke._partition_cases(labels)

    count = deepcopy(dataset)
    count["cases"][0]["partition"] = smoke.HOLDOUT_PARTITION
    with pytest.raises(ValueError, match="partitions are invalid"):
        smoke._partition_cases(count)

    malformed_case = deepcopy(dataset)
    malformed_case["cases"][0] = "bad"
    with pytest.raises(ValueError, match="case is invalid"):
        smoke._partition_cases(malformed_case)


def test_load_dataset_rejects_invalid_file(tmp_path: Path) -> None:
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


def test_feature_binding_and_numeric_evidence_are_minimal_and_stable() -> None:
    package = _retrieval_package()
    binding = smoke._feature_binding(package, _live_env())
    assert binding["reranker_model_revision"] == RERANKER_REVISION
    assert binding["tokenizer_policy_id"].startswith(
        smoke.TOKENIZER_POLICY_PREFIX + "sha256:"
    )

    numeric = smoke._numeric_evidence(package)
    assert numeric == [
        {"rank": 1, "scores": package["evidence_items"][0]["scores"]},  # type: ignore[index]
        {"rank": 2, "scores": package["evidence_items"][1]["scores"]},  # type: ignore[index]
    ]
    assert "private_text" not in numeric[0]

    drift = deepcopy(package)
    drift["retrieval_profile"]["reranker_profile"]["model_revision"] = "wrong"  # type: ignore[index]
    with pytest.raises(ValueError, match="binding drifted"):
        smoke._feature_binding(drift, _live_env())

    no_tokenizer = deepcopy(package)
    no_tokenizer["retrieval_profile"]["bm25_tokenizer_profile"] = {}  # type: ignore[index]
    with pytest.raises(ValueError, match="binding drifted"):
        smoke._feature_binding(no_tokenizer, _live_env())

    with pytest.raises(ValueError, match="exactly two"):
        smoke._numeric_evidence({"evidence_items": []})
    with pytest.raises(ValueError, match="score package"):
        smoke._numeric_evidence({"evidence_items": ["bad", "bad"]})


def test_freeze_then_fixed_threshold_holdout_without_reselection() -> None:
    samples = _holdout_samples()
    calibration = evaluate_multisignal_calibration(
        samples,
        dataset_id="dataset-v2",
        dataset_sha256="a" * 64,
        expected_binding=_binding(),
    )
    assert calibration["status"] == "PASSED"
    freeze = smoke._freeze_calibration(calibration)
    assert freeze["status"] == "FROZEN"
    assert freeze["threshold_reselection_allowed"] is False
    selected_freeze = smoke._freeze_calibration(
        calibration,
        weight_selection_hash="sha256:" + "c" * 64,
    )
    assert selected_freeze["weight_selection_hash"] == "sha256:" + "c" * 64
    assert selected_freeze["weights"] == calibration["weights"]

    holdout = smoke._evaluate_holdout(
        samples=samples,
        dataset_id="dataset-v2",
        threshold=freeze["threshold"],
        expected_binding=_binding(),
    )
    assert holdout["status"] == "PASSED"
    assert holdout["threshold"] == freeze["threshold"]
    assert holdout["dataset_id"] == "dataset-v2:holdout"

    rejected = deepcopy(calibration)
    rejected["status"] = "NO_ACCEPTABLE_THRESHOLD"
    with pytest.raises(ValueError, match="did not pass"):
        smoke._freeze_calibration(rejected)

    incomplete = deepcopy(samples)
    incomplete[0]["feature_package"] = build_multisignal_feature_package(
        [], binding=_binding()
    )
    with pytest.raises(ValueError, match="incomplete"):
        smoke._evaluate_holdout(
            samples=incomplete,
            dataset_id="dataset-v2",
            threshold=0.5,
            expected_binding=_binding(),
        )


def test_projection_configuration_and_small_helpers() -> None:
    assert smoke._evaluation_projection({})["status"] is None
    assert smoke._holdout_projection({})["metrics"] is None
    assert smoke._profile_projection(None) == {"status": "NOT_ADMITTED"}
    assert (
        smoke._profile_projection(
            {
                "status": "ACTIVE",
                "profile_id": "profile",
                "profile_hash": "sha256:hash",
                "threshold": 0.7,
                "runtime_activation_permitted": True,
            }
        )["status"]
        == "ACTIVE"
    )

    issues = smoke._configuration_issues(
        _live_env(NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE="legacy")
    )
    assert issues == [
        {
            "error_code": "configuration_mismatch",
            "field": "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE",
        }
    ]
    assert smoke._mapping("bad") == {}
    with pytest.raises(ValueError, match="invalid"):
        smoke._required_string("", "field")
    assert smoke._required_string(" value ", "field") == "value"
    assert smoke._headers("request", "1" * 32)["X-NEX-Tenant-ID"] == (smoke.TENANT_ID)

    class Client:
        def post(self, path: str, **kwargs: object) -> dict[str, object]:
            return {"path": path, **kwargs}

    request = smoke._retrieve_scope(
        Client(),  # type: ignore[arg-type]
        query="private query",
        document_ids=("document-one", "document-two"),
        request_id="request",
        trace_id="1" * 32,
    )
    assert request["path"] == "/api/v1/retrieval/context"
    assert request["json"]["top_k"] == 2  # type: ignore[index]
    assert request["json"]["document_scope"]["document_ids"] == [  # type: ignore[index]
        "document-one",
        "document-two",
    ]


def test_summary_and_main(tmp_path: Path, monkeypatch, capsys) -> None:
    assert "error=unknown" in smoke.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20q_multisignal_live_holdout",
        lambda: _execution(status="PASS"),
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "multisignal_live_holdout=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20q_multisignal_live_holdout",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
