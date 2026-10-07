from __future__ import annotations

import run_platform_production_api_key_custody as smoke


def test_repository_api_key_custody_evidence_passes() -> None:
    result = smoke.run_platform_production_api_key_custody()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "provider_api_key_count": 3,
        "non_owner_exposure_count": 0,
        "redaction_leak_count": 0,
    }
    assert result["decision"]["next_slice"] == "1429"


def test_summary_main_and_failure_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_api_key_custody()
    assert smoke.summary_line(passing) == (
        "platform_production_api_key_custody=pass keys=3 exposures=0 leaks=0 next=1429"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_production_api_key_custody=fail"
    )
    monkeypatch.setattr(smoke, "run_platform_production_api_key_custody", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "custody=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_production_api_key_custody",
        lambda: (_ for _ in ()).throw(ValueError("bad custody")),
    )
    assert smoke.main([]) == 1


def test_smoke_detects_permissive_custody(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "redact_sensitive_runtime_data", lambda value, **kwargs: value)
    result = smoke.run_platform_production_api_key_custody()
    assert result["status"] == "FAIL"
    assert result["summary"]["redaction_leak_count"] == 3


def test_smoke_detects_cross_owner_custody_acceptance(monkeypatch) -> None:
    real_admit = smoke.admit_production_api_key_custody
    admitted = []

    def permissive(value):
        if not admitted:
            admitted.append(real_admit(value))
        return admitted[0]

    monkeypatch.setattr(smoke, "admit_production_api_key_custody", permissive)
    result = smoke.run_platform_production_api_key_custody()
    assert result["status"] == "FAIL"
    assert result["checks"]["cross_owner_exposure_blocked"] is False
