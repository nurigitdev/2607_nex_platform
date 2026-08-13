from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import run_ae_web_playwright_readiness as smoke


def test_playwright_readiness_passes_static_default() -> None:
    evidence = smoke.run_ae_web_playwright_readiness({})

    assert evidence["status"] == "PASS"
    assert evidence["mode"] == "static"
    assert evidence["playwright"]["package"] == "@playwright/test"
    assert evidence["same_origin_boundary"]["status"] == "PASS"
    assert evidence["node_execution"]["status"] == "SKIPPED"
    assert evidence["checks"]["package_playwright_declared"] is True
    assert evidence["checks"]["quality_gate_wired"] is True
    assert smoke.summary_line(evidence) == (
        "ae_web_playwright_readiness=pass "
        "dependency=@playwright/test mode=static launch=deferred"
    )


def test_playwright_readiness_can_require_installed_node_execution() -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["npm"],
            0,
            stdout=json.dumps(
                {
                    "readiness_schema_version": smoke.NODE_SCHEMA_VERSION,
                    "status": "PASS",
                    "runner": {"mode": "dependency_readiness"},
                    "checks": {"launch_check_requested": False},
                }
            ),
            stderr="",
        )

    evidence = smoke.run_ae_web_playwright_readiness(
        {},
        require_installed=True,
        runner=runner,
    )

    assert evidence["status"] == "PASS"
    assert evidence["mode"] == "installed"
    assert evidence["node_execution"] == {
        "status": "PASS",
        "reason": None,
        "node_schema_version": smoke.NODE_SCHEMA_VERSION,
        "mode": "dependency_readiness",
        "launch_check_requested": False,
    }


def test_playwright_readiness_reports_node_execution_failures() -> None:
    def timeout_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["npm"], timeout=1)

    def os_error_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("node unavailable")

    def returncode_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["npm"], 1, stdout="", stderr="failed")

    def invalid_json_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["npm"], 0, stdout="not-json", stderr="")

    def payload_fail_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["npm"],
            0,
            stdout=json.dumps(
                {
                    "readiness_schema_version": smoke.NODE_SCHEMA_VERSION,
                    "status": "FAIL",
                    "runner": {"mode": "dependency_readiness"},
                    "checks": {"launch_check_requested": False},
                }
            ),
            stderr="",
        )

    assert smoke.run_node_readiness(runner=timeout_runner)["reason"] == "node_timeout"
    assert smoke.run_node_readiness(runner=os_error_runner)["reason"] == "node_unavailable"
    assert smoke.run_node_readiness(runner=returncode_runner)["reason"] == "node_failed"
    assert smoke.run_node_readiness(runner=invalid_json_runner)["reason"] == "node_json_invalid"

    evidence = smoke.run_ae_web_playwright_readiness(
        {},
        require_installed=True,
        runner=payload_fail_runner,
    )
    assert evidence["status"] == "FAIL"
    assert evidence["node_execution"]["reason"] == "node_payload_failed"
    assert any(issue["category"] == "node_readiness_failed" for issue in evidence["issues"])


def test_playwright_readiness_reports_missing_files_tokens_and_package(
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "apps" / "nex-ae-web" / "package.json"
    lock_path = tmp_path / "apps" / "nex-ae-web" / "package-lock.json"
    node_script = (
        tmp_path / "apps" / "nex-ae-web" / "scripts" / "runCredentialLoginPlaywrightReadiness.mjs"
    )
    quality_gate = tmp_path / "scripts" / "quality" / "run_quality_gate.sh"
    runbook = tmp_path / "docs" / "runbooks" / "ae_web_credential_login_browser_smoke.md"
    for path in (package_path, lock_path, node_script, quality_gate, runbook):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    evidence = smoke.run_ae_web_playwright_readiness({}, root_dir=tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["same_origin_boundary_pass"] is False
    assert evidence["checks"]["package_playwright_declared"] is False
    assert any(issue["category"] == "file_missing" for issue in evidence["issues"])
    assert any(issue["category"] == "token_missing" for issue in evidence["issues"])
    assert any(issue["category"] == "package_missing" for issue in evidence["issues"])


def test_playwright_readiness_redaction_output_and_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "http://127.0.0.1:8003/proxy-target-0269"
    evidence = smoke.run_ae_web_playwright_readiness({})
    output_path = tmp_path / "playwright-readiness.json"

    smoke.write_readiness_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match=smoke.PROXY_TARGET_ENV):
        smoke.assert_playwright_readiness_evidence_redacted(
            f"leaked {target}",
            {smoke.PROXY_TARGET_ENV: target},
        )

    monkeypatch.setenv(smoke.PROXY_TARGET_ENV, target)
    with pytest.raises(ValueError, match=smoke.PROXY_TARGET_ENV):
        smoke.write_readiness_evidence(output_path, {"leak": target})

    assert smoke._load_json(tmp_path / "missing.json") == {}
    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")
    assert smoke._load_json(list_path) == {}
    assert smoke._relative(Path("/tmp/outside-0269.txt")) == Path("outside-0269.txt")
    assert smoke._relative_label(Path("/tmp/outside-0269.txt")) == "outside-0269.txt"


def test_playwright_readiness_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_playwright_readiness",
        lambda require_installed=False: {
            "readiness_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "installed" if require_installed else "static",
            "playwright": {
                "package": smoke.PLAYWRIGHT_PACKAGE,
                "launch_check_default": "deferred",
            },
        },
    )

    assert smoke.main(["--summary", "--require-installed", "--output", str(output_path)]) == 0
    assert "ae_web_playwright_readiness=pass" in capsys.readouterr().out
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_playwright_readiness",
        lambda require_installed=False: {"status": "FAIL", "issues": [{"category": "x"}]},
    )
    assert smoke.main(["--summary"]) == 1
    assert "issues=1" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_playwright_readiness",
        lambda require_installed=False: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_playwright_readiness",
        lambda require_installed=False: (_ for _ in ()).throw(json.JSONDecodeError("bad", "", 0)),
    )
    assert smoke.main([]) == 1
    assert "error=JSONDecodeError" in capsys.readouterr().out


def test_playwright_readiness_is_quality_gate_docs_and_package_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    package = json.loads((root / "apps" / "nex-ae-web" / "package.json").read_text(
        encoding="utf-8"
    ))
    slice_doc = (
        root / "docs" / "slices" / "0269_ae_web_playwright_readiness_foundation.md"
    )

    assert "run_ae_web_playwright_readiness.py --summary" in quality_gate
    assert "0269_ae_web_playwright_readiness_foundation.md" in docs_index
    assert "Slice 0269" in ae_web_readme
    assert package["devDependencies"][smoke.PLAYWRIGHT_PACKAGE]
    assert package["scripts"][smoke.NODE_SMOKE_SCRIPT_NAME]
    assert slice_doc.exists()
