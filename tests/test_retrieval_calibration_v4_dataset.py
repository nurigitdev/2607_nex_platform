from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import check_retrieval_calibration_v4_dataset as checker
import pytest
from nex_runtime.semantic_hashes import sha256_text


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_canonical_v4_dataset_and_fold_plan_are_immutable() -> None:
    result = checker.check_retrieval_calibration_v4_dataset()

    assert result == {
        "status": "PASS",
        "dataset_id": "s136-retrieval-package-confidence-public-v4",
        "dataset_file_sha256": checker.FROZEN_DATASET_FILE_SHA256,
        "dataset_sha256": checker.FROZEN_DATASET_SHA256,
        "scenario_count": 100,
        "package_count": 200,
        "candidate_count": 800,
        "calibration_scenario_count": 80,
        "holdout_scenario_count": 20,
        "scenario_review_count": 100,
        "independent_review_passed": True,
        "v3_calibration_scenario_count": 30,
        "new_calibration_scenario_count": 50,
        "new_holdout_scenario_count": 20,
        "fold_plan_file_sha256": checker.FROZEN_FOLD_PLAN_FILE_SHA256,
        "fold_plan_hash": checker.FROZEN_FOLD_PLAN_HASH,
        "outer_fold_count": 5,
        "inner_fold_count": 4,
        "holdout_excluded_from_folds": True,
        "runtime_activation_permitted": False,
        "immutable": True,
    }
    summary = checker.summary_line(result)
    assert summary.startswith("retrieval_calibration_v4_dataset=pass")
    assert "scenarios=100 calibration=80 holdout=20" in summary
    assert checker.FROZEN_DATASET_SHA256 in summary
    assert checker.FROZEN_FOLD_PLAN_HASH in summary


def test_v3_content_is_preserved_only_in_calibration() -> None:
    v3 = json.loads(checker.DEFAULT_V3_PATH.read_text(encoding="utf-8"))
    v4 = json.loads(checker.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    v3_cases = {case["case_id"]: case for case in v3["cases"]}
    v4_cases = {case["case_id"]: case for case in v4["cases"]}

    for case_id, source in v3_cases.items():
        inherited = deepcopy(v4_cases[case_id])
        assert inherited.pop("partition") == "CALIBRATION"
        assert inherited == {key: value for key, value in source.items() if key != "partition"}
    v3_scenarios = {case["scenario_id"] for case in v3["cases"]}
    v4_holdout = {
        case["scenario_id"]
        for case in v4["cases"]
        if case["partition"] == "HOLDOUT"
    }
    assert len(v4_holdout) == 20
    assert not v4_holdout & v3_scenarios


def test_checker_rejects_dataset_file_and_semantic_drift(
    monkeypatch, tmp_path: Path
) -> None:
    payload = json.loads(checker.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["query"] += " changed"
    changed = tmp_path / "changed-dataset.json"
    _write_json(changed, payload)
    with pytest.raises(ValueError, match="dataset file digest"):
        checker.check_retrieval_calibration_v4_dataset(dataset_path=changed)

    exact_text = checker.DEFAULT_DATASET_PATH.read_text(encoding="utf-8")
    exact = tmp_path / "exact-dataset.json"
    exact.write_text(exact_text, encoding="utf-8")
    monkeypatch.setattr(checker, "FROZEN_DATASET_FILE_SHA256", sha256_text(exact_text))
    monkeypatch.setattr(checker, "FROZEN_DATASET_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="semantic digest"):
        checker.check_retrieval_calibration_v4_dataset(dataset_path=exact)


def test_checker_rejects_fold_file_materialization_and_hash_drift(
    monkeypatch, tmp_path: Path
) -> None:
    plan = json.loads(checker.DEFAULT_FOLD_PLAN_PATH.read_text(encoding="utf-8"))
    changed = tmp_path / "changed-folds.json"
    plan["status"] = "CHANGED"
    _write_json(changed, plan)
    with pytest.raises(ValueError, match="fold file digest"):
        checker.check_retrieval_calibration_v4_dataset(fold_plan_path=changed)
    changed_text = changed.read_text(encoding="utf-8")
    monkeypatch.setattr(
        checker,
        "FROZEN_FOLD_PLAN_FILE_SHA256",
        sha256_text(changed_text),
    )
    with pytest.raises(ValueError, match="fold materialization"):
        checker.check_retrieval_calibration_v4_dataset(fold_plan_path=changed)

    exact_text = checker.DEFAULT_FOLD_PLAN_PATH.read_text(encoding="utf-8")
    exact = tmp_path / "exact-folds.json"
    exact.write_text(exact_text, encoding="utf-8")
    monkeypatch.setattr(
        checker,
        "FROZEN_FOLD_PLAN_FILE_SHA256",
        sha256_text(exact_text),
    )
    monkeypatch.setattr(checker, "FROZEN_FOLD_PLAN_HASH", "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="fold semantic digest"):
        checker.check_retrieval_calibration_v4_dataset(fold_plan_path=exact)


def test_checker_rejects_v3_continuity_and_holdout_reuse() -> None:
    v3 = json.loads(checker.DEFAULT_V3_PATH.read_text(encoding="utf-8"))
    v4 = json.loads(checker.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))

    missing = deepcopy(v4)
    inherited_id = v3["cases"][0]["case_id"]
    missing["cases"] = [
        case for case in missing["cases"] if case["case_id"] != inherited_id
    ]
    with pytest.raises(ValueError, match="case missing"):
        checker._require_v3_calibration_continuity(v3, missing)

    changed = deepcopy(v4)
    changed_case = next(
        case for case in changed["cases"] if case["case_id"] == inherited_id
    )
    changed_case["query"] += " changed"
    with pytest.raises(ValueError, match="content mismatch"):
        checker._require_v3_calibration_continuity(v3, changed)

    reused = deepcopy(v4)
    reused_case = next(
        case
        for case in reused["cases"]
        if case["scenario_id"] == v3["cases"][0]["scenario_id"]
    )
    reused_case["partition"] = "HOLDOUT"
    with pytest.raises(ValueError, match="must not reuse"):
        checker._require_v3_calibration_continuity(v3, reused)


def test_cli_success_and_redacted_failure(tmp_path: Path, capsys) -> None:
    assert checker.main(["--summary"]) == 0
    assert "retrieval_calibration_v4_dataset=pass" in capsys.readouterr().out

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    assert checker.main(["--dataset", str(malformed)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "detail": "ValueError",
        "status": "FAIL",
    }
