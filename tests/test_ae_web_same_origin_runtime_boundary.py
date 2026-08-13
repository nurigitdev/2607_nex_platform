from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_same_origin_runtime_boundary as smoke


def test_same_origin_boundary_passes_with_default_disabled_proxy() -> None:
    evidence = smoke.run_ae_web_same_origin_runtime_boundary({})

    assert evidence["status"] == "PASS"
    assert evidence["proxy"]["prefix"] == "/ae-api"
    assert evidence["proxy"]["target_env"] == smoke.PROXY_TARGET_ENV
    assert evidence["proxy"]["target_configured"] is False
    assert evidence["checks"]["proxy_default_disabled"] is True
    assert evidence["checks"]["browser_config_uses_ae_api_base_path"] is True
    assert evidence["checks"]["browser_boundary_config_safe"] is True
    assert smoke.summary_line(evidence) == (
        "ae_web_same_origin_runtime_boundary=pass "
        "proxy=/ae-api files=5/5 browser_config=safe"
    )


def test_same_origin_boundary_allows_configured_proxy_without_leaking_target() -> None:
    env = {
        smoke.PROXY_TARGET_ENV: "http://proxy-user:secret-0268@127.0.0.1:8003"
    }

    evidence = smoke.run_ae_web_same_origin_runtime_boundary(env)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["proxy"]["target_configured"] is True
    assert evidence["proxy"]["target_value"] == "configured"
    assert env[smoke.PROXY_TARGET_ENV] not in serialized
    assert "secret-0268" not in serialized


def test_same_origin_boundary_reports_missing_files_and_tokens(tmp_path: Path) -> None:
    serve_path = tmp_path / "apps" / "nex-ae-web" / "scripts" / "serve.mjs"
    runtime_path = tmp_path / "apps" / "nex-ae-web" / "src" / "runtimeConfig.js"
    session_path = tmp_path / "apps" / "nex-ae-web" / "src" / "sessionClient.js"
    package_path = tmp_path / "apps" / "nex-ae-web" / "package.json"
    for path in (serve_path, runtime_path, session_path, package_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("incomplete", encoding="utf-8")

    evidence = smoke.run_ae_web_same_origin_runtime_boundary({}, root_dir=tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["files_present"] is False
    assert evidence["checks"]["dev_server_exports_proxy"] is False
    assert evidence["checks"]["proxy_default_disabled"] is False
    assert any(issue["category"] == "file_missing" for issue in evidence["issues"])
    assert any(issue["category"] == "token_missing" for issue in evidence["issues"])


def test_same_origin_boundary_redaction_output_and_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "http://127.0.0.1:8003/ae-api-target-0268"
    evidence = smoke.run_ae_web_same_origin_runtime_boundary({})
    output_path = tmp_path / "same-origin.json"

    smoke.write_boundary_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match=smoke.PROXY_TARGET_ENV):
        smoke.assert_same_origin_evidence_redacted(f"leaked {target}", {smoke.PROXY_TARGET_ENV: target})

    monkeypatch.setenv(smoke.PROXY_TARGET_ENV, target)
    with pytest.raises(ValueError, match=smoke.PROXY_TARGET_ENV):
        smoke.write_boundary_evidence(output_path, {"leak": target})

    assert smoke._relative(Path("/tmp/outside-0268.txt")) == Path("outside-0268.txt")
    assert smoke._relative_label(Path("/tmp/outside-0268.txt")) == "outside-0268.txt"
    assert smoke._source_defaults_proxy_disabled('process.env.AE_API_PROXY_TARGET || ""')
    assert not smoke._source_defaults_proxy_disabled("process.env.AE_API_PROXY_TARGET")


def test_same_origin_boundary_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_same_origin_runtime_boundary",
        lambda: {
            "boundary_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "proxy": {"prefix": "/ae-api"},
            "files": [{"present": True}],
        },
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_web_same_origin_runtime_boundary=pass" in capsys.readouterr().out
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_same_origin_runtime_boundary",
        lambda: {"status": "FAIL", "issues": [{"category": "x"}]},
    )
    assert smoke.main(["--summary"]) == 1
    assert "issues=1" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_same_origin_runtime_boundary",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_same_origin_boundary_is_quality_gate_docs_and_runbook_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    runbook = (
        root / "docs" / "runbooks" / "ae_web_credential_login_browser_smoke.md"
    ).read_text(encoding="utf-8")
    serve_script = (root / "apps" / "nex-ae-web" / "scripts" / "serve.mjs").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        root / "docs" / "slices" / "0268_ae_web_same_origin_runtime_boundary.md"
    )

    assert "run_ae_web_same_origin_runtime_boundary.py --summary" in quality_gate
    assert "0268_ae_web_same_origin_runtime_boundary.md" in docs_index
    assert "Slice 0268" in ae_web_readme
    assert "AE_API_PROXY_TARGET" in runbook
    assert "createAeWebServer" in serve_script
    assert "AE_API_PROXY_PREFIX" in serve_script
    assert slice_doc.exists()
