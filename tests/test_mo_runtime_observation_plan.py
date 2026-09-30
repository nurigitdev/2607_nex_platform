from __future__ import annotations

import json

import pytest

from nex_mo.runtime_observability_plan import (
    OBSERVABILITY_MODE_ENV,
    SSH_TARGET_ENV,
    build_runtime_observation_plan,
    project_runtime_observation_plan,
)
import run_mo_runtime_observation_plan as runner


def test_mock_plan_is_deterministic_complete_and_private() -> None:
    plan = build_runtime_observation_plan({})
    projected = project_runtime_observation_plan(plan)
    serialized = json.dumps(projected)

    assert plan.mode == "mock"
    assert plan.configured is True
    assert plan.ssh_target is None
    assert [target.process_port for target in plan.targets] == [9112, 9113, 9111]
    assert projected["capabilities"] == ["embedding", "reranking", "generation"]
    assert projected["requested_dtypes"] == ["bfloat16"] * 3
    assert "ssh_target" not in serialized
    assert "process_port" not in serialized


def test_live_plan_requires_and_accepts_valid_ssh_target() -> None:
    with pytest.raises(ValueError, match="SSH target"):
        build_runtime_observation_plan({OBSERVABILITY_MODE_ENV: "live"})
    with pytest.raises(ValueError, match="SSH target"):
        build_runtime_observation_plan(
            {OBSERVABILITY_MODE_ENV: "live", SSH_TARGET_ENV: "bad target"}
        )

    plan = build_runtime_observation_plan(
        {
            OBSERVABILITY_MODE_ENV: "live",
            SSH_TARGET_ENV: "operator@dgx.local",
        }
    )
    assert plan.configured is True
    assert plan.collector_protocol == "fixed_python_stdin_v1"
    assert plan.ssh_target == "operator@dgx.local"


def test_plan_supports_valid_port_overrides() -> None:
    plan = build_runtime_observation_plan(
        {
            "NEX_MO_RUNTIME_EMBEDDING_PORT": "12012",
            "NEX_MO_RUNTIME_RERANKER_PORT": "12013",
            "NEX_MO_RUNTIME_GENERATION_PORT": "12011",
        }
    )
    assert [target.process_port for target in plan.targets] == [12012, 12013, 12011]


@pytest.mark.parametrize("value", ["bad", "0", "65536"])
def test_plan_rejects_invalid_ports(value: str) -> None:
    with pytest.raises(ValueError, match="NEX_MO_RUNTIME_EMBEDDING_PORT"):
        build_runtime_observation_plan({"NEX_MO_RUNTIME_EMBEDDING_PORT": value})


def test_plan_rejects_duplicate_ports() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_runtime_observation_plan(
            {
                "NEX_MO_RUNTIME_EMBEDDING_PORT": "9111",
                "NEX_MO_RUNTIME_GENERATION_PORT": "9111",
            }
        )


def test_plan_rejects_unsupported_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        build_runtime_observation_plan({OBSERVABILITY_MODE_ENV: "other"})


def test_plan_uses_selected_generation_model_override() -> None:
    plan = build_runtime_observation_plan(
        {
            "NEX_MO_GENERATION_PROFILE": "custom-profile",
            "NEX_MO_GENERATION_MODEL_NAME": "Custom-Model",
        }
    )
    assert plan.targets[-1].model_revision == "Custom-Model"
    assert plan.targets[-1].requested_dtype == "nvfp4"


def test_plan_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observation_plan()
    assert "runtime_observation_plan=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_observation_plan", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "targets=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observation_plan",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
