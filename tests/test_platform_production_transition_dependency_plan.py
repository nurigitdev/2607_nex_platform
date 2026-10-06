from __future__ import annotations

from pathlib import Path

import run_platform_production_transition_dependency_plan as plan


def test_repository_plan_freezes_acyclic_transition_order() -> None:
    result = plan.run_platform_production_transition_dependency_plan()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["topological_order"] == [
        f"S{number}" for number in range(142, 151)
    ]
    assert result["summary"] == {
        "requirement_count": 9,
        "wave_count": 6,
        "parallel_wave_requirement_count": 4,
        "dependency_edge_count": 16,
        "external_capability_count": 11,
        "operational_target_count": 8,
    }
    assert result["decision"] == {
        "parallel_work_allowed_after_s143": True,
        "dependency_bypass_allowed": False,
        "production_deployment_performed": False,
        "next_slice": "1410",
    }


def test_empty_repository_fails_documented_and_deployment_rules(
    tmp_path: Path,
) -> None:
    result = plan.run_platform_production_transition_dependency_plan(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == [
        "all_records_complete",
        "s150_never_implicitly_deploys",
    ]
    assert result["decision"]["next_slice"] == "blocked"


def test_topological_sort_rejects_duplicates_missing_edges_and_cycles() -> None:
    node = plan.TransitionRequirement("S1", 0, (), "test", ())
    assert plan._topological_order((node, node)) == ()
    assert plan._topological_order(
        (plan.TransitionRequirement("S1", 0, ("missing",), "test", ()),)
    ) == ()
    cyclic = (
        plan.TransitionRequirement("S1", 0, ("S2",), "test", ()),
        plan.TransitionRequirement("S2", 1, ("S1",), "test", ()),
    )
    assert plan._topological_order(cyclic) == ()
    assert plan._topological_order(()) == ()


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert plan._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert plan._read_text(source) == "value"

    passing = plan.run_platform_production_transition_dependency_plan()
    assert plan.summary_line(passing) == (
        "platform_production_transition_dependency_plan=pass requirements=9 "
        "waves=6 parallel=4 edges=16 external=11 next=1410"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert plan.summary_line(failing) == (
        "platform_production_transition_dependency_plan=fail issues=1"
    )

    monkeypatch.setattr(
        plan, "run_platform_production_transition_dependency_plan", lambda: passing
    )
    assert plan.main(["--summary"]) == 0
    assert "plan=pass" in capsys.readouterr().out
    assert plan.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        plan,
        "run_platform_production_transition_dependency_plan",
        lambda: failing,
    )
    assert plan.main([]) == 1
