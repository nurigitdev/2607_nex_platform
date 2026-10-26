from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import run_p8_demo_s10_installed_domain_acceptance as acceptance

ROOT = Path(__file__).resolve().parents[1]


def _urls() -> dict[str, str]:
    return {
        "nex-oa": "postgresql+psycopg://nex_oa_user:secret@127.0.0.1:5432/nex_oa_dev",
        "nex-ag": "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_dev",
        "nex-ae-api": "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_dev",
        "nex-cx": "postgresql+psycopg://nex_cx_user:secret@127.0.0.1:5432/nex_cx_dev",
        "nex-mo": "postgresql+psycopg://nex_mo_user:secret@127.0.0.1:5432/nex_mo_dev",
        "nex-wc": "postgresql+psycopg://nex_wc_user:secret@127.0.0.1:5432/nex_wc_dev",
        "nex-eos": "postgresql+psycopg://nex_eos_user:secret@127.0.0.1:5432/nex_eos_dev",
    }


def test_s10_source_admission_is_non_executing_and_business_neutral() -> None:
    result = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {}, execute=False, root=ROOT
    )

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["executed"] is False
    assert result["domain_activation"]["process_count"] == 3
    assert result["new_business_behavior_added"] is False


def test_s10_source_admission_runs_in_a_standalone_python_process(
    tmp_path: Path,
) -> None:
    report = tmp_path / "standalone.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/deployment/run_p8_demo_s10_installed_domain_acceptance.py"),
            "--summary",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "p8_demo_s10_installed_domain=source_admitted" in completed.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["source_admitted"] is True


def test_s10_execution_requires_both_switches_and_contains_failures() -> None:
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_openbao": True,
            "domain_acceptance": {"process_count": 3, "signed_service_count": 4},
        }

    skipped = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {}, execute=True, root=ROOT, protected_runner=runner
    )
    passed = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=runner,
    )
    failed = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("bounded failure")
        ),
    )

    assert skipped["status"] == "SOURCE_ADMITTED"
    assert passed["status"] == "PASS"
    assert passed["executed"] is True
    assert len(calls) == 1
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["bounded failure"]
    assert failed["secret_included"] is False
    assert "consumers=3 signed=4" in acceptance.summary_line(passed)


def test_secret_material_covers_base_bindings_without_exposing_urls() -> None:
    values = acceptance._secret_values(
        {},
        urls=_urls(),
        object_credentials={
            "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access",
            "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-secret",
            "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access",
            "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-secret",
        },
    )

    assert values["NEX_AE_DATABASE_URL"].startswith(
        "postgresql+psycopg://nex_ae_user:secret@host.docker.internal"
    )
    assert len(values) == len(acceptance.DEMO_SECRET_BINDINGS)
    assert values["NEX_MO_VLLM_API_KEY"].startswith("unused-")
    with pytest.raises(acceptance.P8DemoS10AcceptanceError, match="PostgreSQL"):
        acceptance._container_database_url("sqlite:///local.db")


def test_evidence_redaction_and_atomic_report(tmp_path: Path) -> None:
    with pytest.raises(acceptance.P8DemoS10AcceptanceError, match="protected"):
        acceptance._assert_redacted(
            {"status": "PASS", "detail": "private-value"}, {"private-value"}
        )

    report = tmp_path / "s10.json"
    acceptance._write_report(report, {"status": "PASS", "secret_included": False})
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"
