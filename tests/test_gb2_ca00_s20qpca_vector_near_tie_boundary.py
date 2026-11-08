from __future__ import annotations

import run_gb2_s20qpca_vector_near_tie_boundary as smoke


def _parent(*_args, requester=None, **_kwargs):
    assert requester is None
    return {
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "provider_request_counts": {"embedding": 1440, "reranking": 800},
        "pipeline_repeatability": {
            "status": "STABLE",
            "measurement": {"repeat_count": 5},
            "tolerances": {"vector_similarity_quality": 0.005},
            "stages": {
                "candidate_membership_change_count": 0,
                "vector_rank_change_count": 8,
                "bounded_vector_rank_exchange_count": 8,
                "unbounded_vector_rank_change_count": 0,
                "rrf_score_drift_count": 8,
                "bounded_rrf_score_drift_count": 8,
                "unbounded_rrf_score_drift_count": 0,
                "final_rank_change_count": 0,
            },
        },
        "nested_selection": {
            "status": "NO_ADMISSIBLE_PROFILE",
            "runtime_activation_permitted": False,
            "holdout_access_permitted": False,
            "holdout": {"status": "SEALED_NOT_OPENED"},
        },
        "package_ready_repeatability": {
            "status": "NOT_APPLICABLE_PROFILE_NOT_ADMITTED",
            "runtime_activation_permitted": False,
            "holdout_access_permitted": False,
        },
    }


def test_skip_and_profile_guard() -> None:
    skipped = smoke.run_gb2_s20qpca_vector_near_tie_boundary({})
    denied = smoke.run_gb2_s20qpca_vector_near_tie_boundary(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")
    assert denied["failure_code"] == "profile_not_allowed"


def test_boundary_and_live_contract_pass() -> None:
    result = smoke.run_gb2_s20qpca_vector_near_tie_boundary(
        {smoke.SMOKE_ENV: "1"}, parent_runner=_parent
    )

    assert result["status"] == "PASS"
    assert result["ordering_policy"]["maximum_score_delta"] == 0.001
    assert result["checks"]["ordering_boundary_not_expanded"] is True
    assert result["checks"]["numeric_equivalence_tolerance_bound"] is True
    assert result["uncertainty_aware_classification"][
        "bounded_vector_rank_exchange_count"
    ] == 8
    assert result["failed_checks"] == []
    assert "vector_bounded=8" in smoke.summary_line(result)


def test_repeatability_failure_is_fail_closed() -> None:
    def unstable(*args, **kwargs):
        result = _parent(*args, **kwargs)
        result["pipeline_repeatability"]["status"] = "UNSTABLE"
        result["pipeline_repeatability"]["stages"][
            "unbounded_vector_rank_change_count"
        ] = 1
        return result

    result = smoke.run_gb2_s20qpca_vector_near_tie_boundary(
        {smoke.SMOKE_ENV: "1"}, parent_runner=unstable
    )

    assert result["status"] == "FAIL"
    assert result["failed_checks"] == [
        "five_run_pipeline_repeatability_stable",
        "raw_vector_changes_preserved",
        "unbounded_vector_changes_absent",
    ]


def test_main_writes_evidence_and_returns_failure(tmp_path, monkeypatch) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpca_vector_near_tie_boundary",
        lambda: {"status": "PASS"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpca_vector_near_tie_boundary",
        lambda: {"status": "FAIL", "failed_checks": ["forced"]},
    )
    assert smoke.main([]) == 1
    assert "checks=forced" in smoke.summary_line(
        {"status": "FAIL", "failed_checks": ["forced"]}
    )
