from __future__ import annotations

import run_platform_service_token_admission as runner


def test_fastapi_signed_token_admission_smoke_passes() -> None:
    evidence = runner.run_platform_service_token_admission()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["read_http_status"] == 200
    assert evidence["mock_http_status"] == 401
    assert evidence["introspection_call_count"] == 1
    assert evidence["next_slice"] == "1275"


def test_summary_and_main(capsys, monkeypatch) -> None:
    evidence = runner.run_platform_service_token_admission()
    assert runner.summary_line(evidence) == (
        "platform_service_token_admission=pass read=200 mock=401 "
        "introspection=1 next=1275"
    )
    monkeypatch.setattr(runner, "run_platform_service_token_admission", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "platform_service_token_admission=pass" in capsys.readouterr().out
    failed = {
        "status": "FAIL",
        "read_http_status": 0,
        "mock_http_status": 0,
        "introspection_call_count": 0,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(runner, "run_platform_service_token_admission", lambda: failed)
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
