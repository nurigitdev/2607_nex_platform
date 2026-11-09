from __future__ import annotations

import json
from pathlib import Path

import run_platform_deployment_build_inputs as smoke
from nex_runtime.deployment_locks import (
    NODE_LOCK_PATH,
    PYTHON_LOCK_PATH,
    python_lock_package_versions,
)


ROOT = Path(__file__).resolve().parents[1]


def _expected_node_package_count() -> int:
    payload = json.loads((ROOT / NODE_LOCK_PATH).read_text(encoding="utf-8"))
    return sum(
        1
        for path, package in payload["packages"].items()
        if path and isinstance(package, dict)
    )


def test_repository_build_input_evidence_is_complete() -> None:
    result = smoke.run_platform_deployment_build_inputs()

    assert result["status"] == "PASS"
    assert result["summary"]["lock_count"] == 2
    expected_python_packages = len(
        python_lock_package_versions(ROOT / PYTHON_LOCK_PATH)
    )
    assert result["summary"]["python_package_count"] == expected_python_packages
    assert result["summary"]["python_hash_count"] > 1000
    expected_node_packages = _expected_node_package_count()
    assert result["summary"]["node_package_count"] == expected_node_packages
    assert result["summary"]["node_integrity_count"] == expected_node_packages
    assert result["decision"] == {
        "range_only_install_allowed": False,
        "python_require_hashes_required": True,
        "node_npm_ci_required": True,
        "production_connection_required": False,
        "next_slice": "1415",
    }


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_deployment_build_inputs()
    expected_python_packages = len(
        python_lock_package_versions(ROOT / PYTHON_LOCK_PATH)
    )
    assert smoke.summary_line(passing).startswith(
        "platform_deployment_build_inputs=pass locks=2 "
        f"python_packages={expected_python_packages}"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_deployment_build_inputs=fail"
    )

    monkeypatch.setattr(smoke, "run_platform_deployment_build_inputs", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "build_inputs=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_deployment_build_inputs",
        lambda: (_ for _ in ()).throw(ValueError("bad lock")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
