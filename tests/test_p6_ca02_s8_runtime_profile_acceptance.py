from __future__ import annotations

import json
from pathlib import Path

import run_p6_ca02_s8_runtime_profile_acceptance as acceptance


def _readiness(_env) -> dict:
    return {
        "status": "PASS",
        "actual_installed_wheel": True,
        "default_backend_profile": acceptance.NSL_V01_IN_PROCESS_BACKEND,
        "checks": {
            "worker_default_is_in_process": True,
            "process_isolated_compatibility_preserved": True,
        },
        "remote_provider_required": False,
    }


def _recovery(_env) -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"cooperative_timeout": True, "lease_recovery": True},
        "cleanup_counts": {"remaining": 0},
        "remote_provider_required": False,
    }


def _parity(_env) -> dict:
    profiles = acceptance.NSL_V01_BACKEND_PROFILES
    return {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {
            "skill_execution_request_parity": True,
            "nsl_result_summary_parity": True,
            "step_result_v1_2_parity": True,
            "identity_lineage_preserved_per_profile": True,
        },
        "parity": {
            "request": True,
            "result_summary": True,
            "runtime_result": True,
            "step_result": True,
            "identity_lineage": True,
        },
        "profile_cleanup_counts": {
            profile: {"remaining": 0, "s7_remaining": 0} for profile in profiles
        },
        "remote_provider_required": False,
    }


def test_acceptance_is_protected() -> None:
    evidence = acceptance.run_p6_ca02_s8_runtime_profile_acceptance({})

    assert evidence["status"] == "SKIPPED"
    assert acceptance.SMOKE_ENV in evidence["skip_reason"]
    assert acceptance.summary_line(evidence).endswith("=skipped")


def test_acceptance_composes_static_and_protected_evidence() -> None:
    evidence = acceptance.run_p6_ca02_s8_runtime_profile_acceptance(
        {acceptance.SMOKE_ENV: "1"},
        readiness_runner=_readiness,
        recovery_runner=_recovery,
        parity_runner=_parity,
    )

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["failed_checks"] == []
    assert evidence["p7_entry_profile"] == "NSL_V01_IN_PROCESS"
    assert evidence["optional_compatibility_profile"] == (
        "NSL_V01_PROCESS_ISOLATED"
    )
    assert evidence["remote_provider_required"] is False
    assert "checks=12/12" in acceptance.summary_line(evidence)


def test_acceptance_fails_closed_for_each_evidence_boundary() -> None:
    failed_readiness = {**_readiness({}), "status": "FAIL"}
    failed_recovery = {**_recovery({}), "cleanup_counts": {"remaining": 1}}
    failed_parity = {**_parity({}), "parity": {"request": False}}

    evidence = acceptance.run_p6_ca02_s8_runtime_profile_acceptance(
        {acceptance.SMOKE_ENV: "1"},
        readiness_runner=lambda _env: failed_readiness,
        recovery_runner=lambda _env: failed_recovery,
        parity_runner=lambda _env: failed_parity,
    )

    assert evidence["status"] == "FAIL"
    assert "installed_wheel_and_worker_readiness_passed" in evidence["failed_checks"]
    assert "timeout_crash_and_lease_recovery_passed" in evidence["failed_checks"]
    assert "stable_contract_and_lineage_parity_passed" in evidence["failed_checks"]


def test_private_nsl_import_scan_is_ast_based_and_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "allowed.py").write_text(
        "from nsl.api import SkillExecutionJob\n"
        "from nsl.process_isolation import ProcessIsolatedRuntime\n",
        encoding="utf-8",
    )
    (tmp_path / "private.py").write_text(
        "from nsl.compiler import NslCompiler\n", encoding="utf-8"
    )
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    hits = acceptance._disallowed_nsl_imports(tmp_path)

    assert any(hit.endswith(":nsl.compiler") for hit in hits)
    assert any("unreadable:SyntaxError" in hit for hit in hits)
    assert not any("nsl.api" in hit for hit in hits)
    assert not any("nsl.process_isolation" in hit for hit in hits)


def test_missing_documents_and_projection_are_explicit(tmp_path: Path) -> None:
    static = acceptance._static_evidence(tmp_path)
    projection = acceptance._projection(
        {"status": "PASS", "actual_postgres": True, "checks": {"one": True}},
        cleanup={"remaining": 0},
        parity={"request": True},
    )

    assert static["checks"]["s1_through_s7_evidence_present"] is False
    assert len(static["missing_documents"]) == 7
    assert projection == {
        "status": "PASS",
        "actual_postgres": True,
        "check_count": 1,
        "passed_check_count": 1,
        "cleanup": {"remaining": 0},
        "parity": {"request": True},
    }


def test_main_writes_only_executed_acceptance(monkeypatch, tmp_path, capsys) -> None:
    report = tmp_path / "acceptance.json"
    passed = {
        "status": "PASS",
        "checks": {"accepted": True},
        "parity": {"actual_postgres": True},
        "p7_entry_profile": "NSL_V01_IN_PROCESS",
    }
    monkeypatch.setattr(acceptance, "DEFAULT_REPORT", report)
    monkeypatch.setattr(
        acceptance, "run_p6_ca02_s8_runtime_profile_acceptance", lambda: passed
    )
    monkeypatch.setattr(acceptance, "load_env_file", lambda _path: None)

    assert acceptance.main(["--summary"]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "runtime_profile_acceptance=pass" in capsys.readouterr().out

    report.unlink()
    monkeypatch.setattr(
        acceptance,
        "run_p6_ca02_s8_runtime_profile_acceptance",
        lambda: {"status": "SKIPPED"},
    )
    assert acceptance.main([]) == 0
    assert not report.exists()

    monkeypatch.setattr(
        acceptance,
        "run_p6_ca02_s8_runtime_profile_acceptance",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert acceptance.main([]) == 1
