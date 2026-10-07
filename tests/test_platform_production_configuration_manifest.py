from __future__ import annotations

import run_platform_production_configuration_manifest as smoke


def test_repository_manifest_evidence_is_complete() -> None:
    result = smoke.run_platform_production_configuration_manifest()

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "binding_count": 25,
        "secret_reference_count": 16,
        "public_connection_count": 9,
        "control_environment_count": 6,
        "owner_count": 6,
    }
    assert result["decision"] == {
        "raw_secret_environment_is_deployment_input": False,
        "external_reference_is_deployment_input": True,
        "runtime_materialization_performed": False,
        "production_connection_required": False,
        "new_table_required": False,
        "next_slice": "1425",
    }


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_configuration_manifest()
    assert smoke.summary_line(passing) == (
        "platform_production_configuration_manifest=pass bindings=25 "
        "secrets=16 connections=9 controls=6 owners=6 next=1425"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_production_configuration_manifest=fail"
    )

    monkeypatch.setattr(
        smoke, "run_platform_production_configuration_manifest", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "manifest=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_production_configuration_manifest",
        lambda: (_ for _ in ()).throw(ValueError("bad manifest")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out

