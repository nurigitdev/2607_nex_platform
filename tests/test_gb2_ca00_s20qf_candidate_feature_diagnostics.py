from __future__ import annotations

import json
from pathlib import Path

import run_gb2_s20qf_candidate_feature_diagnostics as smoke


def _source(**overrides: object) -> dict[str, object]:
    return {
        "status": "PASS",
        "service_id": "nex-cx",
        "profile": "test",
        "redacted_database_url": "postgresql+psycopg://***@localhost/nex_cx_test",
        "migration": {"planned_count": 1, "applied_count": 0, "skipped_count": 1},
        "dataset": {
            "dataset_id": "dataset-v3",
            "partition": "CALIBRATION",
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": {"reranker_model_revision": "hf:" + "a" * 40},
        "provider_observation": {"reranking": {"success_count": 40}},
        "provider_request_counts": {"total": 240},
        "collection": {
            "sample_count": 40,
            "ready_count": 20,
            "low_confidence_count": 20,
            "sample_set_hash": "sha256:" + "b" * 64,
        },
        "candidate_feature_diagnostics": {
            "status": "DIAGNOSED",
            "runtime_activation_permitted": False,
            "feature_selection_permitted": False,
            "weight_selection_permitted": False,
            "threshold_selection_permitted": False,
            "holdout_access_permitted": False,
            "dataset": {
                "partition": "CALIBRATION",
                "package_count": 40,
                "candidate_observation_count": 160,
            },
            "feature_set_correction": {
                "corrected_candidate_fields": ["reranker_top2_mean"],
                "directional_corrected_candidates": ["reranker_top2_mean"],
                "selection_deferred_to": "GB2-CA00-S20Q-G",
            },
        },
        "persistence": {"retrieval_package_count": 40},
        "checks": {
            "test_database_identity": True,
            "provider_calls_complete": True,
            "restart_readback_exact": True,
            "cleanup_complete": True,
            "candidate_diagnostics_complete": True,
        },
        **overrides,
    }


def test_activation_source_failure_and_candidate_check_failure() -> None:
    skipped = smoke.run_gb2_s20qf_candidate_feature_diagnostics({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("skipped")

    failed = smoke.run_gb2_s20qf_candidate_feature_diagnostics(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
    )
    assert failed["failure_code"] == "source_collection_failed"
    assert failed["detail"] == {
        "status": "FAIL",
        "failure_code": "provider_failed",
    }

    source = _source()
    source["checks"]["cleanup_complete"] = False  # type: ignore[index]
    check_failed = smoke.run_gb2_s20qf_candidate_feature_diagnostics(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: source,
    )
    assert check_failed["failure_code"] == "candidate_diagnostic_checks_failed"
    assert check_failed["detail"] == ["cleanup_complete"]


def test_pass_projection_keeps_holdout_sealed_and_samples_private() -> None:
    calls: list[dict[str, object]] = []

    def collector(environ, **kwargs):
        calls.append({"environ": environ, **kwargs})
        return _source()

    result = smoke.run_gb2_s20qf_candidate_feature_diagnostics(
        {smoke.SMOKE_ENV: "1"},
        requester=lambda *_args, **_kwargs: None,
        collector=collector,
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["source_collection"]["sample_count"] == 40
    assert "samples" not in result["source_collection"]
    assert calls[0]["environ"][smoke.s20qe.SMOKE_ENV] == "1"
    assert "directional=1 holdout=sealed" in smoke.summary_line(result)


def test_summary_failure_and_main_writes_evidence(monkeypatch, tmp_path: Path) -> None:
    assert "error=broken" in smoke.summary_line(smoke._failure("broken"))
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qf_candidate_feature_diagnostics",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "SKIPPED"}
