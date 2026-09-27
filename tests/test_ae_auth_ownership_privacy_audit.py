from __future__ import annotations

from pathlib import Path

from nex_ae_api.ownership_privacy_audit import (
    BOUNDARY_SURFACES,
    BoundarySurface,
    _inspect_surface,
    build_ae_auth_ownership_privacy_audit,
)
import run_ae_auth_ownership_privacy_audit as runner


def test_repository_auth_ownership_privacy_audit_tracks_remaining_gaps() -> None:
    result = build_ae_auth_ownership_privacy_audit()

    assert result["status"] == "PASS"
    assert result["readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "surface_count": 10,
        "hardened_count": 9,
        "refactor_count": 1,
        "high_risk_count": 1,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["new_table_required"] is False
    assert result["decision"]["refactor_before_feature"] is True


def test_high_risk_refactors_are_exact_and_owner_related() -> None:
    result = build_ae_auth_ownership_privacy_audit()
    high_risk = {
        item["surface_id"]: item
        for item in result["surfaces"]
        if item["risk"] == "HIGH"
    }

    assert set(high_risk) == {
        "artifact_file_delivery_routes",
    }
    assert all(item["status"] == "REFACTOR_REQUIRED" for item in high_risk.values())
    assert all("browser_claim" in item["privacy_posture"] for item in high_risk.values())


def test_audit_fails_closed_when_boundary_evidence_is_missing(tmp_path: Path) -> None:
    surfaces = (
        BoundarySurface(
            "missing",
            "missing.py",
            "token",
            "REFACTOR_REQUIRED",
            "HIGH",
            "claim",
            "browser_claim_missing",
        ),
    )

    result = build_ae_auth_ownership_privacy_audit(tmp_path, surfaces=surfaces)

    assert result["status"] == "FAIL"
    assert result["readiness"] == "BLOCKED"
    assert result["checks"]["surface_inventory_complete"] is False
    assert result["checks"]["boundary_evidence_present"] is False
    assert result["checks"]["high_risk_gaps_classified"] is False
    assert result["issues"][0]["path"] == "missing.py"


def test_surface_inspection_covers_present_and_missing_tokens(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("expected token\n", encoding="utf-8")
    surface = BoundarySurface(
        "sample",
        "source.py",
        "expected token",
        "HARDENED",
        "LOW",
        "claim",
        "redacted",
    )

    assert _inspect_surface(tmp_path, surface)["evidence_present"] is True
    source.write_text("wrong\n", encoding="utf-8")
    assert _inspect_surface(tmp_path, surface)["evidence_present"] is False


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_auth_ownership_privacy_audit()

    assert "audit=pass" in runner.summary_line(passing)
    assert "high_risk=1" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_ae_auth_ownership_privacy_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "hardened=9" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_ae_auth_ownership_privacy_audit", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "audit=fail" in capsys.readouterr().out


def test_boundary_surface_ids_are_unique() -> None:
    ids = [surface.surface_id for surface in BOUNDARY_SURFACES]
    assert len(ids) == 10
    assert len(ids) == len(set(ids))
