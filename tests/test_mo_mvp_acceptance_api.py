from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import run_mo_mvp_acceptance_api as smoke


def test_api_smoke_passes() -> None:
    result = smoke.run_mo_mvp_acceptance_api()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "unauthorized_status": 401,
        "accepted_status": 200,
        "gate_count": 9,
        "passed_gate_count": 9,
        "failed_check_count": 0,
    }
    assert result["next_slice"] == "1197"


def test_static_provider_rejects_unexpected_clock() -> None:
    with pytest.raises(ValueError, match="unexpected observation time"):
        smoke.StaticEvidenceProvider().collect(
            observed_at=datetime(2026, 10, 1, 9, 1, tzinfo=UTC)
        )


def test_api_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_mvp_acceptance_api()
    assert smoke.summary_line(passing) == (
        "mo_mvp_acceptance_api=pass auth=401/200 gates=9/9 next=1197"
    )
    assert "api=fail" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(smoke, "run_mo_mvp_acceptance_api", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "api=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke, "run_mo_mvp_acceptance_api", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
