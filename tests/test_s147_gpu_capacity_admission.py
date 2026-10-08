from __future__ import annotations

import run_s147_gpu_capacity_admission as smoke


def test_gpu_capacity_admission_passes() -> None:
    result = smoke.run_gpu_capacity_admission()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "node_count": 2,
        "admitted_count": 1,
        "blocked_count": 3,
        "released_count": 1,
        "check_count": 10,
    }
    assert result["next_slice"] == "1466"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_gpu_capacity_admission()
    assert smoke.summary_line(result) == (
        "gpu_capacity_admission=pass nodes=2 admitted=1 blocked=3 "
        "released=1 checks=10/10 next=1466"
    )
    monkeypatch.setattr(smoke, "run_gpu_capacity_admission", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1466" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_gpu_capacity_admission",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
