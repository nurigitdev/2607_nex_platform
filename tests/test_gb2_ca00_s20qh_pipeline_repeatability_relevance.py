from __future__ import annotations

import json
from pathlib import Path

import run_gb2_s20qh_pipeline_repeatability_relevance as smoke
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_candidate_diagnostic_observations,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _runs() -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for scenario_index in range(20):
        for ready in (True, False):
            candidates = [
                {
                    "candidate_id": f"candidate-{index}",
                    "evidence_role": "ANSWER" if ready and index < 2 else "OTHER",
                    "expected_relevant": ready and index < 2,
                }
                for index in range(4)
            ]
            observations.extend(
                build_candidate_diagnostic_observations(
                    {
                        "scenario_id": f"scenario-{scenario_index}",
                        "expected_ready": ready,
                        "candidates": candidates,
                    },
                    [
                        {
                            "candidate_id": candidate["candidate_id"],
                            "rank": index + 1,
                            "scores": {
                                "rerank_score": 0.9 - index * 0.2,
                                "rrf_normalized_score": 0.8 - index * 0.1,
                                "channel_support_score": 1.0,
                                "bm25_score": 10.0 - index,
                                "vector_score": 0.9 - index * 0.2,
                                "bm25_rank": index + 1,
                                "vector_rank": index + 1,
                            },
                        }
                        for index, candidate in enumerate(candidates)
                    ],
                )
            )
    runs: list[dict[str, object]] = []
    for index in range(5):
        unsigned = {
            "repeat_index": index,
            "sample_count": 40,
            "candidate_observation_count": 160,
            "sample_set_hash": semantic_sha256_hash_ref(["samples"]),
            "observation_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["observation_hash"]) for row in observations)
            ),
            "candidate_observations": observations,
        }
        runs.append({**unsigned, "run_hash": semantic_sha256_hash_ref(unsigned)})
    return runs


def _source() -> dict[str, object]:
    return {
        "status": "PASS",
        "service_id": "nex-cx",
        "profile": "test",
        "redacted_database_url": "postgresql://nex_cx_user:***@localhost/nex_cx_test",
        "migration": {"planned_count": 1, "applied_count": 0, "skipped_count": 1},
        "dataset": {
            "dataset_id": "dataset-v3",
            "dataset_sha256": "d" * 64,
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": {
            "chunk_policy_id": "chunk",
            "embedding_model_revision": "embedding",
            "ranking_policy_id": "ranking",
            "reranker_model_revision": "reranker",
            "tokenizer_policy_id": "tokenizer",
        },
        "provider_observation": {},
        "provider_request_counts": {},
        "repeat_collection": {
            "repeat_count": 5,
            "retrieval_request_count": 200,
            "candidate_observation_count": 800,
            "runs": _runs(),
        },
        "persistence": {"document_count": 160},
        "checks": {
            "test_database_identity": True,
            "repeat_collection_complete": True,
            "provider_calls_complete": True,
            "restart_readback_exact": True,
            "cleanup_complete": True,
        },
    }


def _pipeline(status: str = "STABLE") -> dict[str, str]:
    return {"status": status, "repeatability_hash": "sha256:" + "e" * 64}


def _calibration(status: str = "FROZEN") -> dict[str, object]:
    return {
        "status": status,
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "frozen_policy": (
            {"runtime_activation_permitted": False}
            if status == "FROZEN"
            else None
        ),
    }


def _files(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "repeat.json"
    second = tmp_path / "revision.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    return first, second


def test_protected_runner_skip_and_success(monkeypatch, tmp_path: Path) -> None:
    assert smoke.run_gb2_s20qh_pipeline_repeatability_relevance({})["status"] == "SKIPPED"
    first, second = _files(tmp_path)
    calls: list[dict[str, str]] = []

    def collector(environ, **_kwargs):
        calls.append(environ)
        return _source()

    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    result = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1"},
        collector=collector,
        analyzer=lambda *_args, **_kwargs: _pipeline(),
        calibrator=lambda *_args, **_kwargs: _calibration(),
        repeatability_path=first,
        revision_path=second,
    )

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert calls[0][smoke.s20qe.REPEAT_COUNT_ENV] == "5"
    assert result["source_collection"]["baseline_candidate_sample_count"] == 160
    assert "repeatability=STABLE calibration=FROZEN" in smoke.summary_line(result)
    assert "candidate_observations" not in json.dumps(result)


def test_protected_runner_fails_closed_on_source_or_decision(monkeypatch, tmp_path: Path) -> None:
    first, second = _files(tmp_path)
    source_failure = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
        repeatability_path=first,
        revision_path=second,
    )
    assert source_failure["failure_code"] == "source_collection_failed"

    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    rejected = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        analyzer=lambda *_args, **_kwargs: _pipeline("UNSTABLE"),
        calibrator=lambda *_args, **_kwargs: _calibration("PIPELINE_UNSTABLE"),
        repeatability_path=first,
        revision_path=second,
    )
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "pipeline_relevance_calibration_failed"
    assert rejected["failed_checks"] == [
        "pipeline_repeatability_stable",
        "candidate_relevance_policy_frozen",
        "runtime_activation_prohibited",
    ]
    assert "pipeline_relevance=fail" in smoke.summary_line(rejected)


def test_protected_runner_redacts_configuration_and_reports_invalid_evidence(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    result = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1", "NEX_MO_REMOTE_RERANKER_API_KEY": "secret-value"},
        repeatability_path=missing,
        revision_path=missing,
    )
    assert result["failure_code"] == "pipeline_relevance_calibration_execution_failed"
    assert "secret-value" not in json.dumps(result)


def test_protected_runner_rejects_missing_repeat_payloads(monkeypatch, tmp_path: Path) -> None:
    first, second = _files(tmp_path)
    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    missing_runs = _source()
    missing_runs["repeat_collection"] = {}
    result = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: missing_runs,
        repeatability_path=first,
        revision_path=second,
    )
    assert result["failure_code"] == "repeat_collection_missing"

    missing_baseline = _source()
    missing_baseline["repeat_collection"]["runs"][0]["candidate_observations"] = "bad"
    result = smoke.run_gb2_s20qh_pipeline_repeatability_relevance(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: missing_baseline,
        analyzer=lambda *_args, **_kwargs: _pipeline(),
        repeatability_path=first,
        revision_path=second,
    )
    assert result["failure_code"] == "baseline_candidate_observations_missing"


def test_main_writes_evidence_and_returns_status(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qh_pipeline_repeatability_relevance",
        lambda: {"status": "PASS", "pipeline_repeatability": {"status": "STABLE"}, "candidate_relevance_calibration": {"status": "FROZEN"}},
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "pipeline_relevance=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qh_pipeline_repeatability_relevance",
        lambda: {"status": "FAIL", "failure_code": "failed"},
    )
    assert smoke.main([]) == 1
