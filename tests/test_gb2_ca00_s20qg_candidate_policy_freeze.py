from __future__ import annotations

import json
from pathlib import Path

import run_gb2_s20qg_candidate_policy_freeze as smoke


def _repeatability() -> dict[str, object]:
    return {
        "status": "PASS",
        "checks": {name: True for name in smoke.REQUIRED_REPEATABILITY_CHECKS},
        "candidate_profile": {
            "status": "CANDIDATE",
            "profile_id": "repeatability-v1",
            "binding": {
                "model_name": "served-reranker",
                "deployment_id": "vllm-reranker-http",
                "retrieval_policy_id": "ranking-v1",
            },
            "measurement": {"repeat_count": 5, "observation_count": 600},
            "policy": {"score_delta_tolerance": 0.0005},
        },
        "repeatability": {"cross_label_rank_exchange_count": 0},
    }


def _revision() -> dict[str, object]:
    return {
        "status": "PASS",
        "checks": {name: True for name in smoke.REQUIRED_REVISION_CHECKS},
        "binding": {
            "served_model_name": "served-reranker",
            "deployment_id": "vllm-reranker-http",
            "artifact_revision": "hf:" + "a" * 40,
        },
    }


def _source(**overrides: object) -> dict[str, object]:
    return {
        "status": "PASS",
        "service_id": "nex-cx",
        "profile": "test",
        "redacted_database_url": "postgresql+psycopg://***@localhost/nex_cx_test",
        "migration": {"planned_count": 1},
        "dataset": {
            "dataset_id": "dataset-v3",
            "dataset_sha256": "b" * 64,
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": {
            "chunk_policy_id": "chunk",
            "embedding_model_revision": "embedding",
            "ranking_policy_id": "ranking-v1",
            "reranker_model_revision": "hf:" + "a" * 40,
            "tokenizer_policy_id": "tokenizer",
        },
        "collection": {
            "sample_count": 40,
            "sample_set_hash": "sha256:" + "c" * 64,
            "candidate_feature_samples": [{"sample_id": "opaque"}],
        },
        "candidate_feature_diagnostics": {
            "diagnostic_hash": "sha256:" + "d" * 64,
            "feature_set_correction": {
                "current_feature_fields": [
                    "reranker_top_score",
                    "reranker_top_margin",
                    "rrf_top_score",
                ],
                "corrected_candidate_fields": [
                    "reranker_top2_mean",
                    "reranker_second_score",
                    "reranker_score_spread",
                ],
            },
            "package_features": {
                "reranker_top_score": {"classification": "DIRECTIONAL"},
                "reranker_top_margin": {"classification": "DIRECTIONAL"},
                "reranker_top2_mean": {"classification": "DIRECTIONAL"},
                "rrf_top_score": {"classification": "INVERTED"},
            },
        },
        "checks": {
            "test_database_identity": True,
            "provider_calls_complete": True,
            "candidate_feature_projection_complete": True,
            "restart_readback_exact": True,
            "cleanup_complete": True,
        },
        "provider_observation": {},
        "provider_request_counts": {},
        "persistence": {},
        **overrides,
    }


def _selection(*_args: object, **kwargs: object) -> dict[str, object]:
    assert kwargs["directional_feature_fields"] == (
        "reranker_top_score",
        "reranker_top_margin",
        "reranker_top2_mean",
        "reranker_second_score",
        "reranker_score_spread",
    )
    return {
        "status": "FROZEN",
        "runtime_activation_permitted": False,
        "dataset": {"partition": "CALIBRATION"},
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "frozen_policy": {
            "feature_fields": ["reranker_top_score"],
            "runtime_activation_permitted": False,
        },
    }


def _evidence_files(tmp_path: Path) -> tuple[Path, Path]:
    repeatability = tmp_path / "repeatability.json"
    revision = tmp_path / "revision.json"
    repeatability.write_text(json.dumps(_repeatability()), encoding="utf-8")
    revision.write_text(json.dumps(_revision()), encoding="utf-8")
    return repeatability, revision


def test_skip_source_failure_and_provenance_failure(tmp_path: Path) -> None:
    assert smoke.run_gb2_s20qg_candidate_policy_freeze({})["status"] == "SKIPPED"
    repeatability, revision = _evidence_files(tmp_path)
    failed = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert failed["failure_code"] == "source_collection_failed"

    drifted = _revision()
    drifted["binding"]["artifact_revision"] = "hf:" + "f" * 40  # type: ignore[index]
    revision.write_text(json.dumps(drifted), encoding="utf-8")
    rejected = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        selector=_selection,
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert rejected["failure_code"] == "source_provenance_not_admitted"


def test_pass_projection_keeps_holdout_sealed_and_rows_private(tmp_path: Path) -> None:
    repeatability, revision = _evidence_files(tmp_path)
    result = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        requester=lambda *_args, **_kwargs: None,
        collector=lambda *_args, **_kwargs: _source(),
        selector=_selection,
        repeatability_path=repeatability,
        revision_path=revision,
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["source_collection"]["candidate_feature_sample_count"] == 1
    assert "candidate_feature_samples" not in result["source_collection"]
    assert result["provenance"]["numeric_tolerance"] == 0.0005
    assert "features=1 holdout=sealed" in smoke.summary_line(result)


def test_nonfrozen_selection_and_missing_features_fail_closed(tmp_path: Path) -> None:
    repeatability, revision = _evidence_files(tmp_path)
    rejected = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: _source(),
        selector=lambda *_args, **_kwargs: {
            "status": "NO_ACCEPTABLE_POLICY",
            "runtime_activation_permitted": False,
            "dataset": {"partition": "CALIBRATION"},
            "holdout": {"status": "SEALED_NOT_OPENED"},
            "frozen_policy": None,
        },
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert rejected["status"] == "FAIL"
    assert "candidate_policy_frozen" in rejected["failed_checks"]

    malformed = _source()
    malformed["collection"] = {}
    missing = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: malformed,
        selector=_selection,
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert missing["failure_code"] == "candidate_feature_samples_missing"

    no_features = _source()
    no_features["candidate_feature_diagnostics"] = {
        "diagnostic_hash": "sha256:" + "d" * 64,
        "feature_set_correction": {},
        "package_features": {},
    }
    unavailable = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        collector=lambda *_args, **_kwargs: no_features,
        selector=_selection,
        repeatability_path=repeatability,
        revision_path=revision,
    )
    assert unavailable["failure_code"] == "candidate_features_unavailable"


def test_failure_summary_redaction_and_main(monkeypatch, tmp_path: Path) -> None:
    assert smoke.summary_line(smoke._failure("broken")).endswith("error=broken")
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qg_candidate_policy_freeze",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "SKIPPED"}

    try:
        smoke._assert_redacted(
            {"leak": "secret"}, {"NEX_MO_REMOTE_RERANKER_API_KEY": "secret"}
        )
    except ValueError as exc:
        assert "protected" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("redaction guard did not fail")

    monkeypatch.undo()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    failed = smoke.run_gb2_s20qg_candidate_policy_freeze(
        {smoke.SMOKE_ENV: "1"},
        repeatability_path=invalid,
        revision_path=invalid,
    )
    assert failed["failure_code"] == "candidate_policy_freeze_failed"
    assert failed["detail"] == {
        "exception": "TypeError",
        "message": "evidence document is invalid",
    }
