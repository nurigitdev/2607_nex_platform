from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from nex_runtime.platform_trust_restart_plan import (
    TRUST_PROCESS_STOP_ORDER,
    TRUST_RESTART_CHECKPOINTS,
    build_platform_trust_restart_plan,
    evaluate_platform_trust_restart_checkpoints,
    validate_platform_trust_restart_plan,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/smoke/run_platform_trust_restart_plan.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("platform_trust_restart_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_trust_restart_plan_is_two_generation_and_dependency_ordered() -> None:
    plan = build_platform_trust_restart_plan()
    wire = plan.to_wire()

    assert validate_platform_trust_restart_plan(plan) == ()
    assert wire["generation_count"] == 2
    assert wire["database_service_count"] == 5
    assert wire["process_start_order"][0] == "nex-oa"
    assert wire["process_stop_order"] == TRUST_PROCESS_STOP_ORDER
    assert wire["remote_model_providers_allowed"] is False
    assert wire["temporary_key_cleanup_required"] is True


@pytest.mark.parametrize(
    ("changes", "expected_issue"),
    [
        ({"phase_order": ()}, "phase_order_invalid"),
        ({"process_start_order": ()}, "process_start_order_invalid"),
        ({"process_stop_order": ()}, "process_stop_order_invalid"),
        ({"generation_count": 1}, "generation_count_invalid"),
        ({"database_service_count": 4}, "database_service_count_invalid"),
        ({"remote_model_providers_allowed": True}, "remote_model_provider_boundary_invalid"),
        ({"temporary_key_cleanup_required": False}, "temporary_key_cleanup_missing"),
    ],
)
def test_platform_trust_restart_plan_rejects_drift(
    changes: dict[str, object], expected_issue: str
) -> None:
    plan = replace(build_platform_trust_restart_plan(), **changes)
    assert expected_issue in validate_platform_trust_restart_plan(plan)


def test_restart_checkpoint_evaluator_requires_exact_inventory() -> None:
    passing = evaluate_platform_trust_restart_checkpoints(TRUST_RESTART_CHECKPOINTS)
    missing = evaluate_platform_trust_restart_checkpoints(
        TRUST_RESTART_CHECKPOINTS[:-1]
    )
    duplicate = evaluate_platform_trust_restart_checkpoints(
        (*TRUST_RESTART_CHECKPOINTS, TRUST_RESTART_CHECKPOINTS[0], "unknown")
    )

    assert passing["status"] == "PASS"
    assert missing["missing_checkpoints"] == ["revoked_token_denied"]
    assert duplicate["status"] == "FAIL"
    assert duplicate["duplicate_count"] == 1
    assert duplicate["unknown_checkpoints"] == ["unknown"]


def test_platform_trust_restart_plan_runner_and_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _runner_module()
    result = module.run_platform_trust_restart_plan(ROOT)

    assert result["status"] == "PASS"
    assert result["phase_count"] == 16
    assert result["checkpoint_count"] == 4
    assert module.main(["--summary"]) == 0
    assert (
        "platform_trust_restart_plan=pass phases=16 generations=2 services=5 "
        "checkpoints=4 next=1339"
        in capsys.readouterr().out
    )
