from __future__ import annotations

import json

import pytest
import run_gb2_s20qpj_nested_answer_support_calibration as smoke
from check_retrieval_calibration_v4_dataset import (
    check_retrieval_calibration_v4_dataset,
)

HASH = "sha256:" + "a" * 64
REVISION = "hf:" + "b" * 40


def _source() -> dict:
    admission = check_retrieval_calibration_v4_dataset()
    checks = {
        "dataset": True,
        "holdout": True,
        "runtime": True,
    }
    return {
        "status": "PASS",
        "decision": "CALIBRATION_EVIDENCE_COLLECTED_P_J_REQUIRED",
        "source_database_identity": {
            "database": "nex_cx_test",
            "role": "nex_cx_user",
        },
        "artifact_revision": REVISION,
        "provider_evaluation_count": 160,
        "checks": checks,
        "collection": {
            "collection_hash": HASH,
            "dataset": {
                "dataset_id": admission["dataset_id"],
                "dataset_sha256": admission["dataset_sha256"],
                "package_count": 160,
                "holdout_status": "SEALED_NOT_ACCESSED",
            },
            "provider_binding": {"model_revision": REVISION},
        },
    }


def _selection(*, admitted: bool) -> dict:
    inner = [
        {
            "inner_folds": [
                {"training_package_count": 96, "metrics": {}}
            ]
        }
    ]
    return {
        "status": (
            "CALIBRATION_OOF_ADMITTED" if admitted else "NO_ADMISSIBLE_PROFILE"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {"scenario_count": 80, "package_count": 160},
        "outer_folds": [{"inner_selection": inner}],
        "oof_evaluation": {
            "metrics": {"ready_recall": 1.0, "false_ready_rate": 0.025},
            "stable_profile_fold_count": 3,
        },
        "holdout": {"status": "SEALED_NOT_OPENED"},
    }


def _builder(collection, cases):
    assert collection["collection_hash"] == HASH
    assert cases
    return [{"sample": True}]


def test_skip_profile_and_missing_source_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpj_nested_answer_support_calibration({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    assert smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: str(tmp_path / "missing.json")}
    )["failure_code"] == "source_evidence_missing"


@pytest.mark.parametrize("admitted", [False, True])
def test_runner_accepts_admitted_or_fail_closed_nested_result(admitted) -> None:
    result = smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        sample_builder=_builder,
        selector=lambda *_args, **_kwargs: _selection(admitted=admitted),
    )

    assert result["status"] == "PASS"
    assert result["new_provider_calls"] == 0
    assert result["new_database_calls"] == 0
    assert result["decision"] == (
        "CALIBRATION_OOF_ADMITTED_KEEP_HOLDOUT_SEALED"
        if admitted
        else "NO_ADMISSIBLE_PROFILE_KEEP_HOLDOUT_SEALED"
    )
    assert "holdout=sealed" in smoke.summary_line(result)


def test_runner_fails_on_source_drift_and_nested_exception() -> None:
    source = _source()
    source["checks"]["holdout"] = False
    result = smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1"},
        source=source,
        sample_builder=_builder,
        selector=lambda *_args, **_kwargs: _selection(admitted=False),
    )
    assert result["status"] == "FAIL"
    assert "p_i_checks_all_passed" in result["failed_checks"]

    result = smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        sample_builder=lambda *_args: (_ for _ in ()).throw(ValueError("bad")),
    )
    assert result["failure_code"] == "nested_calibration_failed"
    assert result["failure_detail"] == {"exception": "ValueError"}


def test_invalid_source_redaction_helpers_and_main(tmp_path, monkeypatch, capsys) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text("[]", encoding="utf-8")
    result = smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: str(source_path)}
    )
    assert result["failure_code"] == "source_evidence_invalid"

    dataset = json.loads(smoke.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="source text"):
        smoke._assert_text_free(
            {"leak": dataset["cases"][0]["query"]}, dataset
        )
    with pytest.raises(TypeError, match="cases"):
        smoke._assert_text_free({}, {"cases": {}})
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpj_nested_answer_support_calibration",
        lambda: {"status": "PASS", "selection": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out


def test_runner_rejects_source_text_in_protected_result() -> None:
    dataset = json.loads(smoke.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    selection = _selection(admitted=False)
    selection["leak"] = dataset["cases"][0]["query"]
    result = smoke.run_gb2_s20qpj_nested_answer_support_calibration(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        sample_builder=_builder,
        selector=lambda *_args, **_kwargs: selection,
    )
    assert result["failure_code"] == "protected_evidence_contains_source_text"
