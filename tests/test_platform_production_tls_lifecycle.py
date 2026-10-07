from __future__ import annotations

import run_platform_production_tls_lifecycle as smoke


def test_repository_tls_lifecycle_evidence_passes() -> None:
    result = smoke.run_platform_production_tls_lifecycle()
    assert result["status"] == "PASS"
    assert all(result["alert_checks"].values())
    assert result["summary"] == {
        "rotation_phase_count": 5,
        "rollback_phase_count": 3,
        "expiry_alert_level_count": 4,
        "private_key_exposure_count": 0,
    }
    assert result["decision"]["next_slice"] == "1430"


def test_summary_main_and_failure_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_tls_lifecycle()
    assert smoke.summary_line(passing) == "platform_production_tls_lifecycle=pass phases=5 rollback=3 alerts=4 private_keys=0 next=1430"
    assert smoke.summary_line({"status": "FAIL"}) == "platform_production_tls_lifecycle=fail"
    monkeypatch.setattr(smoke, "run_platform_production_tls_lifecycle", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "lifecycle=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_platform_production_tls_lifecycle", lambda: (_ for _ in ()).throw(ValueError("bad TLS")))
    assert smoke.main([]) == 1
