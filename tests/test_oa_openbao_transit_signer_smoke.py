from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import run_oa_openbao_transit_signer as runner


ROOT = Path(__file__).resolve().parents[1]


def test_transit_signer_smoke_passes() -> None:
    result = runner.run_oa_openbao_transit_signer()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "check_count": 10,
        "request_count": 3,
        "key_version": 1,
        "signature_bytes": 384,
    }
    assert result["decision"]["private_key_exported"] is False
    assert result["decision"]["next_slice"] == "1435"


def test_transit_signer_smoke_is_standalone_executable() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/smoke/run_oa_openbao_transit_signer.py"),
            "--summary",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout
    assert "oa_openbao_transit_signer=pass" in completed.stdout


def test_transit_signer_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_oa_openbao_transit_signer()
    assert runner.summary_line(passing) == (
        "oa_openbao_transit_signer=pass checks=10/10 requests=3 version=1 "
        "signature_bytes=384 next=1435"
    )
    assert runner.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "oa_openbao_transit_signer=fail issues=1"
    )

    monkeypatch.setattr(runner, "run_oa_openbao_transit_signer", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "signer=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_openbao_transit_signer",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert runner.main([]) == 1
