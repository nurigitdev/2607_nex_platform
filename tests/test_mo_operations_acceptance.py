from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nex_mo.operations_acceptance import (
    OperationsAcceptancePlan,
    build_operations_acceptance_plan,
)
import run_mo_operations_acceptance_plan as runner


def _env() -> dict[str, str]:
    return runner.acceptance_environment()


def test_acceptance_plan_admits_only_complete_protected_test_profile() -> None:
    env = _env()
    plan = build_operations_acceptance_plan(env)
    wire = plan.to_wire()
    serialized = json.dumps(wire, sort_keys=True)

    assert plan.admission_status == "READY"
    assert plan.issues == ()
    assert wire["database"] == {
        "configured": True,
        "name": "nex_mo_test",
        "role": "nex_mo_user",
    }
    assert [target["provider_capability"] for target in wire["targets"]] == [
        "embedding",
        "reranking",
        "generation",
    ]
    for private in (
        env["NEX_MO_TEST_DATABASE_URL"],
        env["NEX_MO_REMOTE_EMBEDDING_URL"],
        env["NEX_MO_REMOTE_EMBEDDING_API_KEY"],
        env["NEX_MO_DGX_SSH_TARGET"],
    ):
        assert private not in serialized


def test_default_environment_is_blocked_without_private_values() -> None:
    plan = build_operations_acceptance_plan({})

    assert plan.admission_status == "BLOCKED"
    assert {
        "acceptance_not_enabled",
        "acceptance_profile_not_allowed",
        "provider_mode_not_live",
        "test_database_not_configured",
        "runtime_observation_not_live",
    }.issubset(plan.issues)
    assert len(plan.targets) == 3


@pytest.mark.parametrize(
    ("updates", "issue"),
    [
        ({"NEX_MO_OPERATIONS_LIVE_ACCEPTANCE": "0"}, "acceptance_not_enabled"),
        ({"NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE": "dev"}, "acceptance_profile_not_allowed"),
        ({"NEX_MO_PROVIDER_MODE": "mock"}, "provider_mode_not_live"),
        ({"NEX_MO_TEST_DATABASE_URL": "bad"}, "test_database_not_configured"),
        (
            {
                "NEX_MO_TEST_DATABASE_URL": (
                    "postgresql+psycopg://wrong:private@127.0.0.1/wrong"
                )
            },
            "test_database_identity_not_allowed",
        ),
        ({"NEX_MO_REMOTE_EMBEDDING_URL": ""}, "embedding_endpoint_not_configured"),
        ({"NEX_MO_REMOTE_RERANKER_API_KEY": ""}, "reranking_authorization_not_configured"),
        (
            {"NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "legacy"},
            "embedding_request_shape_invalid",
        ),
        ({"NEX_MO_DGX_SSH_TARGET": "bad target"}, "runtime_observation_configuration_invalid"),
    ],
)
def test_acceptance_plan_blocks_invalid_configuration(updates, issue: str) -> None:
    env = {**_env(), **updates}
    plan = build_operations_acceptance_plan(env)

    assert plan.admission_status == "BLOCKED"
    assert issue in plan.issues


def test_provider_configuration_failure_is_safe_and_deduplicated() -> None:
    env = {
        **_env(),
        "NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS": "bad",
        "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "mock",
    }
    plan = build_operations_acceptance_plan(env)

    assert "provider_acceptance_configuration_invalid" in plan.issues
    assert "runtime_observation_not_live" in plan.issues
    assert len(plan.issues) == len(set(plan.issues))


def test_missing_expected_model_is_blocked(monkeypatch) -> None:
    configs = tuple(
        SimpleNamespace(
            capability=capability,
            endpoint_env=f"{capability}_url",
            configured=True,
            request_shape={
                "embedding": "openai_embeddings",
                "reranking": "rerank",
                "generation": "openai_models",
            }[capability],
            expected_models=() if capability == "generation" else ("model",),
            api_key_env=f"{capability}_key",
            authorization_configured=True,
            timeout_seconds=15.0,
        )
        for capability in ("embedding", "reranking", "generation")
    )
    monkeypatch.setattr(
        "nex_mo.operations_acceptance.build_remote_provider_preflight_configs",
        lambda env: configs,
    )

    plan = build_operations_acceptance_plan(_env())
    assert "generation_expected_model_missing" in plan.issues


def test_acceptance_plan_value_object_reports_blocked() -> None:
    plan = OperationsAcceptancePlan(
        profile="",
        provider_mode="unknown",
        database_configured=False,
        database_name=None,
        database_role=None,
        runtime_observation_mode="unknown",
        runtime_observation_configured=False,
        targets=(),
        issues=("blocked",),
    )
    assert plan.admission_status == "BLOCKED"
    assert plan.to_wire()["redaction"]["status"] == "PASS"


def test_acceptance_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    evidence = runner.run_mo_operations_acceptance_plan()
    assert evidence["status"] == "PASS"
    assert "targets=3" in runner.summary_line(evidence)
    monkeypatch.setattr(runner, "run_mo_operations_acceptance_plan", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "database=true" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_operations_acceptance_plan",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
