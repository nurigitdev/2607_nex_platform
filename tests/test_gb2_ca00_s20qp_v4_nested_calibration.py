from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_gb2_s20qp_v4_nested_calibration as smoke


def _env(**overrides: str) -> dict[str, str]:
    return {
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


def _source(**overrides: object) -> dict[str, object]:
    return {
        "evidence_schema_version": "source",
        "status": "PASS",
        "nested_selection": {
            "status": "NO_ADMISSIBLE_PROFILE",
            "oof_evaluation": {"stable_profile_id": None},
        },
        **overrides,
    }


def test_activation_delegates_to_protected_collector_and_redacts(monkeypatch) -> None:
    assert smoke.run_gb2_s20qp_v4_nested_calibration({})["status"] == "SKIPPED"
    assert smoke.run_gb2_s20qp_v4_nested_calibration(
        _env(**{smoke.PROFILE_ENV: "dev"})
    )["failure_code"] == "profile_not_allowed"

    calls = []

    def source_runner(environ, **kwargs):
        calls.append((environ, kwargs))
        return _source()

    monkeypatch.setattr(smoke.s20qe, "run_gb2_s20qe_v3_calibration_collection", source_runner)
    result = smoke.run_gb2_s20qp_v4_nested_calibration(_env())

    assert result["evidence_schema_version"] == smoke.SCHEMA_VERSION
    assert result["slice_id"] == "GB2-CA00-S20Q-P"
    assert calls[0][0][smoke.s20qe.REPEAT_COUNT_ENV] == "5"
    assert (
        calls[0][0]["NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION"]
        == smoke.INCUMBENT_EMBEDDING_REVISION
    )
    assert (
        calls[0][0]["NEX_MO_REMOTE_RERANKER_MODEL_REVISION"]
        == smoke.INCUMBENT_RERANKER_REVISION
    )
    assert callable(calls[0][1]["executor"])
    assert "selection=NO_ADMISSIBLE_PROFILE" in smoke.summary_line(result)
    serialized = json.dumps(result)
    assert "db-secret" not in serialized
    assert "embedding-secret" not in serialized


def test_activation_executor_and_cli_output(monkeypatch, tmp_path: Path, capsys) -> None:
    collected = []

    def source_runner(_environ, **kwargs):
        executed = kwargs["executor"](
            database_url="db",
            database_env="DB",
            runtime_environ={},
            requester=None,
            repeat_count=5,
        )
        return _source(nested_selection=executed)

    monkeypatch.setattr(smoke.s20qe, "run_gb2_s20qe_v3_calibration_collection", source_runner)
    result = smoke.run_gb2_s20qp_v4_nested_calibration(
        _env(),
        collector=lambda **kwargs: collected.append(kwargs)
        or {
            "status": "NO_ADMISSIBLE_PROFILE",
            "oof_evaluation": {"stable_profile_id": None},
        },
    )
    assert result["status"] == "PASS"
    assert collected[0]["selector"] is smoke.select_nested_retrieval_profile

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qp_v4_nested_calibration",
        lambda: _source(),
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert output.exists()
    assert "gb2_s20qp_v4_nested_calibration=pass" in capsys.readouterr().out
    assert smoke.main(["--summary"]) == 0
    assert "gb2_s20qp_v4_nested_calibration=pass" in capsys.readouterr().out


def test_v4_execution_composes_repeatability_and_nested_selection(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "check_retrieval_calibration_v4_dataset",
        lambda: {
            "status": "PASS",
            "dataset_id": "dataset-v4",
            "dataset_sha256": "dataset-sha",
        },
    )
    collection = {
        "failed_checks": [],
        "checks": {"source": True},
        "binding": {"binding": "value"},
        "dataset": {"holdout_status": "SEALED_NOT_COLLECTED"},
        "repeat_collection": {
            "runs": [{"candidate_observations": ["observation"]}]
        },
    }
    monkeypatch.setattr(smoke.s20qe, "_execute_live_collection", lambda **_kwargs: collection)
    monkeypatch.setattr(
        smoke,
        "analyze_retrieval_pipeline_repeatability",
        lambda *_args, **_kwargs: {
            "status": "STABLE",
            "measurement": {"repeat_count": 5},
        },
    )
    samples = [
        {"sample_id": f"sample-{index}", "sample_hash": f"hash-{index}"}
        for index in range(smoke.EXPECTED_CANDIDATES)
    ]
    for index, row in enumerate(samples):
        row["sample_id"] = f"package-{index // 4}"
    monkeypatch.setattr(
        smoke,
        "build_expanded_candidate_relevance_calibration_samples",
        lambda _rows: samples,
    )
    nested = {
        "status": "NO_ADMISSIBLE_PROFILE",
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
    }
    result = smoke._execute_v4_collection(
        database_url="postgresql://test",
        database_env="DB",
        runtime_environ={},
        requester=None,
        repeat_count=5,
        selector=lambda *_args, **_kwargs: nested,
    )

    assert result["failed_checks"] == []
    assert result["checks"]["nested_selection_completed_fail_closed"] is True
    assert result["calibration_admission"] == {
        "status": "REJECTED",
        "checks": {
            "pipeline_repeatability_stable": True,
            "nested_calibration_oof_admitted": False,
        },
        "holdout_eligible_for_separate_execution": False,
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    assert result["provenance"]["holdout_scores_collected"] is False
    assert str(result["provenance"]["candidate_sample_set_hash"]).startswith(
        "sha256:"
    )

    admitted_nested = {
        **nested,
        "status": "CALIBRATION_OOF_ADMITTED",
    }
    admitted = smoke._execute_v4_collection(
        database_url="postgresql://test",
        database_env="DB",
        runtime_environ={},
        requester=None,
        repeat_count=5,
        selector=lambda *_args, **_kwargs: admitted_nested,
    )
    assert admitted["calibration_admission"]["status"] == "ADMITTED"
    assert admitted["calibration_admission"][
        "holdout_eligible_for_separate_execution"
    ] is True
    assert admitted["calibration_admission"]["holdout_access_permitted"] is False

    monkeypatch.setattr(
        smoke,
        "analyze_retrieval_pipeline_repeatability",
        lambda *_args, **_kwargs: {
            "status": "UNSTABLE",
            "measurement": {"repeat_count": 5},
        },
    )
    unstable = smoke._execute_v4_collection(
        database_url="postgresql://test",
        database_env="DB",
        runtime_environ={},
        requester=None,
        repeat_count=5,
        selector=lambda *_args, **_kwargs: admitted_nested,
    )
    assert unstable["failed_checks"] == []
    assert unstable["calibration_admission"]["status"] == "REJECTED"


def test_v4_execution_guard_failures(monkeypatch) -> None:
    with pytest.raises(ValueError, match="repeat count"):
        smoke._execute_v4_collection(
            database_url="db",
            database_env="DB",
            runtime_environ={},
            requester=None,
            repeat_count=1,
            selector=lambda *_args, **_kwargs: {},
        )

    monkeypatch.setattr(
        smoke,
        "check_retrieval_calibration_v4_dataset",
        lambda: {"status": "PASS", "dataset_id": "id", "dataset_sha256": "sha"},
    )
    failed = {"failed_checks": ["source"], "checks": {"source": False}}
    monkeypatch.setattr(smoke.s20qe, "_execute_live_collection", lambda **_kwargs: failed)
    assert smoke._execute_v4_collection(
        database_url="db",
        database_env="DB",
        runtime_environ={},
        requester=None,
        repeat_count=5,
        selector=lambda *_args, **_kwargs: {},
    ) is failed

    monkeypatch.setattr(
        smoke.s20qe,
        "_execute_live_collection",
        lambda **_kwargs: {"failed_checks": [], "repeat_collection": {"runs": []}},
    )
    with pytest.raises(ValueError, match="collection is unavailable"):
        smoke._execute_v4_collection(
            database_url="db",
            database_env="DB",
            runtime_environ={},
            requester=None,
            repeat_count=5,
            selector=lambda *_args, **_kwargs: {},
        )


def test_v4_dataset_spec_and_redaction_guards(tmp_path: Path) -> None:
    dataset = smoke.s20qe._load_dataset(
        smoke.DEFAULT_DATASET_PATH,
        schema_version=smoke.V4_DATASET_SPEC.schema_version,
        expected_case_count=smoke.V4_DATASET_SPEC.case_count,
    )
    calibration, holdout_values = smoke.s20qe._calibration_cases(
        dataset, dataset_spec=smoke.V4_DATASET_SPEC
    )
    assert len(calibration) == smoke.EXPECTED_PACKAGES
    assert len(holdout_values) == 200

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": dataset["cases"][0]["query"]},
            _env(),
        )
    malformed = tmp_path / "not-object.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="object"):
        smoke._read_object(malformed)
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("skipped")
    assert "error=boom" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "boom"}
    )
