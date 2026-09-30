from __future__ import annotations

import run_mo_provider_telemetry_store as runner


def test_store_smoke_preserves_wire_shape_and_privacy() -> None:
    evidence = runner.run_mo_provider_telemetry_store()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "wire_field_count": 26,
        "request_count": 1,
        "attempt_count": 2,
        "retry_count": 1,
    }


def test_store_smoke_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_store()
    assert "telemetry_store=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_telemetry_store", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1156" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_store",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
