from __future__ import annotations

from pathlib import Path

from nex_ae_api.web_runtime_audit import (
    _load_json_mapping,
    _read_text,
    build_ae_web_runtime_audit,
)
import run_ae_web_runtime_audit as runner


def test_repository_web_runtime_audit_classifies_current_gaps() -> None:
    result = build_ae_web_runtime_audit()

    assert result["status"] == "PASS"
    assert result["web_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"]["source_file_count"] >= 43
    assert result["summary"]["test_file_count"] >= 55
    assert result["summary"]["main_js_line_count"] >= 3_220
    assert result["summary"]["playwright_script_count"] == 7
    assert result["summary"]["playwright_test_count"] == 7
    assert result["summary"]["accessibility_script_count"] == 1
    assert result["summary"]["localization_file_count"] == 0
    assert result["summary"]["hardcoded_korean_line_count"] > 0
    assert result["summary"]["refactor_required_count"] == 4
    assert result["summary"]["good_boundary_count"] == 3
    assert result["package_version"] == "0.0.0-slice0227"


def test_web_runtime_audit_fails_closed_without_inputs(tmp_path: Path) -> None:
    result = build_ae_web_runtime_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ae_web_runtime_audit_failed"
    assert result["summary"]["issue_count"] == 3
    assert result["checks"]["audit_inputs_present"] is False


def test_json_and_text_readers_cover_invalid_and_missing_files(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "package.json"
    payload.write_text('{"version":"1.0.0"}', encoding="utf-8")
    assert _load_json_mapping(payload) == {"version": "1.0.0"}
    assert _read_text(payload) == '{"version":"1.0.0"}'
    payload.write_text("{bad", encoding="utf-8")
    assert _load_json_mapping(payload) == {}
    payload.write_text("[]", encoding="utf-8")
    assert _load_json_mapping(payload) == {}
    assert _load_json_mapping(tmp_path / "missing.json") == {}
    assert _read_text(tmp_path / "missing.txt") == ""


def test_summary_line_and_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_web_runtime_audit()

    summary = passing["summary"]
    assert runner.summary_line(passing) == (
        "ae_web_runtime_audit=pass readiness=GAPS_CONFIRMED "
        f"source={summary['source_file_count']} tests={summary['test_file_count']} "
        f"main_lines={summary['main_js_line_count']} playwright=7/7 "
        "refactors=4 issues=0"
    )
    assert "readiness=UNKNOWN" in runner.summary_line({"status": "FAIL"})
    monkeypatch.setattr(runner, "run_ae_web_runtime_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "refactors=4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_ae_web_runtime_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
