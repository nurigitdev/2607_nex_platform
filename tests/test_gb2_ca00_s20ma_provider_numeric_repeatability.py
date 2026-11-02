from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_gb2_s20ma_provider_numeric_repeatability as smoke

RERANKER_REVISION = "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5"


def _env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "protected-key",
        **smoke.protected_dgx_vllm_profile_defaults(),
        **overrides,
    }


def _observations(dataset: dict, *, cross_label: bool = False) -> list[dict]:
    observations = []
    for repeat_index in range(1, 6):
        for case in dataset["cases"]:
            scores = [0.901, 0.900, 0.500, 0.100]
            if repeat_index % 2 == 0:
                if cross_label:
                    scores = [0.499, 0.900, 0.902, 0.100]
                else:
                    scores = [0.900, 0.901, 0.500, 0.100]
            order = sorted(range(4), key=lambda index: (-scores[index], index))
            ranks = {index: rank for rank, index in enumerate(order, start=1)}
            for index, document in enumerate(case["documents"]):
                observations.append(
                    {
                        "case_id": case["case_id"],
                        "pair_id": f"{case['case_id']}:{document['document_id']}",
                        "partition": case["partition"],
                        "relevance_grade": document["relevance_grade"],
                        "expected_ready": document["expected_ready"],
                        "repeat_index": repeat_index,
                        "score": scores[index],
                        "rank": ranks[index],
                        "model_revision": RERANKER_REVISION,
                        "deployment_id": "vllm-reranker-http",
                        "observed_at": "2026-11-02T00:00:00Z",
                    }
                )
    return observations


def test_skip_and_candidate_profile(monkeypatch) -> None:
    assert smoke.run_gb2_s20ma_provider_numeric_repeatability({})["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "collect_reranker_repeat_observations",
        lambda dataset, **_kwargs: _observations(dataset),
    )
    result = smoke.run_gb2_s20ma_provider_numeric_repeatability(_env())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["candidate_profile"]["policy"]["score_delta_tolerance"] == 0.0015
    assert result["repeatability"]["same_label_near_tie_exchange_count"] == 30
    assert result["repeatability"]["cross_label_rank_exchange_count"] == 0
    assert len(result["score_observations"]) == 600
    assert "tolerance=0.0015" in smoke.summary_line(result)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "http://dgx.test" not in serialized
    assert "protected-key" not in serialized


def test_cross_label_exchange_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "collect_reranker_repeat_observations",
        lambda dataset, **_kwargs: _observations(dataset, cross_label=True),
    )
    result = smoke.run_gb2_s20ma_provider_numeric_repeatability(_env())
    assert result["status"] == "FAIL"
    assert "cross_label_rank_stable" in result["failed_checks"]
    assert result["candidate_profile"] is None


def test_missing_config_execution_failure_and_redaction(tmp_path: Path) -> None:
    result = smoke.run_gb2_s20ma_provider_numeric_repeatability(
        _env(NEX_MO_REMOTE_RERANKER_URL="")
    )
    assert result["status"] == "FAIL"
    assert result["detail"] == "ValueError"

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "protected-key"}, _env(), smoke.DEFAULT_V2_PATH
        )
    smoke._assert_redacted({"safe": True}, _env(), tmp_path / "missing.json")


def test_main_and_summary_paths(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20ma_provider_numeric_repeatability",
        lambda **_kwargs: {"status": "SKIPPED"},
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20ma_provider_numeric_repeatability",
        lambda **_kwargs: {"status": "FAIL", "failed_checks": []},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
    assert smoke.summary_line({}).endswith("checks=execution")
