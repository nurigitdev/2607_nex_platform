from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import run_gb2_s20oa_immutable_reranker_binding as binding


REVISION = "hf:" + "a" * 40


def _artifact_evidence() -> dict:
    return {
        "schema_version": "model_artifact_revision.v1",
        "status": "PASS",
        "revision_source": "HUGGINGFACE_LOCAL_METADATA",
        "artifact_revision": REVISION,
        "metadata_file_count": 2,
        "metadata_target_count": 2,
        "weight_artifact_count": 1,
        "metadata_manifest_digest": "sha256:" + "b" * 64,
        "model_path_persisted": False,
        "artifact_content_persisted": False,
    }


def _s20o_evidence() -> dict:
    return {
        "status": "PASS",
        "decision": {"code": "PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED"},
        "source_and_runtime_audit": {
            "findings": {
                "immutable_model_source_revision_bound": False,
                "sequence_classifier_override_confirmed": True,
                "qwen3_reranker_template_confirmed": True,
            }
        },
    }


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / "artifact.json"
    prior = tmp_path / "s20o.json"
    artifact.write_text(json.dumps(_artifact_evidence()), encoding="utf-8")
    prior.write_text(json.dumps(_s20o_evidence()), encoding="utf-8")
    return {
        binding.SMOKE_ENV: "1",
        binding.ARTIFACT_EVIDENCE_ENV: str(artifact),
        binding.S20O_EVIDENCE_ENV: str(prior),
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "protected-key",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": REVISION,
        **overrides,
    }


def _requester(method: str, url: str, **kwargs: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [
                {"index": 0, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.1},
            ]
        },
    )


def test_skip_and_successful_immutable_binding(tmp_path: Path) -> None:
    assert binding.run_gb2_s20oa_immutable_reranker_binding({})["status"] == (
        "SKIPPED"
    )
    result = binding.run_gb2_s20oa_immutable_reranker_binding(
        _env(tmp_path), requester=_requester
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["binding"]["artifact_revision"] == REVISION
    assert result["binding"]["served_model_name"] == "Qwen3-Reranker-4B"
    assert result["live_observation"]["ranked_document_indices"] == [0, 1]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "dgx.test" not in serialized
    assert "protected-key" not in serialized
    assert "프로젝트 비용 전표" not in serialized
    assert "reranker_binding=pass" in binding.summary_line(result)


def test_binding_rejects_revision_drift_and_prior_evidence_gap(tmp_path: Path) -> None:
    drift = binding.run_gb2_s20oa_immutable_reranker_binding(
        _env(
            tmp_path / "drift",
            NEX_MO_REMOTE_RERANKER_MODEL_REVISION="hf:" + "c" * 40,
        ),
        requester=_requester,
    )
    assert drift["status"] == "FAIL"
    assert drift["checks"]["configured_revision_matches_artifact"] is False

    env = _env(tmp_path / "prior")
    prior_path = Path(env[binding.S20O_EVIDENCE_ENV])
    prior = _s20o_evidence()
    prior["source_and_runtime_audit"]["findings"][
        "sequence_classifier_override_confirmed"
    ] = False
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    gap = binding.run_gb2_s20oa_immutable_reranker_binding(
        env, requester=_requester
    )
    assert gap["status"] == "FAIL"
    assert gap["checks"]["prior_s20o_runtime_gap_was_revision_only"] is False


def test_binding_fails_closed_for_evidence_and_provider_errors(
    tmp_path: Path,
) -> None:
    missing = binding.run_gb2_s20oa_immutable_reranker_binding(
        {binding.SMOKE_ENV: "1"}
    )
    assert missing["failure_code"] == "immutable_reranker_binding_failed"

    env = _env(tmp_path / "bad")
    Path(env[binding.ARTIFACT_EVIDENCE_ENV]).write_text("[]", encoding="utf-8")
    invalid = binding.run_gb2_s20oa_immutable_reranker_binding(env)
    assert invalid["status"] == "FAIL"

    provider = binding.run_gb2_s20oa_immutable_reranker_binding(
        _env(tmp_path / "provider"),
        requester=lambda *args, **kwargs: httpx.Response(503, json={}),
    )
    assert provider["status"] == "FAIL"

    unconfigured_env = _env(tmp_path / "unconfigured")
    unconfigured_env["NEX_MO_REMOTE_RERANKER_URL"] = ""
    unconfigured = binding.run_gb2_s20oa_immutable_reranker_binding(
        unconfigured_env,
        requester=_requester,
    )
    assert unconfigured["status"] == "FAIL"

    incomplete_env = _env(tmp_path / "incomplete")
    Path(incomplete_env[binding.S20O_EVIDENCE_ENV]).write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )
    incomplete = binding.run_gb2_s20oa_immutable_reranker_binding(
        incomplete_env,
        requester=_requester,
    )
    assert incomplete["status"] == "FAIL"


def test_ranked_response_validation_branches() -> None:
    assert binding._ranked_response(None) is False
    assert binding._ranked_response([{"index": 0, "score": 1.0}]) is False
    assert binding._ranked_response(
        [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]
    ) is False
    assert binding._ranked_response(["bad", "items"]) is False
    assert binding._ranked_response(
        [{"index": 0, "score": "bad"}, {"index": 1, "score": 0.1}]
    ) is False


def test_helpers_redaction_summaries_and_main(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    with pytest.raises(ValueError, match="required"):
        binding._required_path(None)
    with pytest.raises(ValueError, match="protected"):
        binding._assert_redacted(
            {"value": "http://secret.test"},
            {"NEX_MO_REMOTE_RERANKER_URL": "http://secret.test"},
        )
    assert "skipped" in binding.summary_line({"status": "SKIPPED"})
    assert "execution" in binding.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        binding,
        "run_gb2_s20oa_immutable_reranker_binding",
        lambda: {"status": "PASS", "binding": {"artifact_revision": REVISION}},
    )
    output = tmp_path / "main.json"
    assert binding.main(["--summary", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "reranker_binding=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        binding,
        "run_gb2_s20oa_immutable_reranker_binding",
        lambda: {"status": "FAIL"},
    )
    assert binding.main([]) == 1
