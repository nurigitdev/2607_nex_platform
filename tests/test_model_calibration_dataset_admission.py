from __future__ import annotations

import json
from pathlib import Path

import pytest

import check_model_calibration_dataset as admission


def test_canonical_v2_dataset_is_admitted_and_v1_is_immutable() -> None:
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
    assert admission.summary_line(result).startswith(
        "model_calibration_dataset_admission=pass"
    )


def test_admission_rejects_v1_drift_and_invalid_v2(tmp_path: Path) -> None:
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


def test_cli_success_and_redacted_failure(tmp_path: Path, capsys) -> None:
    assert admission.main(["--summary"]) == 0
    assert "queries=30 pairs=120" in capsys.readouterr().out

    missing = tmp_path / "missing.json"
    assert admission.main(["--v2", str(missing)]) == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure == {"detail": "FileNotFoundError", "status": "FAIL"}
