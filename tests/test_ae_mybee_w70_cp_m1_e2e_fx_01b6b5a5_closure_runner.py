from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_mybee_w70_cp_m1_01b6b5a5_closure.py"
SPEC = importlib.util.spec_from_file_location("m1_01b6b5a5_closure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
        ),
        "NEX_WC_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_wc_user:secret@127.0.0.1/nex_wc_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1/nex_oa_test"
        ),
        "NEX_EOS_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_eos_user:secret@127.0.0.1/nex_eos_test"
        ),
    }


def test_5a5_runner_guards_exact_database_identities(tmp_path: Path) -> None:
    missing = _environment()
    missing.pop("NEX_OA_TEST_DATABASE_URL")
    with pytest.raises(
        runner.ProductProtectedGateError, match="NEX_OA_TEST_DATABASE_URL"
    ):
        runner.run_gate(report_path=tmp_path / "missing.json", environ=missing)

    wrong = _environment()
    wrong["NEX_AE_TEST_DATABASE_URL"] = wrong[
        "NEX_AE_TEST_DATABASE_URL"
    ].replace("nex_ae_user", "postgres")
    with pytest.raises(
        runner.ProductProtectedGateError, match="nex_ae_user@nex_ae_test"
    ):
        runner.run_gate(report_path=tmp_path / "wrong.json", environ=wrong)


def test_5a5_runner_records_activation_recovery_and_resume_decision(
    tmp_path: Path,
) -> None:
    observed = {}

    def command_runner(command, *, cwd, env, check):
        observed.update(command=command, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(command, 0)

    report_path = tmp_path / "gate.json"
    report = runner.run_gate(
        report_path=report_path,
        environ=_environment(),
        command_runner=command_runner,
        python_executable="/test/python",
    )

    assert observed["command"] == [
        "/test/python",
        "-m",
        "pytest",
        "-q",
        *runner.PROTECTED_TESTS,
    ]
    assert observed["cwd"] == ROOT
    assert observed["check"] is False
    assert all(observed["env"][name] == "1" for name in runner.PROTECTED_FLAGS)
    assert report["status"] == "PASS"
    assert report["actual_postgresql"] is True
    assert report["installed_activation"]["state"] == "ACTIVE"
    assert report["installed_activation"]["rollback_state"] == "CONTRACT_ONLY"
    assert report["public_product_boundary"]["provider_plan_authoritative"] is False
    assert report["runtime_recovery"]["reactivation_resumes_durable_authority"]
    assert report["provider_assisted_live_status"] == "DEFERRED_TO_01B7"
    assert report["resume_decision"] == "ADMIT_01B7"
    assert all(report["source_checks"].values())
    serialized = report_path.read_text(encoding="utf-8")
    assert "secret" not in serialized
    assert json.loads(serialized) == report


def test_5a5_runner_fails_closed_on_matrix_or_source_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(runner.ProductProtectedGateError, match="exit code 9"):
        runner.run_gate(
            report_path=tmp_path / "matrix.json",
            environ=_environment(),
            command_runner=lambda command, **_values: subprocess.CompletedProcess(
                command, 9
            ),
        )

    monkeypatch.setattr(
        runner,
        "_source_residue_checks",
        lambda _root: {
            "all_active_sources_present": True,
            "no_fixed_business_values": False,
        },
    )
    with pytest.raises(runner.ProductProtectedGateError, match="business_values"):
        runner.run_gate(
            report_path=tmp_path / "source.json",
            environ=_environment(),
            command_runner=lambda command, **_values: subprocess.CompletedProcess(
                command, 0
            ),
        )


def test_source_residue_guard_rejects_missing_or_embedded_business_values(
    tmp_path: Path,
) -> None:
    assert runner._source_residue_checks(tmp_path) == {
        "all_active_sources_present": False
    }

    for relative in runner.ACTIVE_PRODUCT_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "generic\n"
        if relative.endswith("canonical-platform.override.yaml"):
            content = (
                "nex_ae_api.agent_runtime_process\n"
                "NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH\n"
                "NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH\n"
            )
        path.write_text(content, encoding="utf-8")
    assert all(runner._source_residue_checks(tmp_path).values())

    target = tmp_path / runner.ACTIVE_PRODUCT_PATHS[0]
    target.write_text('tenant = "VO00"\n', encoding="utf-8")
    assert runner._source_residue_checks(tmp_path)["no_fixed_business_values"] is False
