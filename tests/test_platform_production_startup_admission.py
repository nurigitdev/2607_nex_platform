from __future__ import annotations

import run_platform_production_startup_admission as smoke


def test_repository_production_startup_admission_passes() -> None:
    result = smoke.run_platform_production_startup_admission()

    assert result["status"] == "PASS"
    assert all(result["fail_closed_cases"].values())
    assert result["summary"] == {
        "secret_reference_count": 16,
        "public_connection_count": 9,
        "control_environment_count": 6,
        "https_endpoint_count": 9,
        "fail_closed_case_count": 6,
    }
    assert result["decision"] == {
        "admitted_for_secret_materialization": True,
        "secret_materialization_performed": False,
        "external_connection_required": False,
        "production_deployment_approved": False,
        "next_slice": "1426",
    }


def test_summary_main_and_fail_closed_else_branch(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_startup_admission()
    assert smoke.summary_line(passing) == (
        "platform_production_startup_admission=pass secrets=16 connections=9 "
        "controls=6 https=9 fail_closed=6 next=1426"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_production_startup_admission=fail"
    )

    monkeypatch.setattr(
        smoke, "run_platform_production_startup_admission", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "admission=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_production_startup_admission",
        lambda: (_ for _ in ()).throw(ValueError("bad startup")),
    )
    assert smoke.main([]) == 1


def test_smoke_detects_permissive_admission(monkeypatch) -> None:
    real_admission = smoke.admit_production_startup

    def permissive(environment, *, root):
        try:
            return real_admission(environment, root=root)
        except smoke.ProductionStartupAdmissionError:
            return real_admission(smoke._synthetic_environment(root), root=root)

    monkeypatch.setattr(smoke, "admit_production_startup", permissive)
    result = smoke.run_platform_production_startup_admission()
    assert result["status"] == "FAIL"
    assert not any(result["fail_closed_cases"].values())
    assert result["decision"]["next_slice"] == "blocked"

