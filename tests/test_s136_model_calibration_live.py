from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_s136_model_calibration_live as smoke


def _env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        **smoke.protected_dgx_vllm_profile_defaults(),
        **overrides,
    }


def _response(scores: list[float], *, model: str = "Qwen3-Reranker-4B") -> dict:
    return {
        "model_revision": model,
        "results": [
            {"index": index, "score": score}
            for index, score in enumerate(scores)
        ],
    }


def test_skip_and_successful_candidate_profile(monkeypatch) -> None:
    skipped = smoke.run_s136_model_calibration_live({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda payload, **_kwargs: _response([0.9, 0.3, 0.1]),
    )
    result = smoke.run_s136_model_calibration_live(_env())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["evaluation"]["sample_count"] == 36
    assert result["evaluation"]["selected_threshold"] == 0.6
    assert result["candidate_profile"]["status"] == "CANDIDATE"
    assert result["candidate_profile"]["binding"] == {
        "capability": "reranking",
        "model_revision": "Qwen3-Reranker-4B",
        "request_shape": "rerank",
        "score_semantics": smoke.SCORE_SEMANTICS,
        "policy_id": smoke.POLICY_ID,
    }
    assert result["sample_scores_persisted"] is False
    assert "threshold=0.6" in smoke.summary_line(result)


def test_live_evaluation_fails_closed_for_bad_distribution_and_model_drift(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda payload, **_kwargs: _response([0.1, 0.9, 0.8]),
    )
    failed = smoke.run_s136_model_calibration_live(_env())
    assert failed["status"] == "FAIL"
    assert failed["failed_checks"] == ["evaluation_passed"]
    assert failed["candidate_profile"] is None
    assert smoke.summary_line(failed).endswith("checks=evaluation_passed")

    calls = 0

    def drifting(payload, **_kwargs):
        nonlocal calls
        calls += 1
        model = "Qwen3-Reranker-4B" if calls == 1 else "other-model"
        return _response([0.9, 0.3, 0.1], model=model)

    monkeypatch.setattr(smoke, "execute_remote_rerank_request", drifting)
    drifted = smoke.run_s136_model_calibration_live(_env())
    assert drifted["failed_checks"] == ["model_revision_stable"]


def test_collection_rejects_incomplete_provider_response(monkeypatch) -> None:
    dataset = smoke._load_dataset(smoke.DEFAULT_DATASET_PATH)
    broken = json.loads(json.dumps(dataset))
    broken["cases"][0]["documents"] = []
    with pytest.raises(ValueError, match="non-empty"):
        smoke._collect_samples(broken, environ=_env(), requester=None)

    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda payload, **_kwargs: _response([0.9]),
    )
    with pytest.raises(ValueError, match="every document"):
        smoke._collect_samples(dataset, environ=_env(), requester=None)

    broken = json.loads(json.dumps(dataset))
    broken["cases"][0]["documents"][0]["expected_ready"] = "yes"
    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda payload, **_kwargs: _response([0.9, 0.3, 0.1]),
    )
    with pytest.raises(ValueError, match="boolean"):
        smoke._collect_samples(broken, environ=_env(), requester=None)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dataset_schema_version": "bad", "dataset_id": "x", "cases": [1]},
        {
            "dataset_schema_version": "model_calibration_dataset.v1",
            "dataset_id": "x",
            "cases": [],
        },
    ],
)
def test_dataset_loader_rejects_invalid_shape(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset"):
        smoke._load_dataset(path)


def test_bounded_execution_failure_and_redaction_helpers(tmp_path: Path) -> None:
    missing = smoke.run_s136_model_calibration_live(
        _env(NEX_MO_REMOTE_RERANKER_URL="")
    )
    assert missing["status"] == "FAIL"
    assert missing["detail"] == "ValueError"

    assert smoke._safe_identifier("Model/A 4B") == "model-a-4b"
    with pytest.raises(ValueError, match="field"):
        smoke._required_string(" ", "field")
    smoke._assert_redacted({"safe": True}, _env(), smoke.DEFAULT_DATASET_PATH)
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"value": "reranker-secret"},
            _env(),
            smoke.DEFAULT_DATASET_PATH,
        )

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")
    result = smoke.run_s136_model_calibration_live(
        _env(),
        dataset_path=malformed,
    )
    assert result["status"] == "FAIL"
    assert result["detail"] == "JSONDecodeError"


def test_main_output_and_failure_paths(monkeypatch, tmp_path: Path, capsys) -> None:
    skipped = {"status": "SKIPPED"}
    monkeypatch.setattr(smoke, "run_s136_model_calibration_live", lambda **_kwargs: skipped)
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert '"status": "SKIPPED"' in output.read_text(encoding="utf-8")

    failed = {"status": "FAIL", "failed_checks": []}
    monkeypatch.setattr(smoke, "run_s136_model_calibration_live", lambda **_kwargs: failed)
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
    assert smoke.summary_line({}).endswith("checks=execution")
