from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import run_gb2_s20qpi_answer_support_calibration_collection as smoke
from check_retrieval_calibration_v4_dataset import (
    DEFAULT_DATASET_PATH,
    check_retrieval_calibration_v4_dataset,
)

REVISION = "hf:" + "a" * 40


def _dataset() -> dict:
    return json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))


def _artifact() -> dict:
    return {
        "schema_version": "model_artifact_revision.v1",
        "status": "PASS",
        "revision_source": "HUGGINGFACE_LOCAL_METADATA",
        "artifact_revision": REVISION,
        "metadata_file_count": 3,
        "metadata_target_count": 3,
        "weight_artifact_count": 1,
        "metadata_manifest_digest": "sha256:" + "b" * 64,
        "model_path_persisted": False,
        "artifact_content_persisted": False,
    }


def _source() -> dict:
    dataset = _dataset()
    admission = check_retrieval_calibration_v4_dataset()
    observations = []
    for case in dataset["cases"]:
        if case["partition"] != "CALIBRATION":
            continue
        sample_id = (
            f"{case['scenario_id']}:"
            f"{'positive' if case['expected_ready'] else 'negative'}"
        )
        observations.extend(
            {"sample_id": sample_id, "candidate_id": row["candidate_id"]}
            for row in case["candidates"]
        )
    return {
        "status": "PASS",
        "slice_id": "GB2-CA00-S20Q-P-C-A",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "dataset": {
            "dataset_id": admission["dataset_id"],
            "dataset_sha256": admission["dataset_sha256"],
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "repeat_collection": {"runs": [{"candidate_observations": observations}]},
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _environment(tmp_path: Path) -> dict[str, str]:
    source = _write(tmp_path / "source.json", _source())
    artifact = _write(tmp_path / "artifact.json", _artifact())
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.SOURCE_ENV: str(source),
        smoke.ARTIFACT_ENV: str(artifact),
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://provider.test/v1/chat/completions",
        "NEX_MO_VLLM_API_KEY": "protected-test-key",
        "NEX_MO_VLLM_MODEL": "generation-model",
        "NEX_MO_VLLM_MODEL_REVISION": REVISION,
        "NEX_MO_VLLM_DEPLOYMENT_ID": "generation-deployment",
    }


def _requester(method: str, url: str, **kwargs):
    body = kwargs["json"]
    user = json.loads(body["messages"][1]["content"])
    items = []
    for index, candidate in enumerate(user["candidates"]):
        if index == 0:
            classification, support, contradiction = "DIRECT_ANSWER", 0.8, 0.1
        else:
            classification, support, contradiction = "TOPICAL_NON_ANSWER", 0.2, 0.1
        items.append(
            {
                "candidate_id": candidate["candidate_id"],
                "classification": classification,
                "answer_support_score": support,
                "contradiction_score": contradiction,
            }
        )
    return httpx.Response(
        200,
        request=httpx.Request(method, url),
        json={
            "id": f"generation-{len(items)}",
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps({"items": items})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        },
    )


def test_skip_profile_and_configuration_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpi_answer_support_calibration_collection({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpi_answer_support_calibration_collection(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpi_answer_support_calibration_collection(
        {smoke.SMOKE_ENV: "1"}
    )
    assert result["failure_code"] == "configuration_invalid"
    assert "generation_endpoint" in result["failure_detail"]


def test_protected_collection_runs_all_calibration_packages(tmp_path) -> None:
    result = smoke.run_gb2_s20qpi_answer_support_calibration_collection(
        _environment(tmp_path), requester=_requester
    )

    assert result["status"] == "PASS"
    assert result["provider_evaluation_count"] == 160
    assert result["provider_maximum_concurrency"] == 4
    assert result["provider_http_request_counts"] == {
        "total": 160,
        "generation": 160,
        "holdout_blocked": 0,
    }
    assert result["collection"]["dataset"]["candidate_count"] == 640
    assert result["artifact_revision"] == REVISION
    assert all(result["checks"].values())
    assert "packages=160" in smoke.summary_line(result)
    serialized = json.dumps(result)
    assert "protected-test-key" not in serialized
    assert _dataset()["cases"][0]["query"] not in serialized


def test_revision_drift_and_invalid_collection_fail_closed(tmp_path) -> None:
    env = _environment(tmp_path)
    env["NEX_MO_VLLM_MODEL_REVISION"] = "hf:" + "c" * 40
    result = smoke.run_gb2_s20qpi_answer_support_calibration_collection(env)
    assert result["failure_code"] == "collection_failed"
    assert result["failure_detail"] == {"exception": "ValueError"}

    def broken(*args, **kwargs):
        return {"status": "BROKEN"}

    result = smoke.run_gb2_s20qpi_answer_support_calibration_collection(
        _environment(tmp_path), requester=_requester, collector=broken
    )
    assert result["failure_code"] == "collection_failed"


def test_partition_source_and_holdout_request_guards() -> None:
    dataset = _dataset()
    calibration, holdout_values = smoke._calibration_cases(dataset)
    assert len(calibration) == 160
    assert len(holdout_values) == 200
    admission = check_retrieval_calibration_v4_dataset()
    alignment = smoke._source_alignment(_source(), calibration, admission)
    assert alignment["candidate_count"] == 640

    source = _source()
    source["dataset"]["dataset_sha256"] = "drift"
    with pytest.raises(ValueError, match="dataset binding"):
        smoke._source_alignment(source, calibration, admission)

    env = {
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://provider.test/chat",
        "NEX_MO_VLLM_MODEL": "model",
    }
    requester, counts = smoke._holdout_guarded_requester(
        lambda *args, **kwargs: None,
        holdout_values=("sealed text",),
        environ=env,
    )
    with pytest.raises(ValueError, match="HOLDOUT"):
        requester("POST", "http://provider.test/chat", json={"text": "sealed text"})
    assert counts["holdout_blocked"] == 1

    requester("GET", "http://provider.test/health", json={})
    assert counts == {"total": 1, "generation": 0, "holdout_blocked": 1}


def test_partition_and_source_scope_fail_closed() -> None:
    with pytest.raises(TypeError, match="cases"):
        smoke._calibration_cases({"cases": {}})

    dataset = _dataset()
    dataset["cases"] = dataset["cases"][:-1]
    with pytest.raises(ValueError, match="partitions"):
        smoke._calibration_cases(dataset)

    admission = check_retrieval_calibration_v4_dataset()
    calibration, _ = smoke._calibration_cases(_dataset())
    source = _source()
    source["status"] = "FAIL"
    with pytest.raises(ValueError, match="not admitted"):
        smoke._source_alignment(source, calibration, admission)

    source = _source()
    source["repeat_collection"]["runs"][0]["candidate_observations"].pop()
    with pytest.raises(ValueError, match="candidate scope"):
        smoke._source_alignment(source, calibration, admission)


def test_loader_redaction_summary_and_main(tmp_path, monkeypatch, capsys) -> None:
    mapping = _write(tmp_path / "mapping.json", {"status": "PASS"})
    assert smoke._load_json(mapping) == {"status": "PASS"}
    sequence = tmp_path / "sequence.json"
    sequence.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="object"):
        smoke._load_json(sequence)
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "secret-value"},
            {"NEX_MO_VLLM_API_KEY": "secret-value"},
        )
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "error" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "error"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpi_answer_support_calibration_collection",
        lambda: {"status": "PASS", "collection": {"dataset": {}}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out

    assert smoke._failure("bare") == {
        "evidence_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "bare",
    }

    dataset = _dataset()
    first = dataset["cases"][0]
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": first["candidates"][0]["text"]},
            {},
            dataset=dataset,
        )
