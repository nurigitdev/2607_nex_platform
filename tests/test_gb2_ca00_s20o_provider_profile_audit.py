from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
import run_gb2_s20o_provider_profile_audit as audit


def _env(*, runtime_confirmed: bool = False, **overrides: str) -> dict[str, str]:
    values = {
        audit.SMOKE_ENV: "1",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.test:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "protected-key",
        **audit.protected_dgx_vllm_profile_defaults(),
    }
    if runtime_confirmed:
        values.update(
            {
                "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "hf:abc123",
                audit.RUNTIME_ENV["vllm_version"]: "0.23.0",
                audit.RUNTIME_ENV["model_source_revision"]: "hf:abc123",
                audit.RUNTIME_ENV["sequence_classifier_override"]: "1",
                audit.RUNTIME_ENV["qwen3_reranker_template"]: "true",
            }
        )
    return {**values, **overrides}


def _observations(
    *,
    profile_id: str,
    dataset_key: str,
    separable: bool,
    overlap_shift: float = 0.0,
    model_revision: str = "Qwen3-Reranker-4B",
) -> list[dict]:
    dataset = json.loads(
        (
            audit.DEFAULT_V1_PATH if dataset_key == "v1" else audit.DEFAULT_V2_PATH
        ).read_text(encoding="utf-8")
    )
    cases = dataset["cases"]
    if dataset_key == "v2_calibration":
        cases = [case for case in cases if case.get("partition") == "CALIBRATION"]
    result = []
    for case in cases:
        for document in case["documents"]:
            ready = document["expected_ready"]
            if separable:
                score = 0.85 if ready else 0.15
            else:
                score = (0.55 if ready else 0.50) + overlap_shift
                if document["document_id"] in {"hard-negative", "easy-negative"}:
                    score = 0.65 + overlap_shift
            result.append(
                {
                    "profile_id": profile_id,
                    "dataset_key": dataset_key,
                    "pair_id": f"{case['case_id']}:{document['document_id']}",
                    "partition": case.get("partition", "FROZEN_V1"),
                    "relevance_grade": document.get(
                        "relevance_grade", "POSITIVE" if ready else "NEGATIVE"
                    ),
                    "expected_ready": ready,
                    "score": score,
                    "model_revision": model_revision,
                    "deployment_id": "vllm-reranker-http",
                }
            )
    return result


def _all_observations(
    *,
    explicit_separable: bool,
    model_revision: str = "Qwen3-Reranker-4B",
) -> list[dict]:
    observations = []
    for profile_id, separable in (
        (audit.V1_PROFILE_ID, False),
        (audit.V2_PROFILE_ID, explicit_separable),
    ):
        for dataset_key in ("v1", "v2_calibration"):
            observations.extend(
                _observations(
                    profile_id=profile_id,
                    dataset_key=dataset_key,
                    separable=separable,
                    model_revision=model_revision,
                )
            )
    return observations


def test_skip_and_runtime_profile_gap_decision(monkeypatch) -> None:
    assert audit.run_gb2_s20o_provider_profile_audit({})["status"] == "SKIPPED"

    observations = _all_observations(explicit_separable=True)
    monkeypatch.setattr(
        audit,
        "_collect_profile_observations",
        lambda _dataset, *, dataset_key, profile_id, **_kwargs: [
            item
            for item in observations
            if item["dataset_key"] == dataset_key and item["profile_id"] == profile_id
        ],
    )
    result = audit.run_gb2_s20o_provider_profile_audit(_env())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["decision"]["code"] == (
        "PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED"
    )
    assert result["decision"]["score_profile_assessment"]["code"] == (
        "REQUEST_PROFILE_ISSUE_CONFIRMED"
    )
    assert result["dataset_binding"]["v2_holdout_status"] == "SEALED_NOT_OPENED"
    assert len(result["score_observations"]) == 232
    assert result["source_and_runtime_audit"]["runtime_profile_confirmed"] is False
    serialized = json.dumps(result, ensure_ascii=False)
    assert "http://dgx.test" not in serialized
    assert "protected-key" not in serialized
    assert "새 프로젝트를 생성" not in serialized
    assert "decision=PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED" in (
        audit.summary_line(result)
    )


def test_confirmed_runtime_identifies_request_profile_issue(monkeypatch) -> None:
    observations = _all_observations(
        explicit_separable=True,
        model_revision="hf:abc123",
    )
    monkeypatch.setattr(
        audit,
        "_collect_profile_observations",
        lambda _dataset, *, dataset_key, profile_id, **_kwargs: [
            item
            for item in observations
            if item["dataset_key"] == dataset_key and item["profile_id"] == profile_id
        ],
    )
    result = audit.run_gb2_s20o_provider_profile_audit(_env(runtime_confirmed=True))

    assert result["status"] == "PASS"
    assert result["decision"]["code"] == "REQUEST_PROFILE_ISSUE_CONFIRMED"
    assert result["decision"]["score_profile_assessment"]["code"] == (
        "REQUEST_PROFILE_ISSUE_CONFIRMED"
    )
    assert result["decision"]["runtime_activation_allowed"] is False
    assert result["request_profiles"][1]["instruction_hash"].startswith("sha256:")
    assert "instruction" not in result["request_profiles"][1]


def test_profile_requester_injects_instruction_without_product_contract_change() -> (
    None
):
    captured = {}

    def requester(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return object()

    wrapped = audit._profile_requester(
        requester,
        instruction="enterprise instruction",
    )
    assert wrapped is not None
    marker = wrapped(
        "POST",
        "http://provider.test/v1/rerank",
        json={"query": "q", "documents": ["d"]},
    )
    assert marker is not None
    assert captured["json"]["instruction"] == "enterprise instruction"
    assert audit._profile_requester(requester, instruction=None) is requester
    with pytest.raises(ValueError, match="non-empty"):
        audit._profile_requester(requester, instruction="")
    wrapped = audit._profile_requester(requester, instruction="valid")
    with pytest.raises(TypeError, match="JSON"):
        wrapped("POST", "http://provider.test", json=[])


def test_decision_branches_cover_contribution_and_single_score_limit() -> None:
    confirmed = {"runtime_profile_confirmed": True}
    contribution = audit._evaluate_profiles(_all_observations(explicit_separable=False))
    contribution[audit.V2_PROFILE_ID]["v2_calibration"]["score_distribution"][
        "overlap"
    ] = 0.05
    contribution_decision = audit._profile_decision(
        source_audit=confirmed,
        evaluation=contribution,
    )
    assert contribution_decision["code"] == (
        "REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS"
    )
    assert contribution_decision["score_profile_assessment"]["code"] == (
        "REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS"
    )

    no_improvement = deepcopy(contribution)
    no_improvement[audit.V2_PROFILE_ID]["v2_calibration"]["score_distribution"][
        "overlap"
    ] = no_improvement[audit.V1_PROFILE_ID]["v2_calibration"]["score_distribution"][
        "overlap"
    ]
    assert (
        audit._profile_decision(
            source_audit=confirmed,
            evaluation=no_improvement,
        )["code"]
        == "GENUINE_SINGLE_SCORE_LIMITATION_CONFIRMED"
    )


def test_collection_and_response_validation(monkeypatch) -> None:
    dataset = {
        "cases": [
            {
                "case_id": "case",
                "query": "query",
                "documents": [
                    {
                        "document_id": "document",
                        "text": "text",
                        "expected_ready": True,
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(
        audit,
        "execute_remote_rerank_request",
        lambda *_args, **_kwargs: {
            "model_revision": "model",
            "deployment_id": "deployment",
            "results": [{"index": 0, "score": 0.75}],
        },
    )
    observed = audit._collect_profile_observations(
        dataset,
        dataset_key="v1",
        profile_id=audit.V1_PROFILE_ID,
        environ=_env(),
        requester=None,
    )
    assert observed[0]["score"] == 0.75
    assert observed[0]["relevance_grade"] == "POSITIVE"

    with pytest.raises(ValueError, match="cases"):
        audit._collect_profile_observations(
            {},
            dataset_key="v1",
            profile_id=audit.V1_PROFILE_ID,
            environ=_env(),
            requester=None,
        )
    with pytest.raises(TypeError, match="object"):
        audit._collect_profile_observations(
            {"cases": [None]},
            dataset_key="v1",
            profile_id=audit.V1_PROFILE_ID,
            environ=_env(),
            requester=None,
        )
    with pytest.raises(ValueError, match="documents"):
        audit._collect_profile_observations(
            {"cases": [{"case_id": "case", "query": "query", "documents": []}]},
            dataset_key="v1",
            profile_id=audit.V1_PROFILE_ID,
            environ=_env(),
            requester=None,
        )
    with pytest.raises(TypeError, match="document"):
        audit._collect_profile_observations(
            {"cases": [{"case_id": "case", "query": "query", "documents": [None]}]},
            dataset_key="v1",
            profile_id=audit.V1_PROFILE_ID,
            environ=_env(),
            requester=None,
        )
    malformed_label = deepcopy(dataset)
    malformed_label["cases"][0]["documents"][0]["expected_ready"] = "yes"
    with pytest.raises(ValueError, match="boolean"):
        audit._collect_profile_observations(
            malformed_label,
            dataset_key="v1",
            profile_id=audit.V1_PROFILE_ID,
            environ=_env(),
            requester=None,
        )


@pytest.mark.parametrize(
    "results",
    [
        None,
        [{"index": 0, "score": 0.5}, {"index": 1, "score": 0.4}],
        ["bad"],
        [{"index": "0", "score": 0.5}],
        [{"index": 0, "score": True}],
        [{"index": 0, "score": 0.5}, {"index": 0, "score": 0.4}],
        [{"index": 1, "score": 0.5}],
    ],
)
def test_response_validation_fails_closed(results) -> None:
    with pytest.raises((TypeError, ValueError)):
        audit._scores_by_index({"results": results}, 1)


def test_dataset_runtime_and_redaction_guards(tmp_path: Path) -> None:
    dataset = json.loads(audit.DEFAULT_V2_PATH.read_text(encoding="utf-8"))
    calibration = audit._v2_calibration_dataset(dataset)
    assert len(calibration["cases"]) == 20
    with pytest.raises(TypeError, match="invalid"):
        audit._v2_calibration_dataset({})
    with pytest.raises(ValueError, match="incomplete"):
        audit._v2_calibration_dataset({"cases": []})

    assert audit._runtime_confirmation(None) == "UNCONFIRMED"
    assert audit._runtime_confirmation("yes") == "CONFIRMED"
    assert audit._runtime_confirmation("off") == "NOT_CONFIGURED"
    with pytest.raises(ValueError, match="boolean"):
        audit._runtime_confirmation("maybe")
    assert audit._runtime_value(" value ") == "value"
    assert audit._runtime_value(None) == "UNCONFIRMED"
    with pytest.raises(ValueError, match="non-empty"):
        audit._required_string(" ", "field")

    assert audit._scores_finite_and_bounded([{"score": 0.5}]) is True
    assert audit._scores_finite_and_bounded([{"score": math.nan}]) is False
    assert audit._scores_finite_and_bounded([{"score": 1.1}]) is False

    with pytest.raises(ValueError, match="protected"):
        audit._assert_redacted(
            {"leak": "protected-key"},
            _env(),
            (audit.DEFAULT_V1_PATH,),
        )
    audit._assert_redacted(
        {"safe": True},
        _env(),
        (tmp_path / "missing.json",),
    )
    array_path = tmp_path / "array.json"
    array_path.write_text("[]", encoding="utf-8")
    audit._assert_redacted({"safe": True}, _env(), (array_path,))


def test_execution_failure_cli_and_summary_paths(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    missing = audit.run_gb2_s20o_provider_profile_audit(
        _env(NEX_MO_REMOTE_RERANKER_URL="")
    )
    assert missing["status"] == "FAIL"
    assert missing["detail"] == "ValueError"
    assert audit.summary_line(missing).endswith("checks=execution")

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        audit,
        "run_gb2_s20o_provider_profile_audit",
        lambda **_kwargs: {"status": "SKIPPED"},
    )
    assert audit.main(["--summary", "--output", str(output)]) == 0
    assert "=skipped" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    monkeypatch.setattr(
        audit,
        "run_gb2_s20o_provider_profile_audit",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
