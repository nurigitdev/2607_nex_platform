from __future__ import annotations

import subprocess

import run_platform_packaged_entrypoints as smoke


def test_packaged_entrypoint_evidence_executes_all_background_checks() -> None:
    result = smoke.run_platform_packaged_entrypoints()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "entrypoint_count": 13,
        "background_entrypoint_count": 7,
        "executed_check_count": 7,
        "job_claiming_background_count": 1,
        "lifecycle_only_background_count": 6,
        "source_tree_command_count": 0,
    }
    assert result["decision"]["staging_or_production_background_admitted"] is False


def test_packaged_background_check_normalizes_invalid_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "not-json\n", ""),
    )

    result = smoke._run_packaged_background_check(
        ("python", "-m", "module", "worker"), tmp_path, "nex-cx"
    )

    assert result == {"returncode": 1, "metadata": {"status": "INVALID_OUTPUT"}}


def test_packaged_background_check_accepts_empty_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 2, "", "blocked"),
    )

    result = smoke._run_packaged_background_check(
        ("python", "-m", "module", "worker"), tmp_path, "nex-cx"
    )

    assert result == {"returncode": 2, "metadata": {}}


def test_packaged_entrypoint_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_packaged_entrypoints()
    assert smoke.summary_line(passing) == (
        "platform_packaged_entrypoints=pass entrypoints=13 background=7 "
        "executed=7 claiming=1 lifecycle_only=6 next=1417"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_packaged_entrypoints=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_packaged_entrypoints", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "entrypoints=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_packaged_entrypoints",
        lambda: (_ for _ in ()).throw(ValueError("bad entrypoint")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
