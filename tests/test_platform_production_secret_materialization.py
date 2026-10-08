from __future__ import annotations

import run_platform_production_secret_materialization as smoke


def test_repository_secret_materialization_evidence_passes() -> None:
    result = smoke.run_platform_production_secret_materialization()
    assert result["status"] == "PASS"
    assert result["owner_secret_counts"] == {
        "nex-oa": 2,
        "nex-ag": 5,
        "nex-ae-api": 5,
        "nex-cx": 4,
        "nex-mo": 4,
    }
    assert all(result["fail_closed_cases"].values())
    assert result["summary"] == {
        "owner_count": 5,
        "secret_count": 20,
        "fail_closed_case_count": 3,
        "secret_value_leak_count": 0,
    }
    assert result["decision"]["next_slice"] == "1427"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_secret_materialization()
    assert smoke.summary_line(passing) == (
        "platform_production_secret_materialization=pass owners=5 secrets=20 "
        "fail_closed=3 leaks=0 next=1427"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_production_secret_materialization=fail"
    )
    monkeypatch.setattr(
        smoke, "run_platform_production_secret_materialization", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "materialization=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_production_secret_materialization",
        lambda: (_ for _ in ()).throw(ValueError("bad materialization")),
    )
    assert smoke.main([]) == 1


def test_smoke_detects_secret_value_leak(monkeypatch) -> None:
    real_projection = smoke.production_secret_materialization_projection

    def leaking_projection(value):
        projection = real_projection(value)
        projection["leak"] = next(iter(value.environment_for("nex-oa").values()))
        return projection

    monkeypatch.setattr(
        smoke, "production_secret_materialization_projection", leaking_projection
    )
    result = smoke.run_platform_production_secret_materialization()
    assert result["status"] == "FAIL"
    assert result["summary"]["secret_value_leak_count"] == 1
    assert result["decision"]["next_slice"] == "blocked"


def test_smoke_detects_permissive_materializer(monkeypatch) -> None:
    real_materialize = smoke.materialize_production_secrets

    def permissive(environment, resolver, *, root):
        return real_materialize(
            environment, smoke._DeterministicSecretResolver(), root=root
        )

    monkeypatch.setattr(smoke, "materialize_production_secrets", permissive)
    result = smoke.run_platform_production_secret_materialization()
    assert result["status"] == "FAIL"
    assert not any(result["fail_closed_cases"].values())
