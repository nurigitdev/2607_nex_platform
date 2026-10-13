from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_p4_agent_runtime_foundation_closure as closure


def _postgres(_env) -> dict:
    checks = {
        "restart_trace_restored": True,
        "result_idempotent": True,
        "runtime_metadata_private": True,
    }
    return {
        "status": "PASS",
        "actual_postgres": True,
        "database": "nex_ae_test",
        "checks": checks,
        "cleanup_counts": {"remaining": 0},
    }


def _playwright(_env) -> dict:
    return {
        "status": "PASS",
        "runner": {"browser": "chromium"},
        "viewports": [{"status": "PASS"}, {"status": "PASS"}],
        "checks": {"desktop_passed": True, "mobile_passed": True},
        "issues": [],
        "redaction": {
            "prompt_content_included": False,
            "generated_content_included": False,
            "source_content_included": False,
            "credential_material_included": False,
        },
    }


def test_repository_closure_static_and_injected_protected_evidence_pass() -> None:
    result = closure.run_p4_agent_runtime_foundation_closure(
        {closure.SMOKE_ENV: "1", closure.DATABASE_ENV: "protected"},
        postgres_runner=_postgres,
        playwright_runner=_playwright,
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert sum(
        item["matched_count"] for item in result["frozen_integrity"]
    ) == 312
    assert all(not value for value in result["excluded_scope_hits"].values())
    assert result["postgres"]["cleanup_remaining"] == 0
    assert result["playwright"]["viewport_count"] == 2
    assert result["requirement"] == "P4 IA Runtime Foundation"
    assert "canonical Agent Memory and weekly digest" in result["deferred"]


def test_closure_is_protected_and_fails_closed_for_source_evidence() -> None:
    skipped = closure.run_p4_agent_runtime_foundation_closure({})
    assert skipped["status"] == "SKIPPED"
    assert closure.SMOKE_ENV in skipped["skip_reason"]

    failed = closure.run_p4_agent_runtime_foundation_closure(
        {closure.SMOKE_ENV: "1"},
        postgres_runner=lambda _env: {
            "status": "FAIL",
            "actual_postgres": False,
            "checks": {},
            "cleanup_counts": {"remaining": 1},
        },
        playwright_runner=lambda _env: {
            "status": "FAIL",
            "checks": {},
            "redaction": {},
        },
    )
    assert failed["status"] == "FAIL"
    assert "actual_ae_test_postgresql_smoke_passed" in failed["failed_checks"]
    assert "actual_korean_chat_rag_playwright_passed" in failed["failed_checks"]
    assert "playwright_evidence_redacted" in failed["failed_checks"]


def test_hash_manifest_verification_detects_tamper_and_unsafe_path(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "asset.txt"
    asset.write_text("canonical", encoding="utf-8")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = tmp_path / "SHA256SUMS.txt"
    manifest.write_text(f"\n{digest}  asset.txt\n", encoding="utf-8")

    passed = closure._verify_hash_manifest(tmp_path, Path("SHA256SUMS.txt"), 1)
    assert passed["status"] == "PASS"
    assert passed["matched_count"] == 1

    asset.write_text("changed", encoding="utf-8")
    assert closure._verify_hash_manifest(
        tmp_path, Path("SHA256SUMS.txt"), 1
    )["status"] == "FAIL"
    manifest.write_text(f"{digest}  ../outside.txt\nmalformed\n", encoding="utf-8")
    unsafe = closure._verify_hash_manifest(
        tmp_path, Path("SHA256SUMS.txt"), 2
    )
    assert unsafe["status"] == "FAIL"
    assert unsafe["matched_count"] == 0
    assert closure._verify_hash_manifest(
        tmp_path, Path("missing.txt"), 1
    )["entry_count"] == 0


def test_excluded_scope_and_provider_scans_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "runtime.py"
    source.write_text(
        "import httpx\nDEFAULT_PROJECT = 'bad'\nAPIRouter()\n",
        encoding="utf-8",
    )
    sources = closure._read_sources(tmp_path, (Path("runtime.py"), Path("missing.py")))

    assert sources["missing.py"] == ""
    assert closure._token_hits(
        sources, closure.FORBIDDEN_IMPLEMENTATION_TOKENS
    ) == ["runtime.py:DEFAULT_PROJECT"]
    assert closure._token_hits(sources, closure.FORBIDDEN_PROVIDER_IMPORTS) == [
        "runtime.py:import httpx"
    ]
    assert closure._token_hits(sources, ("APIRouter(",)) == [
        "runtime.py:APIRouter("
    ]


def test_projections_summary_and_cli(monkeypatch, tmp_path: Path, capsys) -> None:
    passing = closure.run_p4_agent_runtime_foundation_closure(
        {closure.SMOKE_ENV: "1"},
        postgres_runner=_postgres,
        playwright_runner=_playwright,
    )
    summary = closure.summary_line(passing)
    assert "closure=pass" in summary
    assert "frozen=312/312" in summary
    assert closure.summary_line({"status": "SKIPPED"}).endswith("=skipped")

    monkeypatch.setattr(
        closure,
        "run_p4_agent_runtime_foundation_closure",
        lambda: passing,
    )
    output = tmp_path / "closure.json"
    assert closure.main(["--summary", "--output", str(output)]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_p4_agent_runtime_foundation_closure",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
