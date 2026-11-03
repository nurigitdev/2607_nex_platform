from __future__ import annotations

import json
from pathlib import Path

import run_gb2_s20qi_candidate_relevance_signal_expansion as smoke
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
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
        "repeat_collection": {
            "repeat_count": 5,
            "retrieval_request_count": 200,
            "candidate_observation_count": 800,
            "runs": _runs(),
        },
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
        "search": {"signal_fields": list(EXPANDED_CANDIDATE_SIGNAL_FIELDS)},
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "frozen_policy": (
            {"runtime_activation_permitted": False}
            if status == "FROZEN"
            else None
        ),
    }


def _files(tmp_path: Path) -> tuple[Path, Path]:
    repeatability = tmp_path / "repeat.json"
    revision = tmp_path / "revision.json"
    repeatability.write_text("{}", encoding="utf-8")
    revision.write_text("{}", encoding="utf-8")
    return repeatability, revision


def test_skip_and_frozen_signal_expansion_success(monkeypatch, tmp_path: Path) -> None:
    assert smoke.run_gb2_s20qi_candidate_relevance_signal_expansion({})[
        "status"
    ] == "SKIPPED"
    repeatability, revision = _files(tmp_path)
    captured: dict[str, object] = {}

    def calibrator(*_args, **kwargs):
        captured.update(kwargs)
        return _calibration()

    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    result = smoke.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        analyzer=lambda *_args, **_kwargs: _pipeline(),
        calibrator=calibrator,
        repeatability_path=repeatability,
        revision_path=revision,
    )

    assert result["status"] == "PASS"
    assert result["decision"]["next_action"] == "ORIGINAL_S20Q_HOLDOUT_ACCEPTANCE"
    assert captured["signal_fields"] == EXPANDED_CANDIDATE_SIGNAL_FIELDS
    assert captured["policy_id"] == smoke.EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID
    assert result["source_collection"]["baseline_candidate_sample_count"] == 160
    assert result["signal_contract"]["truth_or_permission_signal_included"] is False
    assert "candidate_observations" not in json.dumps(result)


def test_no_acceptable_policy_is_a_complete_fail_closed_decision(
    monkeypatch, tmp_path: Path
) -> None:
    repeatability, revision = _files(tmp_path)
    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    result = smoke.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        analyzer=lambda *_args, **_kwargs: _pipeline(),
        calibrator=lambda *_args, **_kwargs: _calibration("NO_ACCEPTABLE_POLICY"),
        repeatability_path=repeatability,
        revision_path=revision,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == {
        "status": "NO_ACCEPTABLE_POLICY",
        "next_action": "CONTROLLED_RERANKER_REVISION_AB",
    }
    assert "decision=NO_ACCEPTABLE_POLICY" in smoke.summary_line(result)


def test_source_and_evidence_failures_are_redacted(monkeypatch, tmp_path: Path) -> None:
    repeatability, revision = _files(tmp_path)
    failed = smoke.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert failed["failure_code"] == "source_collection_failed"

    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    missing = _source()
    missing["repeat_collection"] = {}
    result = smoke.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {smoke.SMOKE_ENV: "1", "NEX_MO_REMOTE_RERANKER_API_KEY": "secret"},
        collector=lambda *_args, **_kwargs: missing,
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert result["failure_code"] == "repeat_collection_missing"
    assert "secret" not in json.dumps(result)


def test_failed_checks_and_main_status(monkeypatch, tmp_path: Path, capsys) -> None:
    repeatability, revision = _files(tmp_path)
    monkeypatch.setattr(
        smoke.s20qg,
        "_admit_provenance",
        lambda *_args, **_kwargs: {"numeric_tolerance": 0.0005},
    )
    result = smoke.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        analyzer=lambda *_args, **_kwargs: _pipeline("UNSTABLE"),
        calibrator=lambda *_args, **_kwargs: _calibration("PIPELINE_UNSTABLE"),
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert result["status"] == "FAIL"
    assert "pipeline_and_expanded_signals_repeatable" in result["failed_checks"]
    assert "candidate_relevance_decision_complete" in result["failed_checks"]

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qi_candidate_relevance_signal_expansion",
        lambda: {"status": "PASS", "decision": {"status": "FROZEN"}},
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "signal_expansion=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qi_candidate_relevance_signal_expansion",
        lambda: {"status": "FAIL", "failure_code": "failed"},
    )
    assert smoke.main([]) == 1
