from __future__ import annotations

import json

import run_platform_postgres_restart_state_machine as smoke
from nex_runtime.postgres_restart_coordinator import PostgresRestartCoordinatorError


def test_state_machine_smoke_and_summary() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS"
    assert result["generation_count"] == 2
    assert result["restart_count"] == 1
    assert result["migration_gate_count"] == 2
    assert result["fresh_engine_count"] == 10
    assert result["shutdown_order"] == ["runtime_processes", "postgres_pools"]
    assert smoke.summary_line(result) == (
        "platform_postgres_restart_state_machine=pass "
        "generations=2 restarts=1 fresh=10 next=1329"
    )


def test_failure_projection_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.PlatformPostgresRestartCoordinator,
        "start",
        lambda self: (_ for _ in ()).throw(
            PostgresRestartCoordinatorError("normalized_failure", {})
        ),
    )

    result = smoke.run_smoke()

    assert result == {
        "schema_version": "platform_postgres_restart_state_machine_smoke.v1",
        "status": "FAIL",
        "failure_code": "normalized_failure",
    }
    assert smoke.summary_line(result).endswith("code=normalized_failure")
    assert smoke.summary_line({"status": "FAIL"}).endswith("code=failed")


def test_main_json_summary_and_failure(monkeypatch, capsys) -> None:
    passing = smoke.run_smoke()
    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)

    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert smoke.main(["--summary"]) == 0
    assert "generations=2" in capsys.readouterr().out

    monkeypatch.setattr(smoke, "run_smoke", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1
