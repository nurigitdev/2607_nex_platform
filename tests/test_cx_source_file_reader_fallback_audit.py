from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_cx_source_file_reader_fallback_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret-0281@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_CX_SOURCE_STORAGE_ROOT": "/data/nex-platform/secret-0281/source-files",
    }


def test_source_file_reader_fallback_audit_passes_current_gap() -> None:
    evidence = audit.run_cx_source_file_reader_fallback_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["scope"]["slice"] == "Slice 0281"
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["runtime_probe"]["status"] == "PASS"
    assert evidence["runtime_probe"]["observations"]["fallback_state"] == "implemented"
    assert evidence["runtime_probe"]["observations"]["source_reader"] == (
        "materialized_local_source_file"
    )
    assert evidence["runtime_probe"]["observations"]["extraction_error_code_after_evict"] is None
    assert evidence["runtime_probe"]["checks"]["materialized_source_exists"] is True
    assert evidence["runtime_probe"]["checks"]["fallback_extraction_succeeded"] is True
    assert evidence["runtime_probe"]["checks"]["source_reader_redacted"] is True
    assert audit.summary_line(evidence).startswith(
        "cx_source_file_reader_fallback_audit=pass "
    )


def test_source_file_reader_fallback_audit_does_not_leak_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_cx_source_file_reader_fallback_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0281" not in serialized
    assert "/data/nex-platform" not in serialized
    assert audit.SECRET_SOURCE.decode("utf-8") not in serialized
    assert "nex-cx-source-reader-fallback-" not in serialized


def test_source_file_reader_fallback_audit_reports_missing_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(
        audit,
        "REQUIRED_PATHS",
        (
            audit.RequiredPath(
                "missing",
                missing,
                "Missing path for regression coverage.",
            ),
        ),
    )
    monkeypatch.setattr(
        audit,
        "REQUIRED_SOURCE_TOKENS",
        (
            audit.TokenRequirement(
                "current_memory_reader",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_cx_source_file_reader_fallback_audit(
        {},
        root_dir=tmp_path,
        runtime_probe_runner=lambda: {"status": "PASS", "checks": {}},
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["current_memory_reader_identified"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_source_file_reader_fallback_audit_reports_probe_failures() -> None:
    explicit_failure = audit.run_cx_source_file_reader_fallback_audit(
        {},
        runtime_probe_runner=lambda: {"status": "FAIL", "failure_code": "probe_bad"},
    )
    exception_failure = audit.run_cx_source_file_reader_fallback_audit(
        {},
        runtime_probe_runner=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    invalid_failure = audit.run_cx_source_file_reader_fallback_audit(
        {},
        runtime_probe_runner=lambda: [],
    )

    assert explicit_failure["status"] == "FAIL"
    assert explicit_failure["checks"]["runtime_gap_probe_passed"] is False
    assert explicit_failure["issues"][-1]["subject"] == "probe_bad"
    assert exception_failure["runtime_probe"]["failure_code"] == "RuntimeError"
    assert invalid_failure["runtime_probe"]["failure_code"] == "invalid_probe"


def test_source_file_reader_fallback_gap_probe_records_extraction_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extraction(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise audit.IngestionError(
            status_code=409,
            error_code="cx.source_content_unavailable",
            detail="forced fallback failure",
        )

    monkeypatch.setattr(audit, "run_text_extraction_job", fail_extraction)

    probe = audit.run_gap_probe()

    assert probe["status"] == "FAIL"
    assert probe["observations"]["extraction_error_code_after_evict"] == (
        "cx.source_content_unavailable"
    )
    assert probe["checks"]["fallback_extraction_succeeded"] is False


def test_source_file_reader_fallback_audit_helpers_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_cx_source_file_reader_fallback_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_CX_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            protected_env()["NEX_CX_TEST_DATABASE_URL"],
            protected_env(),
        )
    with pytest.raises(ValueError, match="raw source"):
        audit.assert_evidence_redacted(audit.SECRET_SOURCE.decode("utf-8"), {})
    with pytest.raises(ValueError, match="local path"):
        audit.assert_evidence_redacted("root=/data/nex-platform/cx/source-files", {})
    with pytest.raises(ValueError, match="temp path"):
        audit.assert_evidence_redacted("nex-cx-source-reader-fallback-abcd", {})

    assert audit.relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit.present_count([{"present": True}, {"present": False}]) == 1
    assert audit.present_count_bool({"a": True, "b": False}) == 1
    assert audit.grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"ready": True, "blocked": False}

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "cx_source_file_reader_fallback_audit=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_source_file_reader_fallback_audit_quality_gate_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root / "docs" / "slices" / "0281_cx_source_file_reader_fallback_audit.md"
    )

    assert "run_cx_source_file_reader_fallback_audit.py --summary" in quality_gate
    assert "0281_cx_source_file_reader_fallback_audit.md" in docs_index
    assert slice_doc.exists()
