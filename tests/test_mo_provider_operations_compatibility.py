from __future__ import annotations

import json

import pytest

import run_mo_provider_operations_compatibility as compatibility


def architecture(status: str = "PASS") -> dict[str, object]:
    return {
        "status": status,
        "summary": {"module_rule_pass_count": 8},
    }


def skipped() -> dict[str, object]:
    return {"status": "SKIPPED"}


def passing_profile() -> dict[str, object]:
    return {
        "status": "PASS",
        "stage_status": {
            "local_live_config": "PASS",
            "dgx_live_preflight": "PASS",
        },
    }


def passing_providers() -> dict[str, object]:
    return {
        "status": "PASS",
        "stage_status": {
            "activation": "PASS",
            "configuration": "PASS",
            "embedding": "PASS",
            "reranking": "PASS",
            "generation": "PASS",
            "assertions": "PASS",
        },
    }


def passing_dtype() -> dict[str, object]:
    return {
        "status": "PASS",
        "observations": [
            {"bf16_confirmed": True, "bf16_explicit": True},
            {"bf16_confirmed": True, "bf16_explicit": True},
            {"bf16_confirmed": True, "bf16_explicit": True},
        ],
    }


def test_repository_compatibility_is_deterministic_without_live_opt_in() -> None:
    evidence = compatibility.run_mo_provider_operations_compatibility({})

    assert evidence["status"] == "PASS"
    assert evidence["readiness"] == "DETERMINISTIC_COMPATIBLE_LIVE_NOT_REQUESTED"
    assert evidence["component_status"] == {
        "architecture": "PASS",
        "profile_preflight": "SKIPPED",
        "provider_requests": "SKIPPED",
        "process_dtype": "SKIPPED",
    }
    assert evidence["summary"]["architecture_modules"] == 8
    assert evidence["next_slice"] == "1121"


def test_live_opt_in_propagates_protected_activation_and_summarizes_evidence() -> None:
    observed: list[dict[str, str]] = []

    def capture(result: dict[str, object]):
        def runner(env: dict[str, str]) -> dict[str, object]:
            observed.append(env)
            return result

        return runner

    evidence = compatibility.run_mo_provider_operations_compatibility(
        {compatibility.ACTIVATION_ENV: "1"},
        architecture_runner=architecture,
        profile_runner=capture(passing_profile()),
        provider_runner=capture(passing_providers()),
        dtype_runner=capture(passing_dtype()),
    )

    assert evidence["status"] == "PASS"
    assert evidence["readiness"] == "LIVE_COMPATIBLE"
    assert evidence["summary"] == {
        "architecture_modules": 8,
        "profile_stages_passed": 2,
        "provider_requests_passed": 3,
        "bf16_confirmed": 3,
        "bf16_explicit": 3,
    }
    assert all(env["NEX_MO_PROTECTED_LIVE_PROFILE"] == "dgx_vllm" for env in observed)
    assert all(env["NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE"] == "1" for env in observed)
    assert all(env["NEX_MO_DGX_PROCESS_DTYPE_PROBE"] == "1" for env in observed)
    assert "providers=3/3 bf16=3/3 explicit=3/3 next=1121" in (
        compatibility.summary_line(evidence)
    )


@pytest.mark.parametrize(
    ("architecture_status", "profile_status", "live_requested", "expected_component"),
    [
        ("FAIL", "SKIPPED", False, "architecture"),
        ("PASS", "FAIL", False, "profile_preflight"),
        ("PASS", "SKIPPED", True, "profile_preflight"),
    ],
)
def test_compatibility_fails_closed_for_architecture_live_failure_or_required_skip(
    architecture_status: str,
    profile_status: str,
    live_requested: bool,
    expected_component: str,
) -> None:
    env = {compatibility.ACTIVATION_ENV: "1"} if live_requested else {}
    evidence = compatibility.run_mo_provider_operations_compatibility(
        env,
        architecture_runner=lambda: architecture(architecture_status),
        profile_runner=lambda unused: {"status": profile_status},
        provider_runner=lambda unused: skipped(),
        dtype_runner=lambda unused: skipped(),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["readiness"] == "BLOCKED"
    assert evidence["next_slice"] is None
    assert expected_component in {item["component"] for item in evidence["issues"]}


def test_helpers_ignore_malformed_optional_evidence_and_reject_protected_value() -> None:
    assert compatibility._status({"status": "unexpected"}) == "FAIL"
    assert compatibility._architecture_module_count({"summary": None}) == 0
    assert compatibility._passed_stage_count({"stage_status": None}) == 0
    assert compatibility._provider_request_count({"stage_status": None}) == 0
    assert compatibility._dtype_count({"observations": None}, "bf16_confirmed") == 0
    assert compatibility._dtype_count(
        {"observations": [None, {"bf16_confirmed": True}]},
        "bf16_confirmed",
    ) == 1

    with pytest.raises(ValueError, match="NEX_MO_VLLM_API_KEY"):
        compatibility.assert_evidence_redacted(
            "prefix-generation-secret-suffix",
            {"NEX_MO_VLLM_API_KEY": "generation-secret"},
        )


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = compatibility.run_mo_provider_operations_compatibility({})
    monkeypatch.setattr(
        compatibility,
        "run_mo_provider_operations_compatibility",
        lambda: passing,
    )
    assert compatibility.main(["--summary"]) == 0
    assert "compatibility=pass" in capsys.readouterr().out
    assert compatibility.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        compatibility,
        "run_mo_provider_operations_compatibility",
        lambda: {"status": "FAIL", "summary": {}, "component_status": {}},
    )
    assert compatibility.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
