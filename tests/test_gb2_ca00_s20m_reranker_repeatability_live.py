from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import run_gb2_s20m_reranker_repeatability_live as smoke

RERANKER_REVISION = "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5"


def _env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "protected-reranker-key",
        **smoke.protected_dgx_vllm_profile_defaults(),
        **overrides,
    }


def _response(
    scores: list[float] | None = None,
    *,
    model: str = RERANKER_REVISION,
    deployment: str = "vllm-reranker-http",
) -> dict:
    values = scores or [0.9, 0.7, 0.4, 0.1]
    return {
        "model_revision": model,
        "deployment_id": deployment,
        "results": [
            {"index": index, "score": score}
            for index, score in enumerate(values)
        ],
    }


def test_skip_and_stable_repeatability(monkeypatch) -> None:
    skipped = smoke.run_gb2_s20m_reranker_repeatability_live({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda _payload, **_kwargs: _response(),
    )
    result = smoke.run_gb2_s20m_reranker_repeatability_live(_env())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["dataset_binding"]["pair_count"] == 120
    assert result["repeatability"] == {
        "repeat_count": 2,
        "pair_coverage_complete": True,
        "observation_count": 240,
        "score_delta_tolerance": 0.000001,
        "max_absolute_score_delta": 0.0,
        "score_drift_pair_count": 0,
        "rank_inversion_count": 0,
        "rank_inversion_pair_ids": [],
        "non_finite_score_count": 0,
        "out_of_bounds_score_count": 0,
    }
    assert len(result["score_observations"]) == 240
    serialized = json.dumps(result, ensure_ascii=False)
    assert "http://dgx.test" not in serialized
    assert "protected-reranker-key" not in serialized
    assert "새 프로젝트를 생성" not in serialized
    assert "observations=240" in smoke.summary_line(result)


def test_score_and_rank_drift_fail_closed(monkeypatch) -> None:
    calls = 0

    def drifting(_payload, **_kwargs):
        nonlocal calls
        calls += 1
        scores = [0.9, 0.7, 0.4, 0.1]
        if calls > 30:
            scores = [0.7, 0.9, 0.4, 0.1]
        return _response(scores)

    monkeypatch.setattr(smoke, "execute_remote_rerank_request", drifting)
    result = smoke.run_gb2_s20m_reranker_repeatability_live(_env())

    assert result["status"] == "FAIL"
    assert result["failed_checks"] == [
        "score_repeatability",
        "rank_repeatability",
    ]
    assert result["repeatability"]["score_drift_pair_count"] == 60
    assert result["repeatability"]["rank_inversion_count"] == 60


@pytest.mark.parametrize(
    "response, failed_check",
    [
        (_response(model="different-model"), "model_revision_stable"),
        (_response(deployment="different-deployment"), "deployment_identity_stable"),
        (_response([math.nan, 0.7, 0.4, 0.1]), "scores_finite"),
        (_response([1.1, 0.7, 0.4, 0.1]), "scores_bounded"),
    ],
)
def test_identity_and_score_contracts_fail_closed(
    monkeypatch,
    response: dict,
    failed_check: str,
) -> None:
    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda _payload, **_kwargs: response,
    )
    result = smoke.run_gb2_s20m_reranker_repeatability_live(_env())
    assert result["status"] == "FAIL"
    assert failed_check in result["failed_checks"]


@pytest.mark.parametrize(
    "results",
    [
        None,
        ["bad"],
        [{"index": "0", "score": 0.5}],
        [{"index": 0, "score": True}],
        [
            {"index": 0, "score": 0.9},
            {"index": 0, "score": 0.8},
            {"index": 2, "score": 0.4},
            {"index": 3, "score": 0.1},
        ],
        [{"index": 0, "score": 0.9}],
    ],
)
def test_malformed_provider_results_are_rejected(monkeypatch, results) -> None:
    response = _response()
    response["results"] = results
    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda _payload, **_kwargs: response,
    )
    result = smoke.run_gb2_s20m_reranker_repeatability_live(_env())
    assert result["status"] == "FAIL"
    assert result["detail"] == "ValueError"


def test_missing_config_bad_dataset_and_evidence_redaction(tmp_path: Path) -> None:
    missing = smoke.run_gb2_s20m_reranker_repeatability_live(
        _env(NEX_MO_REMOTE_RERANKER_URL="")
    )
    assert missing["status"] == "FAIL"
    assert missing["detail"] == "ValueError"

    bad_dataset = tmp_path / "bad.json"
    bad_dataset.write_text("{}", encoding="utf-8")
    invalid = smoke.run_gb2_s20m_reranker_repeatability_live(
        _env(), dataset_path=bad_dataset
    )
    assert invalid["status"] == "FAIL"

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "protected-reranker-key"},
            _env(),
            smoke.DEFAULT_V2_PATH,
        )

    missing_path = tmp_path / "missing-dataset.json"
    smoke._assert_redacted({"safe": True}, _env(), missing_path)
    array_path = tmp_path / "array-dataset.json"
    array_path.write_text("[]", encoding="utf-8")
    smoke._assert_redacted({"safe": True}, _env(), array_path)


def test_collection_rejects_invalid_dataset_shapes(monkeypatch) -> None:
    with pytest.raises(ValueError, match="cases"):
        smoke._collect_repeat_observations({}, environ=_env(), requester=None)
    with pytest.raises(ValueError, match="documents"):
        smoke._collect_repeat_observations(
            {"cases": [{"case_id": "case", "query": "query", "documents": []}]},
            environ=_env(),
            requester=None,
        )
    with pytest.raises(ValueError, match="query"):
        smoke._collect_repeat_observations(
            {"cases": [{"case_id": "case", "query": "", "documents": [{}]}]},
            environ=_env(),
            requester=None,
        )

    monkeypatch.setattr(
        smoke,
        "execute_remote_rerank_request",
        lambda _payload, **_kwargs: _response([0.5]),
    )
    with pytest.raises(ValueError, match="boolean"):
        smoke._collect_repeat_observations(
            {
                "cases": [
                    {
                        "case_id": "case",
                        "query": "query",
                        "partition": "CALIBRATION",
                        "documents": [
                            {
                                "document_id": "document",
                                "relevance_grade": "STRONG_POSITIVE",
                                "expected_ready": "yes",
                                "text": "text",
                            }
                        ],
                    }
                ]
            },
            environ=_env(),
            requester=None,
        )


def test_analysis_handles_incomplete_coverage() -> None:
    analysis = smoke._analyze_repeatability(
        [
            {
                "pair_id": "only-pair",
                "repeat_index": 1,
                "score": 0.5,
            }
        ],
        expected_pair_ids={"only-pair"},
    )
    assert analysis["pair_coverage_complete"] is False
    assert math.isinf(analysis["max_absolute_score_delta"])


def test_main_success_failure_and_output(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20m_reranker_repeatability_live",
        lambda **_kwargs: {"status": "SKIPPED"},
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20m_reranker_repeatability_live",
        lambda **_kwargs: {"status": "FAIL", "failed_checks": []},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
    assert smoke.summary_line({}).endswith("checks=execution")
