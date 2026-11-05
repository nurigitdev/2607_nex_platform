from __future__ import annotations

import json

import pytest
import run_gb2_s20qpp_pre_holdout_freeze as smoke


def _source() -> dict:
    return {
        "status": "PASS",
        "decision": "CANONICAL_THRESHOLD_CANDIDATE_ADMITTED_HOLDOUT_REQUIRED",
        "calibration": {},
        "checks": {"candidate": True, "holdout": True},
    }


def _dataset_manifest() -> dict:
    return {"status": "PASS", "immutable": True}


def _freeze() -> dict:
    return {
        "status": "HOLDOUT_ONE_SHOT_EXECUTION_ARMED",
        "execution_id": "s20qpq-execution",
        "authorization": {
            "candidate": {
                "profile_id": "answer-support-contradiction-aware-v2",
                "threshold": 0.46375,
            },
            "protocol": {
                "maximum_execution_attempts": 1,
                "expected_provider_evaluations": 40,
                "maximum_provider_http_requests": 40,
            },
        },
        "receipt_contract": {
            "receipt_path": smoke.HOLDOUT_RECEIPT_PATH,
            "required_execution_id": "s20qpq-execution",
            "reservation_write_mode": "ATOMIC_CREATE_EXCLUSIVE",
            "reservation_required_before_provider_call": True,
        },
        "safety": {"holdout_executed_in_this_slice": False},
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "runtime_activation_permitted": False,
    }


def _freezer(**kwargs) -> dict:
    assert kwargs["p_o_calibration"] == {}
    assert kwargs["dataset_manifest"] == _dataset_manifest()
    assert kwargs["existing_receipt"] is None
    return _freeze()


def test_skip_profile_and_missing_source_guards() -> None:
    assert smoke.run_gb2_s20qpp_pre_holdout_freeze({})["status"] == "SKIPPED"
    assert smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {
            smoke.SMOKE_ENV: "1",
            smoke.P_O_SOURCE_ENV: "/missing/p-o.json",
        }
    )
    assert result["failure_code"] == "pre_holdout_freeze_failed"


def test_runner_arms_holdout_without_provider_or_database_calls() -> None:
    result = smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {smoke.SMOKE_ENV: "1"},
        p_o_source=_source(),
        design={},
        dataset_checker=_dataset_manifest,
        receipt_loader=lambda _path: None,
        freezer=_freezer,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "HOLDOUT_ONE_SHOT_EXECUTION_ARMED_P_Q_REQUIRED"
    assert result["new_provider_calls"] == 0
    assert "execution_id=s20qpq-execution" in smoke.summary_line(result)


def test_runner_passes_existing_receipt_to_fail_closed_freezer(tmp_path) -> None:
    observed = {}

    def freezer(**kwargs):
        observed.update(kwargs)
        raise ValueError("consumed")

    result = smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {
            smoke.SMOKE_ENV: "1",
            smoke.RECEIPT_PATH_ENV: str(tmp_path / "receipt.json"),
        },
        p_o_source=_source(),
        design={},
        dataset_checker=_dataset_manifest,
        receipt_loader=lambda path: {"path": str(path)},
        freezer=freezer,
    )

    assert observed["existing_receipt"]["path"].endswith("receipt.json")
    assert result["failure_code"] == "pre_holdout_freeze_failed"


def test_runner_reports_source_and_freeze_check_failures() -> None:
    source = _source()
    source["status"] = "FAIL"
    result = smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {smoke.SMOKE_ENV: "1"},
        p_o_source=source,
        design={},
        dataset_checker=_dataset_manifest,
        receipt_loader=lambda _path: None,
        freezer=_freezer,
    )
    assert result["status"] == "FAIL"
    assert "p_o_evidence_passed" in result["failed_checks"]

    freeze = _freeze()
    freeze["new_provider_calls"] = 1
    result = smoke.run_gb2_s20qpp_pre_holdout_freeze(
        {smoke.SMOKE_ENV: "1"},
        p_o_source=_source(),
        design={},
        dataset_checker=_dataset_manifest,
        receipt_loader=lambda _path: None,
        freezer=lambda **_kwargs: freeze,
    )
    assert result["status"] == "FAIL"
    assert "provider_not_called" in result["failed_checks"]


def test_helpers_summary_and_main(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source()), encoding="utf-8")
    assert smoke._load(source) == _source()
    assert smoke._load_optional(tmp_path / "missing.json") is None
    assert smoke._load_optional(source) == _source()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="object"):
        smoke._load(invalid)
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpp_pre_holdout_freeze",
        lambda: {"status": "PASS", "freeze": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text()
    assert "=pass" in capsys.readouterr().out
