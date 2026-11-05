from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_canary import (
    AnswerSupportShadowCanary,
    AnswerSupportShadowCanaryError,
    build_shadow_canary_operator_approval,
    validate_shadow_canary_operator_approval,
    validate_shadow_canary_policy,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self, outcomes) -> None:
        self.readiness_manifest = _manifest()
        self.outcomes = list(outcomes)
        self.calls = 0

    def observe(self, **_kwargs):
        self.calls += 1
        return dict(self.outcomes.pop(0))


def test_canary_completes_bounded_budget_and_preserves_non_activation() -> None:
    outcomes = [
        _outcome(elapsed_ms=100.25 + index, agree=index != 2)
        for index in range(6)
    ]
    runtime = FakeRuntime(outcomes)
    canary = _canary(runtime)

    for _ in range(6):
        result = canary.observe(**_observation())

    snapshot = canary.snapshot()
    assert result["canary_snapshot"]["status"] == "COMPLETED"
    assert snapshot["provider_calls"] == 6
    assert snapshot["observed_count"] == 6
    assert snapshot["disagreement_count"] == 1
    assert snapshot["latency_sample_count"] == 6
    assert snapshot["p95_latency_ms"] == 105.25
    assert snapshot["total_tokens"] == 180
    assert snapshot["runtime_activation_permitted"] is False
    assert snapshot["production_cutover_permitted"] is False

    skipped = canary.observe(**_observation())
    assert skipped["skip_reason"] == "CANARY_BUDGET_EXHAUSTED"
    assert skipped["provider_called"] is False
    assert runtime.calls == 6


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (
            {
                "status": "FAILED",
                "provider_called": True,
                "elapsed_ms": 100,
                "usage": {"total_tokens": 30},
                "primary_shadow_agree": True,
                "error_code": "cx.answer_support_shadow.provider_binding_drift",
            },
            "cx.answer_support_shadow.provider_binding_drift",
        ),
        (
            {
                "status": "FAILED",
                "provider_called": True,
                "elapsed_ms": 100,
                "usage": {"total_tokens": 30},
                "primary_shadow_agree": True,
                "error_code": "cx.answer_support_shadow.provider_unavailable",
            },
            "PROVIDER_FAILURE_BUDGET_EXCEEDED",
        ),
        (
            {
                "status": "OBSERVED",
                "provider_called": True,
                "elapsed_ms": 60_001,
                "usage": {"total_tokens": 30},
                "primary_shadow_agree": True,
            },
            "SINGLE_LATENCY_BUDGET_EXCEEDED",
        ),
        (
            {
                "status": "OBSERVED",
                "provider_called": True,
                "elapsed_ms": 100,
                "usage": {"total_tokens": 12_001},
                "primary_shadow_agree": True,
            },
            "TOKEN_BUDGET_EXCEEDED",
        ),
        (
            {
                "status": "OBSERVED",
                "provider_called": True,
                "usage": {"total_tokens": 30},
                "primary_shadow_agree": True,
            },
            "LATENCY_TELEMETRY_MISSING",
        ),
    ],
)
def test_canary_halts_on_stop_condition(outcome, reason: str) -> None:
    runtime = FakeRuntime([outcome])
    canary = _canary(runtime)

    canary.observe(**_observation())

    assert canary.snapshot()["status"] == "HALTED"
    assert canary.snapshot()["terminal_reason"] == reason
    assert canary.observe(**_observation())["skip_reason"] == "CANARY_HALTED"
    assert runtime.calls == 1


def test_canary_halts_on_terminal_p95_budget() -> None:
    policy = _policy()
    policy["maximum_provider_calls"] = 2
    policy["maximum_p95_latency_ms"] = 100
    runtime = FakeRuntime([_outcome(elapsed_ms=90), _outcome(elapsed_ms=101)])
    canary = _canary(runtime, policy=policy)

    canary.observe(**_observation())
    canary.observe(**_observation())

    assert canary.snapshot()["terminal_reason"] == "P95_LATENCY_BUDGET_EXCEEDED"


def test_policy_and_operator_approval_fail_closed() -> None:
    policy = _policy()
    normalized = validate_shadow_canary_policy(policy)
    assert normalized["policy_hash"].startswith("sha256:")

    manifest = _manifest()
    profile = manifest["candidate_profile"]
    approval = _approval(policy=policy, manifest=manifest)
    admitted = validate_shadow_canary_operator_approval(
        approval,
        policy=policy,
        manifest_hash=manifest["manifest_hash"],
        profile_hash=profile["profile_hash"],
        provider_binding=profile["provider_binding"],
        now=NOW,
    )
    assert admitted["scope"] == "SHADOW_CANARY_EXECUTION_ONLY"

    tampered = deepcopy(approval)
    tampered["maximum_provider_calls"] = 7
    with pytest.raises(AnswerSupportShadowCanaryError, match="invalid"):
        validate_shadow_canary_operator_approval(
            tampered,
            policy=policy,
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            now=NOW,
        )

    with pytest.raises(AnswerSupportShadowCanaryError, match="invalid"):
        validate_shadow_canary_operator_approval(
            approval,
            policy=policy,
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            now=datetime(2026, 11, 5, 2, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("maximum_provider_calls"),
        lambda value: value.__setitem__("maximum_concurrency", 2),
        lambda value: value.__setitem__("maximum_error_rate", 0.1),
        lambda value: value.__setitem__("maximum_provider_calls", 0),
        lambda value: value.__setitem__("maximum_single_latency_ms", True),
        lambda value: value.__setitem__("maximum_error_rate", True),
    ],
)
def test_policy_rejects_drift(mutation) -> None:
    policy = _policy()
    mutation(policy)
    with pytest.raises(AnswerSupportShadowCanaryError):
        validate_shadow_canary_policy(policy)


def test_approval_rejects_invalid_window_and_naive_clock_is_admitted() -> None:
    manifest = _manifest()
    profile = manifest["candidate_profile"]
    with pytest.raises(AnswerSupportShadowCanaryError):
        build_shadow_canary_operator_approval(
            operator_id="operator-one",
            policy=_policy(),
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            approved_at="2026-11-05T01:00:00Z",
            expires_at="2026-11-05T01:00:00Z",
        )

    approval = _approval(policy=_policy(), manifest=manifest)
    assert validate_shadow_canary_operator_approval(
        approval,
        policy=_policy(),
        manifest_hash=manifest["manifest_hash"],
        profile_hash=profile["profile_hash"],
        provider_binding=profile["provider_binding"],
        now=NOW.replace(tzinfo=None),
    )["status"] == "APPROVED"


def test_policy_hash_approval_fields_and_scope_drift_fail_closed() -> None:
    policy = validate_shadow_canary_policy(_policy())
    policy["policy_hash"] = "sha256:" + "0" * 64
    with pytest.raises(AnswerSupportShadowCanaryError):
        validate_shadow_canary_policy(policy)

    manifest = _manifest()
    profile = manifest["candidate_profile"]
    with pytest.raises(AnswerSupportShadowCanaryError):
        validate_shadow_canary_operator_approval(
            {},
            policy=_policy(),
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            now=NOW,
        )

    approval = _approval(policy=_policy(), manifest=manifest)
    approval.pop("approval_hash")
    approval["status"] = "REVOKED"
    approval["approval_hash"] = semantic_sha256_hash_ref(approval)
    with pytest.raises(AnswerSupportShadowCanaryError):
        validate_shadow_canary_operator_approval(
            approval,
            policy=_policy(),
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            now=NOW,
        )


@pytest.mark.parametrize(
    ("approved_at", "operator_id"),
    [
        ("2026-11-05T01:00:00+00:00", "operator-one"),
        ("not-a-timeZ", "operator-one"),
        ("2026-11-05T01:00:00Z", " "),
    ],
)
def test_approval_builder_rejects_invalid_timestamp_or_operator(
    approved_at: str, operator_id: str
) -> None:
    manifest = _manifest()
    profile = manifest["candidate_profile"]
    with pytest.raises(AnswerSupportShadowCanaryError):
        build_shadow_canary_operator_approval(
            operator_id=operator_id,
            policy=_policy(),
            manifest_hash=manifest["manifest_hash"],
            profile_hash=profile["profile_hash"],
            provider_binding=profile["provider_binding"],
            approved_at=approved_at,
            expires_at="2026-11-05T01:30:00Z",
        )


def test_canary_rejects_missing_runtime_profile() -> None:
    runtime = FakeRuntime([])
    runtime.readiness_manifest = {}
    with pytest.raises(AnswerSupportShadowCanaryError):
        AnswerSupportShadowCanary(
            runtime=runtime,
            policy=_policy(),
            approval={},
            clock=lambda: NOW,
        )

    runtime.readiness_manifest = {
        "manifest_hash": "sha256:" + "a" * 64,
        "candidate_profile": {
            "profile_hash": "sha256:" + "b" * 64,
            "provider_binding": [],
        },
    }
    with pytest.raises(AnswerSupportShadowCanaryError):
        AnswerSupportShadowCanary(
            runtime=runtime,
            policy=_policy(),
            approval={},
            clock=lambda: NOW,
        )


def test_non_provider_outcome_and_invalid_usage_do_not_create_latency_sample() -> None:
    runtime = FakeRuntime(
        [
            {
                "status": "SKIPPED",
                "provider_called": False,
                "usage": {"total_tokens": True},
            },
            {
                "status": "FAILED",
                "provider_called": False,
                "error_code": "cx.answer_support_shadow.contract_invalid",
            },
        ]
    )
    canary = _canary(runtime)

    first = canary.observe(**_observation())
    assert first["canary_snapshot"]["status"] == "RUNNING"
    assert first["canary_snapshot"]["provider_calls"] == 0
    assert first["canary_snapshot"]["latency_sample_count"] == 0
    assert first["canary_snapshot"]["p95_latency_ms"] == 0.0

    canary.observe(**_observation())
    assert canary.snapshot()["status"] == "HALTED"


def test_invalid_provider_usage_is_ignored_without_losing_latency() -> None:
    policy = _policy()
    policy["maximum_provider_calls"] = 2
    runtime = FakeRuntime(
        [
            {
                "status": "OBSERVED",
                "provider_called": True,
                "elapsed_ms": 10.5,
                "usage": {"total_tokens": True},
                "primary_shadow_agree": True,
            },
            {
                "status": "OBSERVED",
                "provider_called": True,
                "elapsed_ms": 11.5,
                "usage": None,
                "primary_shadow_agree": True,
            },
        ]
    )
    canary = _canary(runtime, policy=policy)

    canary.observe(**_observation())
    canary.observe(**_observation())

    assert canary.snapshot()["status"] == "COMPLETED"
    assert canary.snapshot()["latency_sample_count"] == 2
    assert canary.snapshot()["total_tokens"] == 0


def _canary(runtime, *, policy=None) -> AnswerSupportShadowCanary:
    selected_policy = policy or _policy()
    return AnswerSupportShadowCanary(
        runtime=runtime,
        policy=selected_policy,
        approval=_approval(
            policy=selected_policy,
            manifest=runtime.readiness_manifest,
        ),
        clock=lambda: NOW,
    )


def _policy() -> dict:
    return __import__("json").loads(
        (
            ROOT
            / "scripts/smoke/data/s136_answer_support_shadow_canary_v1_policy.json"
        ).read_text(encoding="utf-8")
    )


def _manifest() -> dict:
    profile = {
        "profile_hash": "sha256:" + "b" * 64,
        "provider_binding": {
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "provider_alias": "general-llm-default",
            "provider_type": "vllm",
            "request_profile_id": "s136-answer-support-generation-json-v1",
            "score_semantics_id": "bounded-ordinal-answer-support-v1",
        },
    }
    return {
        "manifest_hash": "sha256:" + "a" * 64,
        "candidate_profile": profile,
    }


def _approval(*, policy: dict, manifest: dict) -> dict:
    profile = manifest["candidate_profile"]
    return build_shadow_canary_operator_approval(
        operator_id="operator-one",
        policy=policy,
        manifest_hash=manifest["manifest_hash"],
        profile_hash=profile["profile_hash"],
        provider_binding=profile["provider_binding"],
        approved_at="2026-11-05T01:00:00Z",
        expires_at="2026-11-05T01:30:00Z",
    )


def _outcome(
    *,
    status: str = "OBSERVED",
    elapsed_ms: float = 100.0,
    total_tokens: int = 30,
    agree: bool = True,
    error_code: str | None = None,
) -> dict:
    value = {
        "status": status,
        "provider_called": True,
        "elapsed_ms": elapsed_ms,
        "usage": {"total_tokens": total_tokens},
        "primary_shadow_agree": agree,
    }
    if error_code:
        value["error_code"] = error_code
    return value


def _observation() -> dict:
    return {
        "query_text": "private query",
        "evidence_items": [{"text": "private evidence"}],
        "primary_package": {"status": "READY"},
        "access_context": CxAccessContext(
            caller_service_id="nex-ae-api",
            tenant_id="tenant",
            subject_id="subject",
            request_id="request",
            trace_id="1" * 32,
            scopes=("service:call",),
        ),
    }
