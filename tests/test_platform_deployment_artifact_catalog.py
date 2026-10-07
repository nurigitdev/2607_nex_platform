from __future__ import annotations

import run_platform_deployment_artifact_catalog as smoke


def test_artifact_catalog_evidence_is_complete_and_private() -> None:
    result = smoke.run_platform_deployment_artifact_catalog()

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "artifact_count": 6,
        "process_binding_count": 13,
        "owner_count": 6,
        "unbound_process_count": 0,
    }
    assert result["catalog_digest"].startswith("sha256:")
    assert len(result["catalog_digest"]) == 71
    assert result["decision"] == {
        "catalog_is_canonical": True,
        "mutable_tag_admitted": False,
        "secret_value_present": False,
        "production_connection_required": False,
        "next_slice": "1414",
    }


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_deployment_artifact_catalog()
    assert smoke.summary_line(passing) == (
        "platform_deployment_artifact_catalog=pass "
        "artifacts=6 bindings=13 owners=6 unbound=0 next=1414"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_deployment_artifact_catalog=fail"
    )

    monkeypatch.setattr(
        smoke, "run_platform_deployment_artifact_catalog", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "catalog=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_deployment_artifact_catalog",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1

