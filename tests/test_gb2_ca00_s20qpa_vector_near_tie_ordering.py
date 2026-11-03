from __future__ import annotations

import run_gb2_s20qpa_vector_near_tie_ordering as smoke


def _parent(*_args, requester=None, **_kwargs):
    assert requester is None
    return {
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "migration": {"planned_count": 10, "applied_count": 0, "skipped_count": 10},
        "dataset": {"scenario_count": 80, "holdout_status": "SEALED_NOT_COLLECTED"},
        "binding": {"embedding_model_revision": "embedding-revision"},
        "provider_observation": {"embedding": {"success_count": 1440}},
        "provider_request_counts": {"embedding": 1440, "reranking": 800},
        "checks": {"provider_calls_complete": True, "cleanup_complete": True},
        "pipeline_repeatability": {
            "status": "STABLE",
            "measurement": {"repeat_count": 5},
            "stages": {
                "candidate_membership_change_count": 0,
                "vector_rank_change_count": 0,
                "rrf_score_drift_count": 0,
                "final_rank_change_count": 0,
            },
        },
        "calibration_admission": {"status": "REJECTED"},
        "nested_selection": {
            "status": "NO_ADMISSIBLE_PROFILE",
            "runtime_activation_permitted": False,
            "holdout_access_permitted": False,
            "holdout": {"status": "SEALED_NOT_OPENED"},
        },
    }


def test_skip_and_profile_guard() -> None:
    skipped = smoke.run_gb2_s20qpa_vector_near_tie_ordering({})
    denied = smoke.run_gb2_s20qpa_vector_near_tie_ordering(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")
    assert denied == {
        "evidence_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "profile_not_allowed",
    }


def test_repeatability_pass_is_independent_from_calibration_rejection() -> None:
    result = smoke.run_gb2_s20qpa_vector_near_tie_ordering(
        {smoke.SMOKE_ENV: "1"},
        parent_runner=_parent,
    )

    assert result["status"] == "PASS"
    assert result["calibration_admission"]["status"] == "REJECTED"
    assert result["nested_selection_status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["holdout_status"] == "SEALED_NOT_OPENED"
    assert result["ordering_policy"]["raw_score_preserved"] is True
    assert result["database_identity"]["database"] == "nex_cx_test"
    assert result["provider_request_counts"]["reranking"] == 800
    assert result["failed_checks"] == []
    assert "repeatability=STABLE" in smoke.summary_line(result)


def test_repeatability_drift_fails_closed() -> None:
    def unstable(*args, **kwargs):
        result = _parent(*args, **kwargs)
        result["pipeline_repeatability"]["status"] = "UNSTABLE"
        result["pipeline_repeatability"]["stages"]["vector_rank_change_count"] = 2
        return result

    result = smoke.run_gb2_s20qpa_vector_near_tie_ordering(
        {smoke.SMOKE_ENV: "1"},
        parent_runner=unstable,
    )

    assert result["status"] == "FAIL"
    assert result["failed_checks"] == [
        "five_run_pipeline_repeatability_stable",
        "vector_rank_repeatable",
    ]
    assert "vector_rank_repeatable" in smoke.summary_line(result)


def test_main_writes_evidence_and_returns_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpa_vector_near_tie_ordering",
        lambda: {"status": "PASS"},
    )
    output = tmp_path / "evidence.json"

    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpa_vector_near_tie_ordering",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert smoke.main([]) == 1
