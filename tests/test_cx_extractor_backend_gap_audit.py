from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_cx_extractor_backend_gap_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret-0284@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_CX_SOURCE_STORAGE_ROOT": "/data/nex-platform/secret-0284/source-files",
    }


def test_extractor_backend_gap_audit_passes_current_repo() -> None:
    evidence = audit.run_cx_extractor_backend_gap_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["scope"]["slice"] == "Slice 0286"
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["gap_summary"]["implemented_real_extraction_count"] == 4
    assert evidence["gap_summary"]["gap_placeholder_count"] == 2
    assert evidence["gap_summary"]["gap_source_formats"] == [
        "pptx",
        "xlsx",
    ]
    assert evidence["runtime_probe"]["status"] == "PASS"
    assert evidence["runtime_probe"]["checks"]["pdf_real_extraction"]
    assert evidence["runtime_probe"]["checks"]["docx_real_extraction"]
    assert evidence["runtime_probe"]["checks"]["remaining_binary_gaps_are_placeholders"]
    assert evidence["runtime_probe"]["checks"]["binary_raw_source_not_serialized"]
    assert evidence["checks"]["binary_gaps_explicit"] is True
    assert evidence["checks"]["pdf_extraction_backend_ready"] is True
    assert evidence["checks"]["docx_extraction_backend_ready"] is True
    assert audit.summary_line(evidence).startswith(
        "cx_extractor_backend_gap_audit=pass "
    )
    assert "implemented=4 gaps=2 next=Slice 0287" in audit.summary_line(evidence)


def test_extractor_backend_gap_audit_does_not_leak_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_cx_extractor_backend_gap_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0284" not in serialized
    assert "/data/nex-platform" not in serialized
    assert audit.SECRET_SOURCE.decode("utf-8") not in serialized


def test_extractor_backend_gap_audit_reports_missing_boundaries(
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
                "extractor_catalog",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_cx_extractor_backend_gap_audit(
        {},
        root_dir=tmp_path,
        runtime_probe_runner=lambda: {"status": "PASS", "checks": {}},
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["extractor_catalog_ready"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_extractor_backend_gap_audit_reports_probe_failures() -> None:
    explicit_failure = audit.run_cx_extractor_backend_gap_audit(
        {},
        runtime_probe_runner=lambda: {"status": "FAIL", "failure_code": "probe_bad"},
    )
    exception_failure = audit.run_cx_extractor_backend_gap_audit(
        {},
        runtime_probe_runner=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    invalid_failure = audit.run_cx_extractor_backend_gap_audit(
        {},
        runtime_probe_runner=lambda: [],
    )

    assert explicit_failure["status"] == "FAIL"
    assert explicit_failure["checks"]["runtime_probe_passed"] is False
    assert explicit_failure["issues"][-1]["subject"] == "probe_bad"
    assert exception_failure["runtime_probe"]["failure_code"] == "RuntimeError"
    assert invalid_failure["runtime_probe"]["failure_code"] == "invalid_probe"


def test_extractor_backend_gap_probe_detects_placeholder_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_extractor = audit.LocalMockTextExtractor

    class LeakyExtractor:
        def extract_markdown(self, source: audit.ExtractorInput) -> audit.Any:
            if source.filename.endswith(".bin"):
                raise audit.ExtractionAdapterError(
                    status_code=415,
                    error_code="cx.extractor_source_type_unsupported",
                    detail="unsupported",
                )
            return original_extractor().extract_markdown(source)

    class WrongBinaryExtractor(LeakyExtractor):
        def extract_markdown(self, source: audit.ExtractorInput) -> audit.Any:
            output = super().extract_markdown(source)
            if source.filename.endswith(".docx"):
                return type(output)(
                    markdown_text=output.markdown_text,
                    provider=output.provider,
                    mode="wrong_mode",
                    version=output.version,
                    source_format=output.source_format,
                    warnings=output.warnings,
                )
            return output

    monkeypatch.setattr(audit, "LocalMockTextExtractor", WrongBinaryExtractor)

    probe = audit.run_extractor_backend_probe()

    assert probe["status"] == "FAIL"
    assert probe["checks"]["pdf_real_extraction"] is True
    assert probe["checks"]["docx_real_extraction"] is False
    assert probe["checks"]["remaining_binary_gaps_are_placeholders"] is True


def test_extractor_backend_gap_audit_helpers_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_cx_extractor_backend_gap_audit({})

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
    assert audit.content_type_for_probe("pdf") == "application/pdf"
    assert audit.content_type_for_probe("unknown") == "application/octet-stream"
    assert audit.next_slice_from_gap_summary({"next_slices": ["Slice 0287"]}) == (
        "Slice 0287"
    )
    assert audit.source_bytes_for_probe("docx") != audit.SECRET_SOURCE
    assert audit.source_bytes_for_probe("pptx") == audit.SECRET_SOURCE
    assert audit.next_slice_from_gap_summary({"next_slices": []}) is None
    assert audit.next_slice_from_gap_summary({"next_slices": "Slice 0286"}) is None

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "cx_extractor_backend_gap_audit=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_extractor_backend_gap_audit_quality_gate_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = root / "docs" / "slices" / "0284_cx_extractor_backend_gap_audit.md"
    slice_0285_doc = (
        root / "docs" / "slices" / "0285_cx_pdf_extraction_adapter_foundation.md"
    )
    slice_0286_doc = (
        root / "docs" / "slices" / "0286_cx_docx_extraction_adapter_foundation.md"
    )

    assert "run_cx_extractor_backend_gap_audit.py --summary" in quality_gate
    assert "0284_cx_extractor_backend_gap_audit.md" in docs_index
    assert "0285_cx_pdf_extraction_adapter_foundation.md" in docs_index
    assert "0286_cx_docx_extraction_adapter_foundation.md" in docs_index
    assert slice_doc.exists()
    assert slice_0285_doc.exists()
    assert slice_0286_doc.exists()
