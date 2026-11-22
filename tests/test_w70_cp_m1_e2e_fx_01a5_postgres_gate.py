from __future__ import annotations

from pathlib import Path

import run_w70_cp_m1_e2e_fx_01a5_postgres_gate as gate


def test_postgres_gate_is_protected_by_explicit_enable() -> None:
    result = gate.run_gate({})
    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_postgres_gate_rejects_non_test_database() -> None:
    result = gate.run_gate(
        {
            gate.ENABLE_ENV: "1",
            gate.DATABASE_ENV: "postgresql://nex_ae_user:secret@localhost/nex_ae_dev",
        }
    )
    assert result["status"] == "FAIL"
    assert result["actual_postgres"] is False


def test_postgres_gate_source_uses_signed_release_and_zero_residue() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "build_mybee_m1_verified_skill_catalog" in source
    assert "M1InstalledSkillRuntime" in source
    assert source.count("gateway.resolve_verified(**values)") == 2
    assert "DELETE FROM ae_nsl_artifact WHERE tenant_id" in source
    assert "run_service_migrations" in source
    assert "scripts/smoke/data" not in source
