from __future__ import annotations

import run_s148_slo_evaluation as smoke


def test_slo_evaluation_smoke_passes() -> None:
    result = smoke.run_slo_evaluation()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "policy_count": 5,
        "evaluation_count": 5,
        "healthy_count": 5,
        "no_data_count": 1,
    }
    assert result["next_slice"] == "1476"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_slo_evaluation()
    assert smoke.summary_line(passing) == (
        "s148_slo_evaluation=pass policies=5 healthy=5 no_data=1 checks=8/8 next=1476"
    )
    failed = {"status": "FAIL", "checks": {}, "summary": {}, "next_slice": "blocked"}
    assert smoke.summary_line(failed) == (
        "s148_slo_evaluation=fail policies=0 healthy=0 no_data=0 checks=0/8 next=blocked"
    )
    monkeypatch.setattr(smoke, "run_slo_evaluation", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "evaluation=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_slo_evaluation", lambda: failed)
    assert smoke.main([]) == 1
