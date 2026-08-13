from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_post_login_document_workflow_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0271@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret-0271@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret-0271@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD": "browser-secret-0271",
    }


def test_post_login_document_workflow_audit_passes_on_current_repo() -> None:
    evidence = audit.run_ae_web_post_login_document_workflow_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["decisions"]["upload_payload_scope"] == "metadata_handoff_only"
    assert evidence["decisions"]["browser_api_path"] == "/ae-api"
    assert evidence["decisions"]["protected_smoke_databases"] == [
        "nex_ae_test",
        "nex_oa_test",
        "nex_cx_test",
    ]
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["html_anchors"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_gaps"])
    assert audit.summary_line(evidence).startswith(
        "ae_web_post_login_document_workflow_audit=pass "
    )


def test_post_login_document_workflow_audit_does_not_leak_protected_env() -> None:
    env = protected_env()

    evidence = audit.run_ae_web_post_login_document_workflow_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0271" not in serialized
    assert "browser-secret-0271" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert env["NEX_CX_TEST_DATABASE_URL"] not in serialized
    assert env["NEX_OA_TEST_DATABASE_URL"] not in serialized


def test_post_login_document_workflow_audit_reports_missing_static_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.js"
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
    monkeypatch.setattr(audit, "REQUIRED_HTML_ANCHORS", ("missing-anchor",))
    monkeypatch.setattr(
        audit,
        "REQUIRED_SOURCE_TOKENS",
        (
            audit.TokenRequirement(
                "missing",
                missing,
                "missing-token",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_web_post_login_document_workflow_audit({}, root_dir=tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["post_login_html_anchors_present"] is False
    assert evidence["checks"]["source_boundaries_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "html_anchor_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_post_login_document_workflow_audit_redaction_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_web_post_login_document_workflow_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            "postgresql+psycopg://nex_ae_user:secret-0271@127.0.0.1:5432/nex_ae_test",
            protected_env(),
        )

    assert audit.relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit.present_count([{"present": True}, {"present": False}]) == 1

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_web_post_login_document_workflow_audit=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_post_login_document_workflow_audit_quality_gate_docs_and_readme_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0271_ae_web_post_login_document_workflow_audit.md"
    )

    assert "run_ae_web_post_login_document_workflow_audit.py --summary" in quality_gate
    assert "0271_ae_web_post_login_document_workflow_audit.md" in docs_index
    assert "Slice 0271" in ae_web_readme
    assert slice_doc.exists()
