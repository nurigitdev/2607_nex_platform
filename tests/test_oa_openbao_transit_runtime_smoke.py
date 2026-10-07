from __future__ import annotations

import run_oa_openbao_transit_runtime as runner


def test_transit_runtime_smoke_passes() -> None:
    result = runner.run_oa_openbao_transit_runtime()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 10,
        "transport_count": 1,
        "request_count": 2,
        "signature_bytes": 384,
    }
    assert result["decision"]["silent_fallback_allowed"] is False
    assert result["decision"]["next_slice"] == "1436"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = runner.run_oa_openbao_transit_runtime()
    assert runner.summary_line(passing) == (
        "oa_openbao_transit_runtime=pass checks=10/10 transports=1 requests=2 "
        "provider=OPENBAO_TRANSIT next=1436"
    )
    assert runner.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "oa_openbao_transit_runtime=fail issues=1"
    )
    monkeypatch.setattr(runner, "run_oa_openbao_transit_runtime", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "runtime=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_openbao_transit_runtime",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert runner.main([]) == 1
