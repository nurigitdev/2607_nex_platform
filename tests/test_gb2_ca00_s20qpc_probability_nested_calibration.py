from __future__ import annotations

from copy import deepcopy

import pytest
import run_gb2_s20qpc_probability_nested_calibration as smoke
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _selection(*, status: str = "NO_ADMISSIBLE_PROFILE") -> dict:
    inner_selection = [
        {
            "profile_id": f"profile-{profile_index}",
            "candidate_auc": 0.75,
            "metrics": {
                "ready_recall": 0.2,
                "false_ready_rate": 0.05,
                "balanced_accuracy": 0.575,
            },
            "inner_folds": [
                {
                    "fold_index": fold_index,
                    "candidate_probability_training_candidate_count": 384,
                }
                for fold_index in range(4)
            ],
        }
        for profile_index in range(4)
    ]
    value = {
        "status": status,
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "outer_folds": [
            {"fold_index": index, "inner_selection": deepcopy(inner_selection)}
            for index in range(5)
        ],
        "oof_evaluation": {"metrics": None},
    }
    value["selection_hash"] = semantic_sha256_hash_ref(value)
    return value


def _parent(_environ, *, requester=None, selector=None):
    assert requester is None
    assert callable(selector)
    probability = _selection()
    probability["baseline_comparison"] = {
        "comparison_scope": "SAME_CALIBRATION_COLLECTION_INNER_DIAGNOSTIC_ONLY",
        "legacy_second_highest": {"status": "NO_ADMISSIBLE_PROFILE"},
        "candidate_probability_at_least_two": {
            "ready_recall_range": {"minimum": 0.1, "maximum": 0.2}
        },
    }
    return {
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "dataset": {"holdout_status": "SEALED_NOT_COLLECTED"},
        "checks": {"provider_calls_complete": True, "cleanup_complete": True},
        "pipeline_repeatability": {
            "status": "STABLE",
            "measurement": {"repeat_count": 5},
        },
        "nested_selection": probability,
    }


def test_skip_and_profile_guard() -> None:
    skipped = smoke.run_gb2_s20qpc_probability_nested_calibration({})
    denied = smoke.run_gb2_s20qpc_probability_nested_calibration(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")
    assert denied["failure_code"] == "profile_not_allowed"


def test_runner_accepts_fail_closed_calibration_result() -> None:
    result = smoke.run_gb2_s20qpc_probability_nested_calibration(
        {smoke.SMOKE_ENV: "1"}, parent_runner=_parent
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "NO_ADMISSIBLE_PROFILE_KEEP_HOLDOUT_SEALED"
    assert result["checks"]["candidate_probability_fit_is_inner_fold_local"]
    assert result["failed_checks"] == []
    assert "ready_recall_max=0.2" in smoke.summary_line(result)


def test_comparison_selector_and_diagnostic_ranges(monkeypatch) -> None:
    legacy = _selection()
    probability = _selection(status="CALIBRATION_OOF_ADMITTED")
    monkeypatch.setattr(smoke, "select_nested_retrieval_profile", lambda *_a, **_k: legacy)
    monkeypatch.setattr(
        smoke,
        "select_nested_candidate_probability_profile",
        lambda *_a, **_k: probability,
    )

    result = smoke._comparison_selector([])
    comparison = result["baseline_comparison"]

    assert result["status"] == "CALIBRATION_OOF_ADMITTED"
    assert comparison["legacy_second_highest"]["profile_fold_diagnostic_count"] == 20
    assert comparison["candidate_probability_at_least_two"][
        "ready_recall_range"
    ] == {"minimum": 0.2, "maximum": 0.2}
    assert comparison["holdout_access_permitted"] is False
    assert result["selection_hash"].startswith("sha256:")


def test_admitted_package_repeat_collection_is_projected(monkeypatch) -> None:
    calls = []

    def build(observations):
        calls.append(observations)
        return [{"projected": observations[0]}]

    def evaluate(repeated_samples, **kwargs):
        assert repeated_samples == [
            [{"projected": "first"}],
            [{"projected": "second"}],
        ]
        assert kwargs["expected_repeat_count"] == 2
        return {"status": "STABLE"}

    monkeypatch.setattr(
        smoke,
        "build_expanded_candidate_relevance_calibration_samples",
        build,
    )
    monkeypatch.setattr(
        smoke,
        "evaluate_candidate_probability_package_repeatability",
        evaluate,
    )
    result = smoke._package_ready_repeatability(
        {
            "repeat_collection": {
                "runs": [
                    {"candidate_observations": ["first"]},
                    {"candidate_observations": ["second"]},
                ]
            },
            "binding": {},
        },
        nested={"status": "CALIBRATION_OOF_ADMITTED"},
        repeatability={"measurement": {"repeat_count": 2}},
    )

    assert result == {"status": "STABLE"}
    assert calls == [["first"], ["second"]]


def test_admitted_package_repeat_collection_rejects_missing_rows() -> None:
    with pytest.raises(ValueError, match="collection is unavailable"):
        smoke._package_ready_repeatability(
            {},
            nested={"status": "CALIBRATION_OOF_ADMITTED"},
            repeatability={},
        )

    with pytest.raises(TypeError, match="observations are invalid"):
        smoke._package_ready_repeatability(
            {"repeat_collection": {"runs": [{}]}},
            nested={"status": "CALIBRATION_OOF_ADMITTED"},
            repeatability={},
        )


def test_main_writes_evidence_and_failure_summary(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpc_probability_nested_calibration",
        lambda: {
            **_parent({}, selector=lambda: None),
            "status": "PASS",
        },
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpc_probability_nested_calibration",
        lambda: {"status": "FAIL", "failed_checks": ["forced"]},
    )
    assert smoke.main(["--summary"]) == 1
    assert "checks=forced" in capsys.readouterr().out
