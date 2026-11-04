from __future__ import annotations

from copy import deepcopy

import run_gb2_s20qpd_package_probability_failure_audit as smoke
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def _source() -> dict:
    samples = []
    for scenario in range(12):
        for ready in (False, True):
            label = "positive" if ready else "negative"
            if ready:
                scores = (
                    (0.70, 0.65, 0.40, 0.35)
                    if scenario < 8
                    else (0.50, 0.45, 0.40, 0.35)
                )
            else:
                scores = (
                    (0.72, 0.68, 0.40, 0.35)
                    if scenario < 3
                    else (0.55, 0.50, 0.40, 0.35)
                )
            for index, score in enumerate(scores):
                row = {
                    "sample_schema_version": (
                        "cx_retrieval_confidence_candidate_relevance_sample.v2"
                    ),
                    "sample_id": f"scenario-{scenario}:{label}",
                    "candidate_id": f"{scenario}-{label}-{index}",
                    "expected_ready": ready,
                    "expected_relevant": ready and index < 2,
                    "signals": {
                        "reranker_score": score,
                        "rrf_normalized_score": score,
                        "channel_rank_quality": score,
                        "bm25_score_quality": score,
                        "vector_similarity_quality": score,
                    },
                }
                row["sample_hash"] = semantic_sha256_hash_ref(row)
                samples.append(row)
    nested = {
        "status": "NO_ADMISSIBLE_PROFILE",
        "holdout_access_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
    }
    nested["selection_hash"] = semantic_sha256_hash_ref(nested)
    return {
        "binding": {
            "embedding_model_revision": "embedding-revision",
            "reranker_model_revision": "reranker-revision",
            "ranking_policy_id": "ranking-v1",
            "tokenizer_policy_id": "tokenizer-v1",
            "chunk_policy_id": "chunk-v1",
        },
        "nested_selection": nested,
        "collection": {"candidate_relevance_samples": samples},
    }


def test_skip_profile_and_missing_source_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpd_package_probability_failure_audit({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpd_package_probability_failure_audit(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    missing = smoke.run_gb2_s20qpd_package_probability_failure_audit(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: str(tmp_path / "missing.json")}
    )
    assert missing["failure_code"] == "source_evidence_missing"


def test_runner_attributes_failure_without_opening_holdout() -> None:
    result = smoke.run_gb2_s20qpd_package_probability_failure_audit(
        {smoke.SMOKE_ENV: "1"}, source=_source()
    )

    assert result["status"] == "PASS"
    assert result["provider_calls"] == 0
    assert result["holdout_opened"] is False
    assert result["audit"]["decision"] == (
        "DEPENDENCE_ROBUST_PACKAGE_SCORE_REQUIRED"
    )
    assert "holdout=sealed" in smoke.summary_line(result)


def test_runner_rejects_source_drift() -> None:
    source = _source()
    source["nested_selection"]["status"] = "CALIBRATION_OOF_ADMITTED"
    result = smoke.run_gb2_s20qpd_package_probability_failure_audit(
        {smoke.SMOKE_ENV: "1"}, source=source
    )
    assert result["status"] == "FAIL"
    assert "source_is_fail_closed" in result["failed_checks"]

    missing = deepcopy(_source())
    missing["collection"] = {}
    result = smoke.run_gb2_s20qpd_package_probability_failure_audit(
        {smoke.SMOKE_ENV: "1"}, source=missing
    )
    assert result["failure_code"] == "candidate_samples_missing"


def test_main_writes_evidence(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "audit.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpd_package_probability_failure_audit",
        lambda: {"status": "PASS", "audit": {"decision": "done"}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out
