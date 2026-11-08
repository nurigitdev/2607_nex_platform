from __future__ import annotations

import json
from types import SimpleNamespace

import run_p6_ca02_s5_worker_readiness_smoke as smoke


def _readiness(status: str = "PASS") -> dict[str, object]:
    return {
        "schema_version": "nsl_installed_package_readiness.v1",
        "status": status,
        "distribution": "nex-skill-language",
        "wheel_sha256": "sha256:" + "1" * 64,
        "platform_lock_sha256": "sha256:" + "2" * 64,
        "in_process_profile_admissible": status == "PASS",
    }


def test_smoke_is_protected() -> None:
    evidence = smoke.run_p6_ca02_s5_worker_readiness_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_installed_wheel"] is False


def test_smoke_combines_installed_package_default_and_compatibility(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "load_in_process_nsl_package_readiness",
        lambda _env: _readiness(),
    )
    monkeypatch.setattr(
        smoke,
        "build_v01_in_process_backend",
        lambda _factory: SimpleNamespace(
            backend_profile=smoke.NSL_V01_IN_PROCESS_BACKEND,
            execute=lambda **_kwargs: {},
        ),
    )

    evidence = smoke.run_p6_ca02_s5_worker_readiness_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "PASS"
    assert evidence["checks_passed"] == evidence["checks_total"] == 8
    assert evidence["actual_postgres"] is False
    assert evidence["remote_provider_required"] is False
    assert "p6_ca02_s5_worker_readiness=pass" in smoke.summary_line(evidence)


def test_smoke_reports_failed_readiness_and_contained_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "load_in_process_nsl_package_readiness",
        lambda _env: _readiness("FAIL"),
    )
    monkeypatch.setattr(
        smoke,
        "build_v01_in_process_backend",
        lambda _factory: SimpleNamespace(
            backend_profile=smoke.NSL_V01_IN_PROCESS_BACKEND,
            execute=lambda **_kwargs: {},
        ),
    )
    failed = smoke.run_p6_ca02_s5_worker_readiness_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["status"] == "FAIL"
    assert failed["checks"]["worker_startup_readiness_passed"] is False

    monkeypatch.setattr(
        smoke,
        "load_in_process_nsl_package_readiness",
        lambda _env: (_ for _ in ()).throw(RuntimeError("contained")),
    )
    errored = smoke.run_p6_ca02_s5_worker_readiness_smoke({smoke.SMOKE_ENV: "1"})
    assert errored["failure_code"] == "execution_failed"
    assert errored["actual_installed_wheel"] is False


def test_main_writes_only_executed_evidence(monkeypatch, tmp_path, capsys) -> None:
    passed = {
        "status": "PASS",
        "actual_installed_wheel": True,
        "checks_passed": 8,
        "checks_total": 8,
        "default_backend_profile": "NSL_V01_IN_PROCESS",
    }
    report = tmp_path / "readiness.json"
    monkeypatch.setattr(smoke, "DEFAULT_REPORT", report)
    monkeypatch.setattr(smoke, "run_p6_ca02_s5_worker_readiness_smoke", lambda: passed)

    assert smoke.main(["--summary"]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "checks=8/8" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_p6_ca02_s5_worker_readiness_smoke",
        lambda: {"status": "SKIPPED", "actual_installed_wheel": False},
    )
    assert smoke.main([]) == 0
