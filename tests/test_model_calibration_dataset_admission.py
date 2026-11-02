from __future__ import annotations

import json
from pathlib import Path

import check_model_calibration_dataset as admission
import pytest


def test_canonical_datasets_are_admitted_and_immutable() -> None:
    result = admission.admit_calibration_dataset_files()

    assert result["status"] == "PASS"
    assert result["v1"] == {
        "dataset_id": "s136-reranker-relevance-public-v1",
        "file_sha256": admission.FROZEN_V1_FILE_SHA256,
        "immutable": True,
    }
    assert result["v2"]["query_count"] == 30
    assert result["v2"]["pair_count"] == 120
    assert result["v2"]["positive_count"] == 60
    assert result["v2"]["negative_count"] == 60
    assert result["v2"]["dataset_sha256"] == admission.FROZEN_V2_DATASET_SHA256
    assert result["v2"]["file_sha256"] == admission.FROZEN_V2_FILE_SHA256
    assert result["v2"]["immutable"] is True
    assert result["v3"]["scenario_count"] == 30
    assert result["v3"]["package_count"] == 60
    assert result["v3"]["candidate_count"] == 240
    assert result["v3"]["ready_package_count"] == 30
    assert result["v3"]["low_confidence_package_count"] == 30
    assert result["v3"]["dataset_sha256"] == admission.FROZEN_V3_DATASET_SHA256
    assert result["v3"]["file_sha256"] == admission.FROZEN_V3_FILE_SHA256
    assert result["v3"]["immutable"] is True
    assert result["v2"]["partition_query_counts"] == {
        "CALIBRATION": 20,
        "HOLDOUT": 10,
    }
    assert result["v2"]["language_query_counts"] == {
        "KOREAN": 18,
        "KOREAN_ENGLISH_MIXED": 6,
        "ENGLISH": 6,
    }
    assert "query" not in result["v2"]
    assert "text" not in result["v2"]
    summary = admission.summary_line(result)
    assert summary.startswith("model_calibration_dataset_admission=pass")
    assert "v2_queries=30 v2_pairs=120" in summary
    assert "v3_scenarios=30 v3_packages=60 v3_candidates=240" in summary


def test_admission_rejects_v1_v2_and_v3_drift(tmp_path: Path) -> None:
    bad_v1 = tmp_path / "v1.json"
    bad_v1.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="v1"):
        admission.admit_calibration_dataset_files(v1_path=bad_v1)

    bad_v2 = tmp_path / "v2.json"
    bad_v2.write_text(json.dumps({"dataset_schema_version": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset"):
        admission.admit_calibration_dataset_files(v2_path=bad_v2)

    changed_v2 = tmp_path / "changed-v2.json"
    payload = json.loads(admission.DEFAULT_V2_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["documents"][0]["text"] += " 변경"
    changed_v2.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="v2"):
        admission.admit_calibration_dataset_files(v2_path=changed_v2)

    bad_v3 = tmp_path / "v3.json"
    bad_v3.write_text(json.dumps({"dataset_schema_version": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="v3"):
        admission.admit_calibration_dataset_files(v3_path=bad_v3)

    changed_v3 = tmp_path / "changed-v3.json"
    payload = json.loads(admission.DEFAULT_V3_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["candidates"][0]["text"] += " changed"
    changed_v3.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="v3"):
        admission.admit_calibration_dataset_files(v3_path=changed_v3)


def test_admission_rejects_semantic_digest_drift(monkeypatch) -> None:
    v2_digest = admission.FROZEN_V2_DATASET_SHA256
    monkeypatch.setattr(admission, "FROZEN_V2_DATASET_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="v2 calibration dataset digest"):
        admission.admit_calibration_dataset_files()

    monkeypatch.setattr(
        admission,
        "FROZEN_V2_DATASET_SHA256",
        v2_digest,
    )
    monkeypatch.setattr(admission, "FROZEN_V3_DATASET_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="v3 calibration dataset digest"):
        admission.admit_calibration_dataset_files()


def test_v3_ready_packages_preserve_reviewed_v2_sources() -> None:
    v2 = json.loads(admission.DEFAULT_V2_PATH.read_text(encoding="utf-8"))
    v3 = json.loads(admission.DEFAULT_V3_PATH.read_text(encoding="utf-8"))
    v2_cases = {case["case_id"]: case for case in v2["cases"]}
    v3_cases = {case["case_id"]: case for case in v3["cases"]}
    v2_queries = {case["query"] for case in v2["cases"]}
    v2_texts = {
        document["text"] for case in v2["cases"] for document in case["documents"]
    }
    role_to_grade = {
        "PRIMARY_ANSWER": "STRONG_POSITIVE",
        "SUPPORTING_ANSWER": "ACCEPTABLE_POSITIVE",
        "HARD_NON_ANSWER": "HARD_NEGATIVE",
        "EASY_NON_ANSWER": "EASY_NEGATIVE",
    }

    assert {case["scenario_id"] for case in v3["cases"]} == set(v2_cases)
    for scenario_id, source_case in v2_cases.items():
        ready = v3_cases[f"{scenario_id}-ready"]
        low = v3_cases[f"{scenario_id}-low-confidence"]
        source_documents = {
            document["relevance_grade"]: document["text"]
            for document in source_case["documents"]
        }
        assert ready["query"] == source_case["query"]
        assert {
            candidate["evidence_role"]: candidate["text"]
            for candidate in ready["candidates"]
        } == {role: source_documents[grade] for role, grade in role_to_grade.items()}
        assert low["query"] != ready["query"]
        assert low["query"] not in v2_queries
        assert all(candidate["text"] not in v2_texts for candidate in low["candidates"])
        assert all(
            candidate["expected_relevant"] is False for candidate in low["candidates"]
        )


def test_cli_success_and_redacted_failure(tmp_path: Path, capsys) -> None:
    assert admission.main(["--summary"]) == 0
    assert "v3_scenarios=30 v3_packages=60" in capsys.readouterr().out

    missing = tmp_path / "missing.json"
    assert admission.main(["--v2", str(missing)]) == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure == {"detail": "FileNotFoundError", "status": "FAIL"}
