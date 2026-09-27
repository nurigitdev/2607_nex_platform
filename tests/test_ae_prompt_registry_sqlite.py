from __future__ import annotations

import json

import run_ae_prompt_registry_sqlite as smoke


def test_sqlite_smoke_passes() -> None:
    result = smoke.run_ae_prompt_registry_sqlite()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["binding_count"] == 4
    assert result["render_event_count"] == 1
    assert result["actual_postgres"] is False
    assert result["next_slice"] == "1025"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_ae_prompt_registry_sqlite()
    assert smoke.summary_line(passing) == (
        "ae_prompt_registry_sqlite=pass checks=6/6 bindings=4 events=1 next=1025"
    )
    assert len(smoke._schema_statements()) == 4

    monkeypatch.setattr(smoke, "run_ae_prompt_registry_sqlite", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "sqlite=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_prompt_registry_sqlite",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert smoke.main([]) == 1
