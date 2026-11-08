from __future__ import annotations

import json
from pathlib import Path

import check_retrieval_calibration_v4_design as checker
from nex_runtime.semantic_hashes import sha256_text


def test_frozen_design_checker_and_summary() -> None:
    result = checker.check_retrieval_calibration_v4_design()

    assert result["status"] == "PASS"
    assert result["scenario_count"] == 100
    assert result["calibration_scenario_count"] == 80
    assert result["holdout_scenario_count"] == 20
    assert result["immutable"] is True
    assert "profiles=4" in checker.summary_line(result)
    assert checker.FROZEN_DESIGN_HASH in checker.summary_line(result)


def test_checker_rejects_file_and_semantic_digest_drift(
    monkeypatch, tmp_path: Path
) -> None:
    text = checker.DEFAULT_DESIGN_PATH.read_text(encoding="utf-8")
    changed = tmp_path / "changed.json"
    changed.write_text(text.replace("FROZEN_NOT_AUTHORED", "DRAFT", 1), encoding="utf-8")

    try:
        checker.check_retrieval_calibration_v4_design(changed)
    except ValueError as exc:
        assert "file digest" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("file digest drift must fail")

    exact = tmp_path / "exact.json"
    exact.write_text(text, encoding="utf-8")
    monkeypatch.setattr(checker, "FROZEN_FILE_SHA256", sha256_text(text))
    monkeypatch.setattr(checker, "FROZEN_DESIGN_HASH", "sha256:" + "0" * 64)
    try:
        checker.check_retrieval_calibration_v4_design(exact)
    except ValueError as exc:
        assert "semantic digest" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("semantic digest drift must fail")


def test_main_success_and_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    assert checker.main(["--summary"]) == 0
    assert "retrieval_calibration_v4_design=pass" in capsys.readouterr().out

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(checker, "FROZEN_FILE_SHA256", sha256_text("[]"))
    assert checker.main(["--design", str(malformed)]) == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "detail": "RetrievalCalibrationDesignError",
        "status": "FAIL",
    }
