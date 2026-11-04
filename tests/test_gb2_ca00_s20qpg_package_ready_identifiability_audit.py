from __future__ import annotations

from copy import deepcopy

import pytest
import run_gb2_s20qpg_package_ready_identifiability_audit as smoke


def _source() -> dict:
    return {
        "status": "PASS",
        "binding": {"embedding_model_revision": "embedding"},
        "nested_selection": {
            "status": "NO_ADMISSIBLE_PROFILE",
            "holdout_access_permitted": False,
            "holdout": {"status": "SEALED_NOT_OPENED"},
        },
        "repeat_collection": {
            "runs": [{"candidate_observations": [{"placeholder": True}]}]
        },
        "provider_request_counts": {"total": 2240},
    }


def _selection() -> dict:
    return {
        "status": "PASS",
        "selection": {
            "status": "NO_ADMISSIBLE_PROFILE",
            "holdout": {"status": "SEALED_NOT_OPENED"},
        },
    }


def _dataset() -> dict:
    return {
        "cases": [
            {
                "scenario_id": "scenario-1",
                "partition": "CALIBRATION",
                "expected_ready": False,
                "domain": "FINANCE",
                "language_profile": "KOREAN",
            },
            {
                "scenario_id": "scenario-1",
                "partition": "CALIBRATION",
                "expected_ready": True,
                "domain": "FINANCE",
                "language_profile": "KOREAN",
            },
            {
                "scenario_id": "scenario-2",
                "partition": "HOLDOUT",
                "expected_ready": True,
                "domain": "PROJECT",
                "language_profile": "ENGLISH",
            },
        ]
    }


def _audit() -> dict:
    return {
        "status": "DIAGNOSED",
        "decision": "ANSWERABILITY_SIGNAL_REQUIRED",
        "identifiability": {
            "selected_diagnostic_combination": {
                "best_safety_point": {
                    "ready_recall": 0.2,
                    "false_ready_rate": 0.05,
                }
            }
        },
        "next_contract": {
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
    }


def test_skip_profile_and_missing_evidence_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpg_package_ready_identifiability_audit({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SOURCE_ENV: str(tmp_path / "missing-source.json"),
        }
    )
    assert result["failure_code"] == "source_evidence_missing"
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SELECTION_ENV: str(tmp_path / "missing-selection.json"),
        },
        source=_source(),
    )
    assert result["failure_code"] == "selection_evidence_missing"

    original = smoke.DATASET_PATH
    smoke.DATASET_PATH = tmp_path / "missing-dataset.json"
    try:
        result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
            {smoke.SMOKE_ENV: "1"},
            source=_source(),
            selection_source=_selection(),
        )
    finally:
        smoke.DATASET_PATH = original
    assert result["failure_code"] == "dataset_missing"


def test_runner_records_bounded_corrective_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "audit_package_ready_identifiability", lambda *args, **kwargs: _audit()
    )
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        selection_source=_selection(),
        dataset=_dataset(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "ANSWERABILITY_SIGNAL_REQUIRED"
    assert result["provider_calls"] == 0
    assert result["holdout_opened"] is False
    assert "safe_recall=0.2" in smoke.summary_line(result)


def test_runner_rejects_source_drift_and_missing_observations(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "audit_package_ready_identifiability", lambda *args, **kwargs: _audit()
    )
    source = _source()
    source["status"] = "FAIL"
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {smoke.SMOKE_ENV: "1"},
        source=source,
        selection_source=_selection(),
        dataset=_dataset(),
    )
    assert result["status"] == "FAIL"
    assert "source_execution_passed" in result["failed_checks"]

    missing = deepcopy(_source())
    missing["repeat_collection"] = {}
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {smoke.SMOKE_ENV: "1"},
        source=missing,
        selection_source=_selection(),
        dataset=_dataset(),
    )
    assert result["failure_code"] == "candidate_observations_missing"


def test_runner_maps_invalid_audit_input_to_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise ValueError("drift")

    monkeypatch.setattr(smoke, "audit_package_ready_identifiability", fail)
    result = smoke.run_gb2_s20qpg_package_ready_identifiability_audit(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        selection_source=_selection(),
        dataset=_dataset(),
    )
    assert result["failure_code"] == "audit_input_invalid"
    assert result["failure_detail"] == "drift"


def test_dataset_metadata_guard_matrix() -> None:
    assert set(smoke._calibration_package_metadata(_dataset())) == {
        "scenario-1:negative",
        "scenario-1:positive",
    }
    with pytest.raises(TypeError, match="cases"):
        smoke._calibration_package_metadata({})
    duplicate = _dataset()
    duplicate["cases"].append(dict(duplicate["cases"][0]))
    with pytest.raises(ValueError, match="duplicated"):
        smoke._calibration_package_metadata(duplicate)
    with pytest.raises(ValueError, match="packages are missing"):
        smoke._calibration_package_metadata({"cases": []})
    invalid_ready = _dataset()
    invalid_ready["cases"][0]["expected_ready"] = "no"
    with pytest.raises(TypeError, match="expected_ready"):
        smoke._calibration_package_metadata(invalid_ready)
    invalid_domain = _dataset()
    invalid_domain["cases"][0]["domain"] = ""
    with pytest.raises(ValueError, match="domain"):
        smoke._calibration_package_metadata(invalid_domain)


def test_json_loader_and_failure_summary(tmp_path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text('{"status": "PASS"}', encoding="utf-8")
    assert smoke._load_json(valid) == {"status": "PASS"}
    sequence = tmp_path / "sequence.json"
    sequence.write_text("[]", encoding="utf-8")
    assert smoke._load_json(sequence) is None
    assert "checks=broken" in smoke.summary_line(
        {"status": "FAIL", "failed_checks": ["broken"]}
    )


def test_main_writes_evidence(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "audit.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpg_package_ready_identifiability_audit",
        lambda: {"status": "PASS", "decision": "done", "audit": _audit()},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpg_package_ready_identifiability_audit",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "=skipped" in capsys.readouterr().out
