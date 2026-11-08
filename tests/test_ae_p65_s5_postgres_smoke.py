from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_p65_s5_postgres_smoke.py"
SPEC = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


SAFE_URL = "postgresql://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"


def test_protected_smoke_is_skipped_by_default_and_guards_target() -> None:
    skipped = smoke.run_p65_s5_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_p65_s5_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert missing["failure_code"] == "database_url_missing"

    wrong = smoke.run_p65_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/other",
        }
    )
    assert wrong["failure_code"] == "target_not_allowed"
    assert "secret" not in str(wrong)


def test_protected_smoke_composes_migration_and_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("2205_ae_nsl_dual_profile", smoke.REQUIRED_MIGRATION),
            applied=(smoke.REQUIRED_MIGRATION,),
            skipped=("2205_ae_nsl_dual_profile",),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_postgres_smoke",
        lambda _url: {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"database_zero_residue": True},
            "row_counts": {"ae_semantic_candidate": 3},
            "cleanup_counts": {"remaining": 0},
            "database": smoke.EXPECTED_DATABASE,
            "role": smoke.EXPECTED_ROLE,
            "execution_state": "EXECUTED",
        },
    )
    evidence = smoke.run_p65_s5_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: SAFE_URL}
    )
    assert evidence["status"] == "PASS"
    assert evidence["checks"]["migration_current"] is True
    assert evidence["redacted_database_url"].find("secret") == -1
    assert "checks=2/2" in smoke.summary_line(evidence)


def test_evidence_output_is_tmp_scoped() -> None:
    evidence = {"status": "PASS"}
    output = Path("/tmp/p65-s5-test-evidence.json")
    smoke.write_evidence(output, evidence)
    assert output.read_text(encoding="utf-8").endswith("\n")
    output.unlink()

    with pytest.raises(ValueError):
        smoke.write_evidence(ROOT / "reports" / "outside.json", evidence)
