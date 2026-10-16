from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import run_p6_ca02_s7_dual_profile_postgres_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]


def _parity_contract() -> dict[str, Any]:
    return {
        "request_fields": ["compiled_inputs", "schema_version"],
        "request_projection": {
            "schema_version": "1.0",
            "compiled_inputs": {"year": 2026},
        },
        "result_summary_fields": ["execution_status", "schema_version"],
        "result_summary_projection": {
            "schema_version": "1.0",
            "execution_status": "COMPLETED",
        },
        "runtime_result_projection": {
            "schema_version": "1.0",
            "status": "COMPLETED",
            "outputs": [],
        },
        "step_result_fields": ["schema_version", "status"],
        "step_result_projection": {
            "schema_version": "1.2",
            "status": "SUCCEEDED",
        },
        "identity_lineage_preserved": True,
    }


def _profile_evidence(profile: str) -> dict[str, Any]:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "backend_profile": profile,
        "checks": {"e2e": True, "identity": True},
        "row_counts": {"ae_nsl_backend_run": 1, "ae_step_result": 2},
        "cleanup_counts": {"remaining": 0, "s7_remaining": 0},
        "parity_contract": _parity_contract(),
    }


def test_smoke_is_protected_and_rejects_unsafe_inputs() -> None:
    skipped = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke({})
    missing_database = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    rejected = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql+psycopg://other:secret@localhost/other",
        }
    )
    missing_source = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
            ),
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing_database["failure_code"] == "database_url_missing"
    assert rejected["failure_code"] == "target_not_allowed"
    assert missing_source["failure_code"] == "nsl_source_missing"


def test_smoke_executes_both_profiles_and_compares_contracts(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    migration = SimpleNamespace(
        planned=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
        applied=(),
        skipped=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
    )
    calls: list[str] = []
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "wheel_sha256": "sha256:" + "a" * 64,
                "package_version": "0.1.0",
                "source_revision": "1" * 40,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        smoke.p6_ca02_s3,
        "_installed_package_evidence",
        lambda *_args: {
            "wheel_sha256": "sha256:" + "a" * 64,
            "package_version": "0.1.0",
            "public_api_complete": True,
            "runtime_import_is_not_checkout": True,
        },
    )
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)

    def execute_profile(**kwargs: Any) -> dict[str, Any]:
        profile = kwargs["backend_profile"]
        calls.append(profile)
        return _profile_evidence(profile)

    monkeypatch.setattr(smoke.p6_s7, "execute_p6_s7_postgres_profile", execute_profile)
    evidence = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
            ),
            smoke.NSL_SOURCE_ENV: str(source),
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["remote_provider_required"] is False
    assert calls == list(smoke.PROFILES)
    assert all(evidence["checks"].values())
    assert all(evidence["parity"].values())
    assert "checks=10/10" in smoke.summary_line(evidence)


def test_parity_comparison_detects_semantic_drift() -> None:
    profiles = {profile: _profile_evidence(profile) for profile in smoke.PROFILES}
    profiles[smoke.NSL_V01_PROCESS_ISOLATED_BACKEND]["parity_contract"] = {
        **_parity_contract(),
        "runtime_result_projection": {"status": "FAILED"},
        "identity_lineage_preserved": False,
    }

    parity = smoke._compare_profile_contracts(profiles)

    assert parity == {
        "request": True,
        "result_summary": True,
        "runtime_result": False,
        "step_result": True,
        "identity_lineage": False,
    }


def test_profile_pass_requires_exact_profile_and_all_checks() -> None:
    evidence = _profile_evidence(smoke.NSL_V01_IN_PROCESS_BACKEND)
    assert smoke._profile_passed(evidence, smoke.NSL_V01_IN_PROCESS_BACKEND)
    evidence["checks"]["identity"] = False
    assert not smoke._profile_passed(evidence, smoke.NSL_V01_IN_PROCESS_BACKEND)
    evidence["checks"]["identity"] = True
    assert not smoke._profile_passed(evidence, smoke.NSL_V01_PROCESS_ISOLATED_BACKEND)


def test_smoke_contains_and_redacts_execution_failure(monkeypatch, tmp_path) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    database_url = "postgresql+psycopg://nex_ae_user:private@localhost/nex_ae_test"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(
        smoke.p6_ca02_s3,
        "_installed_package_evidence",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(database_url)),
    )

    evidence = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: database_url,
            smoke.NSL_SOURCE_ENV: str(source),
        }
    )

    assert evidence["failure_code"] == "execution_failed"
    assert "private" not in evidence["detail"]


def test_main_writes_executed_evidence(monkeypatch, tmp_path, capsys) -> None:
    report = tmp_path / "evidence.json"
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"parity": True},
        "parity": {"request": True},
        "migration": {"latest_version": smoke.REQUIRED_MIGRATION},
    }
    monkeypatch.setattr(smoke, "DEFAULT_REPORT", report)
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke, "run_p6_ca02_s7_dual_profile_postgres_smoke", lambda: evidence
    )

    assert smoke.main(["--summary"]) == 0
    assert "p6_ca02_s7_dual_profile_postgres=pass" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"


def test_main_does_not_write_skipped_evidence(monkeypatch, tmp_path, capsys) -> None:
    report = tmp_path / "skipped.json"
    evidence = {
        "status": "SKIPPED",
        "actual_postgres": False,
        "skip_reason": "protected",
    }
    monkeypatch.setattr(smoke, "DEFAULT_REPORT", report)
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke, "run_p6_ca02_s7_dual_profile_postgres_smoke", lambda: evidence
    )

    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
    assert not report.exists()


def test_actual_postgres_dual_profile_smoke() -> None:
    evidence = smoke.run_p6_ca02_s7_dual_profile_postgres_smoke()

    if evidence["status"] == "SKIPPED":
        pytest.skip(evidence["skip_reason"])
    assert evidence["status"] == "PASS", evidence
    assert evidence["actual_postgres"] is True
    assert all(evidence["checks"].values())
