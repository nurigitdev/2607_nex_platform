from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import run_gb2_s20n_single_signal_calibration as decision
from nex_runtime import model_calibration


def _dataset() -> dict:
    return json.loads(decision.DEFAULT_V2_PATH.read_text(encoding="utf-8"))


def _score(
    grade: str,
    partition: str,
    *,
    calibration_separable: bool,
    holdout_separable: bool,
) -> float:
    separable = (
        calibration_separable
        if partition == decision.CALIBRATION_PARTITION
        else holdout_separable
    )
    if separable:
        return {
            "STRONG_POSITIVE": 0.9,
            "ACCEPTABLE_POSITIVE": 0.8,
            "HARD_NEGATIVE": 0.2,
            "EASY_NEGATIVE": 0.1,
        }[grade]
    return {
        "STRONG_POSITIVE": 0.3,
        "ACCEPTABLE_POSITIVE": 0.2,
        "HARD_NEGATIVE": 0.9,
        "EASY_NEGATIVE": 0.8,
    }[grade]


def _source(
    *,
    calibration_separable: bool,
    holdout_separable: bool,
    repeat_count: int = 2,
) -> dict:
    dataset = _dataset()
    observations = []
    for repeat_index in range(1, repeat_count + 1):
        for case in dataset["cases"]:
            scored = [
                (
                    index,
                    _score(
                        document["relevance_grade"],
                        case["partition"],
                        calibration_separable=calibration_separable,
                        holdout_separable=holdout_separable,
                    ),
                )
                for index, document in enumerate(case["documents"])
            ]
            ranks = {
                index: rank
                for rank, (index, _value) in enumerate(
                    sorted(scored, key=lambda item: (-item[1], item[0])),
                    start=1,
                )
            }
            for index, document in enumerate(case["documents"]):
                observations.append(
                    {
                        "case_id": case["case_id"],
                        "pair_id": f"{case['case_id']}:{document['document_id']}",
                        "partition": case["partition"],
                        "relevance_grade": document["relevance_grade"],
                        "expected_ready": document["expected_ready"],
                        "repeat_index": repeat_index,
                        "score": scored[index][1],
                        "rank": ranks[index],
                        "model_revision": "Qwen3-Reranker-4B",
                        "deployment_id": "vllm-reranker-http",
                        "observed_at": "2026-11-02T00:00:00Z",
                    }
                )
    return {
        "evidence_schema_version": decision.EXPECTED_SOURCE_SCHEMA_VERSION,
        "status": "PASS",
        "checks": {name: True for name in decision.REQUIRED_SOURCE_CHECKS},
        "candidate_profile": {
            "profile_id": "reranking-qwen3-4b-numeric-repeatability-v1",
            "status": "CANDIDATE",
            "binding": {
                "capability": "reranking",
                "model_name": "Qwen3-Reranker-4B",
                "model_revision": "Qwen3-Reranker-4B",
                "deployment_id": "vllm-reranker-http",
                "request_shape": "rerank",
                "score_semantics": "provider_native_relevance_0_1",
                "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
                "dataset_id": "s136-reranker-relevance-public-v2",
                "dataset_sha256": (
                    "a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899"
                ),
            },
            "measurement": {
                "repeat_count": repeat_count,
                "observation_count": 120 * repeat_count,
            },
            "policy": {"score_delta_tolerance": 0.0005},
        },
        "score_observations": observations,
    }


def _run(tmp_path: Path, source: dict) -> dict:
    evidence = tmp_path / "repeatability.json"
    evidence.write_text(json.dumps(source), encoding="utf-8")
    return decision.run_gb2_s20n_single_signal_calibration(
        repeatability_evidence_path=evidence
    )


def test_calibration_rejection_records_multi_signal_without_opening_holdout(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        _source(calibration_separable=False, holdout_separable=True),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "MULTI_SIGNAL_REQUIRED"
    assert result["decision_reason"] == "calibration_threshold_unacceptable"
    assert result["calibration_fit"]["status"] == "NO_ACCEPTABLE_THRESHOLD"
    assert result["threshold_freeze"]["status"] == "NO_ACCEPTABLE_THRESHOLD"
    assert result["threshold_freeze"]["threshold"] is None
    assert result["calibration_threshold_evaluation"]["status"] == "REJECTED"
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "reason": "calibration_threshold_unacceptable",
        "expected_sample_count": 40,
        "threshold_reselected": False,
    }
    assert all(result["checks"].values())
    assert "decision=MULTI_SIGNAL_REQUIRED" in decision.summary_line(result)


def test_frozen_threshold_passes_or_rejects_untouched_holdout(tmp_path: Path) -> None:
    admitted = _run(
        tmp_path,
        _source(calibration_separable=True, holdout_separable=True),
    )
    assert admitted["decision"] == "SINGLE_SIGNAL_ADMITTED"
    assert admitted["threshold_freeze"]["status"] == "FROZEN"
    assert admitted["holdout"]["status"] == "EVALUATED"
    assert admitted["holdout"]["evaluation"]["status"] == "PASSED"
    assert admitted["holdout"]["threshold_freeze_hash"] == (
        admitted["threshold_freeze"]["freeze_hash"]
    )

    rejected = _run(
        tmp_path,
        _source(calibration_separable=True, holdout_separable=False),
    )
    assert rejected["decision"] == "MULTI_SIGNAL_REQUIRED"
    assert rejected["decision_reason"] == "frozen_threshold_failed_holdout"
    assert rejected["holdout"]["evaluation"]["status"] == "REJECTED"
    assert rejected["threshold_freeze"] == admitted["threshold_freeze"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(status="FAIL"),
        lambda payload: payload["checks"].update(model_revision_stable=False),
        lambda payload: payload["candidate_profile"]["binding"].update(
            dataset_sha256="0" * 64
        ),
        lambda payload: payload["candidate_profile"]["measurement"].update(
            repeat_count=1
        ),
        lambda payload: payload["score_observations"].append(
            deepcopy(payload["score_observations"][0])
        ),
        lambda payload: payload["score_observations"][0].update(score=2.0),
        lambda payload: payload["score_observations"][0].update(
            model_revision="drifted"
        ),
    ],
)
def test_invalid_or_drifted_repeatability_evidence_fails_closed(
    tmp_path: Path,
    mutator,
) -> None:
    source = _source(calibration_separable=True, holdout_separable=True)
    mutator(source)

    result = _run(tmp_path, source)

    assert result == {
        "evidence_schema_version": decision.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "single_signal_calibration_failed",
        "detail": "ValueError",
    }
    assert decision.summary_line(result).endswith(
        "reason=single_signal_calibration_failed"
    )


def test_score_drift_missing_file_redaction_and_cli_paths(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = _source(calibration_separable=True, holdout_separable=True)
    source["score_observations"][120]["score"] += 0.01
    assert _run(tmp_path, source)["status"] == "FAIL"

    missing = decision.run_gb2_s20n_single_signal_calibration(
        repeatability_evidence_path=tmp_path / "missing.json"
    )
    assert missing["detail"] == "FileNotFoundError"

    query = _dataset()["cases"][0]["query"]
    with pytest.raises(ValueError, match="protected"):
        decision._assert_redacted({"leak": query}, decision.DEFAULT_V2_PATH)

    output = tmp_path / "decision.json"
    monkeypatch.setattr(
        decision,
        "run_gb2_s20n_single_signal_calibration",
        lambda **_kwargs: {"status": "PASS", "decision": "MULTI_SIGNAL_REQUIRED"},
    )
    assert decision.main(["--summary", "--output", str(output)]) == 0
    assert "gb2_s20n_single_signal=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        decision,
        "run_gb2_s20n_single_signal_calibration",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert decision.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_fit_and_candidate_profile_failure_branches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _source(calibration_separable=True, holdout_separable=True)
    evidence = tmp_path / "repeatability.json"
    evidence.write_text(json.dumps(source), encoding="utf-8")

    monkeypatch.setattr(
        decision,
        "evaluate_binary_score_calibration",
        lambda *_args, **_kwargs: {"status": "INSUFFICIENT_SAMPLES"},
    )
    assert (
        decision.run_gb2_s20n_single_signal_calibration(
            repeatability_evidence_path=evidence
        )["status"]
        == "FAIL"
    )

    monkeypatch.setattr(
        decision,
        "evaluate_binary_score_calibration",
        lambda *_args, **_kwargs: {
            "status": "NO_ACCEPTABLE_THRESHOLD",
            "selected_threshold": None,
            "best_effort_metrics": None,
        },
    )
    assert (
        decision.run_gb2_s20n_single_signal_calibration(
            repeatability_evidence_path=evidence
        )["status"]
        == "FAIL"
    )

    admitted = decision.admit_calibration_dataset_files()["v2"]
    missing_profile = deepcopy(source)
    missing_profile["candidate_profile"] = None
    with pytest.raises(ValueError, match="profile is unavailable"):
        decision._validate_source_header(missing_profile, admitted)

    malformed_profile = deepcopy(source)
    malformed_profile["candidate_profile"]["policy"] = None
    with pytest.raises(ValueError, match="profile is malformed"):
        decision._validate_source_header(malformed_profile, admitted)

    incomplete_binding = deepcopy(source)
    incomplete_binding["candidate_profile"]["binding"]["model_name"] = " "
    with pytest.raises(ValueError, match="binding is incomplete"):
        decision._validate_source_header(incomplete_binding, admitted)


def test_observation_and_partition_validation_failure_branches() -> None:
    source = _source(calibration_separable=True, holdout_separable=True)
    admitted = decision.admit_calibration_dataset_files()["v2"]
    profile = decision._validate_source_header(source, admitted)
    expected = decision._dataset_pair_manifest(_dataset())

    malformed = deepcopy(source)
    malformed["score_observations"] = None
    with pytest.raises(ValueError, match="must be an array"):
        decision._validate_observation_envelope(
            malformed,
            expected_pairs=expected,
            source_profile=profile,
        )

    malformed = deepcopy(source)
    malformed["score_observations"][0] = None
    with pytest.raises(ValueError, match="must be an object"):
        decision._validate_observation_envelope(
            malformed,
            expected_pairs=expected,
            source_profile=profile,
        )

    unknown = deepcopy(source)
    unknown["score_observations"][0]["pair_id"] = "unknown:pair"
    with pytest.raises(ValueError, match="pair is unknown"):
        decision._validate_observation_envelope(
            unknown,
            expected_pairs=expected,
            source_profile=profile,
        )

    duplicate = deepcopy(source)
    duplicate["score_observations"][1] = deepcopy(duplicate["score_observations"][0])
    with pytest.raises(ValueError, match="duplicated"):
        decision._validate_observation_envelope(
            duplicate,
            expected_pairs=expected,
            source_profile=profile,
        )

    incomplete_expected = deepcopy(expected)
    incomplete_expected["missing:pair"] = {
        "case_id": "missing",
        "partition": decision.CALIBRATION_PARTITION,
        "relevance_grade": "EASY_NEGATIVE",
        "expected_ready": False,
    }
    with pytest.raises(ValueError, match="coverage is incomplete"):
        decision._validate_observation_envelope(
            source,
            expected_pairs=incomplete_expected,
            source_profile=profile,
        )

    with pytest.raises(ValueError, match="partition coverage"):
        decision._collapse_partition(
            source["score_observations"],
            expected_pairs=expected,
            partition=decision.CALIBRATION_PARTITION,
            repeat_count=3,
        )


def test_dataset_redaction_and_confidence_guard_failure_branches(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="cases are invalid"):
        decision._dataset_pair_manifest({})
    with pytest.raises(ValueError, match="case is invalid"):
        decision._dataset_pair_manifest({"cases": [None]})
    with pytest.raises(ValueError, match="document is invalid"):
        decision._dataset_pair_manifest(
            {"cases": [{"case_id": "case", "documents": [None]}]}
        )

    decision._assert_redacted({"safe": True}, tmp_path / "missing.json")
    with pytest.raises(ValueError, match="non-empty"):
        decision._required_string(" ", "field")
    with pytest.raises(model_calibration.ModelCalibrationError, match="counts"):
        model_calibration._wilson_interval(1, 0)
