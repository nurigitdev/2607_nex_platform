from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_collection import (
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    ANSWER_SUPPORT_SHADOW_OUTCOME_SCHEMA_VERSION,
    AnswerSupportShadowRuntime,
    score_answer_support_shadow_features,
    validate_answer_support_shadow_configuration,
)


ROOT = Path(__file__).resolve().parents[1]
REVISION = "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
QUERY = "정산 기준을 알려줘"
EVIDENCE_TEXTS = ("첫 번째 승인 기준", "두 번째 정산 근거")


class RecordingSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.outcomes: list[dict[str, Any]] = []

    def record(self, outcome) -> None:
        if self.error is not None:
            raise self.error
        self.outcomes.append(dict(outcome))


class FakeGenerationClient:
    def __init__(
        self,
        *,
        deployment_id: str = "dgx-qwen3-5-9b-9116",
        error: Exception | None = None,
        ready: bool = True,
    ) -> None:
        self.deployment_id = deployment_id
        self.error = error
        self.ready = ready
        self.calls: list[dict[str, Any]] = []

    def create_generation(self, payload, *, request_id: str, trace_id: str):
        self.calls.append(
            {"payload": deepcopy(payload), "request_id": request_id, "trace_id": trace_id}
        )
        if self.error is not None:
            raise self.error
        user_payload = json.loads(payload["messages"][1]["content"])
        items = []
        for index, candidate in enumerate(user_payload["candidates"]):
            items.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "classification": (
                        "SUPPORTING_EVIDENCE" if self.ready else "TOPICAL_NON_ANSWER"
                    ),
                    "answer_support_score": (
                        0.9 - index * 0.1 if self.ready else 0.1
                    ),
                    "contradiction_score": 0.05 if self.ready else 0.3,
                }
            )
        return {
            "alias": "general-llm-default",
            "model_revision": REVISION,
            "deployment_id": self.deployment_id,
            "provider_type": "vllm",
            "output": {"type": "text", "text": json.dumps({"items": items})},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


def test_shadow_runtime_observes_ready_without_persisting_private_text() -> None:
    sink = RecordingSink()
    client = FakeGenerationClient()
    runtime = _runtime(client=client, sink=sink)

    outcome = runtime.observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )

    assert outcome["outcome_schema_version"] == ANSWER_SUPPORT_SHADOW_OUTCOME_SCHEMA_VERSION
    assert outcome["status"] == "OBSERVED"
    assert outcome["shadow_decision"] == "READY"
    assert outcome["primary_shadow_agree"] is True
    assert outcome["provider_called"] is True
    assert outcome["user_visible"] is False
    assert outcome["primary_decision_mutated"] is False
    assert outcome["runtime_activation_permitted"] is False
    assert outcome["usage"] == {
        "input_tokens": 20,
        "output_tokens": 10,
        "total_tokens": 30,
    }
    assert sink.outcomes == [outcome]
    serialized = json.dumps(outcome, ensure_ascii=False)
    assert QUERY not in serialized
    assert all(text not in serialized for text in EVIDENCE_TEXTS)
    assert client.calls[0]["payload"]["reasoning_mode"] == "disabled"
    assert client.calls[0]["payload"]["temperature"] == 0.0


def test_shadow_runtime_records_low_confidence_disagreement() -> None:
    outcome = _runtime(client=FakeGenerationClient(ready=False)).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )

    assert outcome["status"] == "OBSERVED"
    assert outcome["shadow_decision"] == "LOW_CONFIDENCE"
    assert outcome["primary_shadow_agree"] is False
    assert outcome["shadow_score"] < outcome["threshold"]


@pytest.mark.parametrize(
    ("purpose", "with_evidence", "reason", "decision"),
    [
        ("search", True, "PURPOSE_NOT_ELIGIBLE", "NOT_EVALUATED"),
        ("grounded_answer", False, "NO_AUTHORIZED_EVIDENCE", "NOT_READY"),
    ],
)
def test_shadow_runtime_skips_without_provider_call(
    purpose: str,
    with_evidence: bool,
    reason: str,
    decision: str,
) -> None:
    client = FakeGenerationClient()

    outcome = _runtime(client=client).observe(
        query_text=QUERY,
        evidence_items=_evidence_items() if with_evidence else [],
        primary_package=_package(purpose=purpose),
        access_context=_context(),
    )

    assert outcome["status"] == "SKIPPED"
    assert outcome["skip_reason"] == reason
    assert outcome["shadow_decision"] == decision
    assert outcome["provider_called"] is False
    assert client.calls == []


def test_provider_binding_drift_and_provider_failure_are_isolated() -> None:
    drift = _runtime(
        client=FakeGenerationClient(deployment_id="unexpected-deployment")
    ).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert drift["status"] == "FAILED"
    assert drift["error_code"] == "cx.answer_support_shadow.provider_binding_drift"
    assert drift["shadow_decision"] == "NOT_READY"
    assert drift["provider_called"] is True

    unavailable = _runtime(
        client=FakeGenerationClient(error=RuntimeError("private provider detail"))
    ).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert unavailable["status"] == "FAILED"
    assert unavailable["error_code"] == "cx.answer_support_shadow.provider_unavailable"
    assert unavailable["provider_called"] is True
    assert "private provider detail" not in json.dumps(unavailable)


def test_permission_drift_and_telemetry_failure_do_not_escape() -> None:
    evidence = _evidence_items()
    evidence[0]["permission_result"]["visible"] = False
    runtime = _runtime(
        client=FakeGenerationClient(),
        sink=RecordingSink(RuntimeError("sink unavailable")),
    )

    outcome = runtime.observe(
        query_text=QUERY,
        evidence_items=evidence,
        primary_package=_package(),
        access_context=_context(),
    )

    assert outcome["status"] == "FAILED"
    assert outcome["error_code"] == "cx.answer_support_shadow.permission_drift"
    assert outcome["provider_called"] is False


def test_configuration_integrity_and_request_binding_fail_closed() -> None:
    manifest = _manifest()
    profile = _request_profile()
    design = _signal_design()

    validated = validate_answer_support_shadow_configuration(
        manifest,
        signal_design=design,
        request_profile=profile,
    )
    assert validated["candidate_profile"]["status"] == "READY_FOR_SHADOW"

    tampered = deepcopy(manifest)
    tampered["candidate_profile"]["threshold"] = 0.1
    with pytest.raises(ValueError, match="manifest_integrity"):
        validate_answer_support_shadow_configuration(
            tampered,
            signal_design=design,
            request_profile=profile,
        )

    rebound = deepcopy(manifest)
    rebound.pop("manifest_hash")
    candidate = rebound["candidate_profile"]
    candidate.pop("profile_hash")
    candidate["request_profile_hash"] = "sha256:" + "0" * 64
    candidate["profile_hash"] = semantic_sha256_hash_ref(candidate)
    rebound["manifest_hash"] = semantic_sha256_hash_ref(rebound)
    with pytest.raises(ValueError, match="request_profile_binding"):
        validate_answer_support_shadow_configuration(
            rebound,
            signal_design=design,
            request_profile=profile,
        )


@pytest.mark.parametrize(
    ("mutation", "rehash_profile", "message"),
    [
        (lambda value: value["candidate_profile"].__setitem__("threshold", 0.2), False, "profile_integrity"),
        (lambda value: value.__setitem__("status", "ACTIVE"), True, "readiness_boundary"),
        (
            lambda value: value["candidate_profile"]["provider_binding"].pop(
                "deployment_id"
            ),
            True,
            "provider_binding",
        ),
        (
            lambda value: value["candidate_profile"].__setitem__(
                "policy_id", "other-policy"
            ),
            True,
            "candidate_profile",
        ),
    ],
)
def test_each_shadow_configuration_boundary_fails_closed(
    mutation,
    rehash_profile: bool,
    message: str,
) -> None:
    manifest = _manifest()
    mutation(manifest)
    _rehash_manifest(manifest, rehash_profile=rehash_profile)

    with pytest.raises(ValueError, match=message):
        validate_answer_support_shadow_configuration(
            manifest,
            signal_design=_signal_design(),
            request_profile=_request_profile(),
        )


def test_invalid_runtime_input_and_provider_response_are_sanitized() -> None:
    invalid_input = _runtime().observe(
        query_text=QUERY,
        evidence_items="bad",  # type: ignore[arg-type]
        primary_package={"retrieval_package_id": 1, "status": 2, "purpose": "grounded_answer"},
        access_context=_context(),
    )
    assert invalid_input["error_code"] == "cx.answer_support_shadow.contract_invalid"
    assert invalid_input["provider_called"] is False
    assert invalid_input["retrieval_package_id"] is None
    assert invalid_input["primary_status"] is None

    class InvalidResponseClient(FakeGenerationClient):
        def create_generation(self, payload, *, request_id: str, trace_id: str):
            result = super().create_generation(
                payload, request_id=request_id, trace_id=trace_id
            )
            result["finish_reason"] = "LENGTH"
            return result

    invalid_response = _runtime(client=InvalidResponseClient()).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert invalid_response["error_code"] == (
        "cx.answer_support_shadow.provider_response_invalid"
    )
    assert invalid_response["provider_called"] is True


def test_non_mapping_usage_is_omitted() -> None:
    class SparseUsageClient(FakeGenerationClient):
        def create_generation(self, payload, *, request_id: str, trace_id: str):
            result = super().create_generation(
                payload, request_id=request_id, trace_id=trace_id
            )
            result["usage"] = "unknown"
            return result

    outcome = _runtime(client=SparseUsageClient()).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert outcome["status"] == "OBSERVED"
    assert outcome["usage"] is None

    class InvalidCountsClient(FakeGenerationClient):
        def create_generation(self, payload, *, request_id: str, trace_id: str):
            result = super().create_generation(
                payload, request_id=request_id, trace_id=trace_id
            )
            result["usage"] = {
                "input_tokens": True,
                "output_tokens": -1,
                "total_tokens": "30",
            }
            return result

    invalid_counts = _runtime(client=InvalidCountsClient()).observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert invalid_counts["usage"] is None


@pytest.mark.parametrize(
    "evidence",
    [
        [{"evidence_id": "one", "text": "text", "permission_result": []}],
        [{"evidence_id": "one", "text": " ", "permission_result": {"visible": True}}],
    ],
)
def test_malformed_private_evidence_fails_before_provider(evidence) -> None:
    outcome = _runtime().observe(
        query_text=QUERY,
        evidence_items=evidence,
        primary_package=_package(),
        access_context=_context(),
    )
    assert outcome["status"] == "FAILED"
    assert outcome["error_code"] == "cx.answer_support_shadow.contract_invalid"
    assert outcome["provider_called"] is False


def test_unexpected_internal_failure_is_sanitized() -> None:
    class ExplodingRuntime(AnswerSupportShadowRuntime):
        def _evaluate(self, **_kwargs):
            raise KeyError("private internal detail")

    base = _runtime()
    runtime = ExplodingRuntime(
        readiness_manifest=base.readiness_manifest,
        signal_design=base.signal_design,
        request_profile=base.request_profile,
        generation_client=base.generation_client,
        outcome_sink=base.outcome_sink,
    )
    outcome = runtime.observe(
        query_text=QUERY,
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    assert outcome["error_code"] == "cx.answer_support_shadow.provider_unavailable"
    assert outcome["provider_called"] is False
    assert "private internal detail" not in json.dumps(outcome)


def test_feature_score_guards_invalid_values() -> None:
    projection = {
        "features": {
            "direct_or_support_fraction": 1.0,
            "second_answer_support_score": 0.8,
            "top_two_answer_support_mean": 0.85,
            "maximum_contradiction_score": 0.1,
            "support_contradiction_margin": 0.775,
        }
    }
    assert score_answer_support_shadow_features(projection) == 0.893125

    projection["features"]["maximum_contradiction_score"] = True
    with pytest.raises(ValueError, match="score"):
        score_answer_support_shadow_features(projection)

    projection["features"]["maximum_contradiction_score"] = 0.1
    projection["features"]["support_contradiction_margin"] = -2.0
    with pytest.raises(ValueError, match="margin"):
        score_answer_support_shadow_features(projection)


def _runtime(*, client=None, sink=None) -> AnswerSupportShadowRuntime:
    return AnswerSupportShadowRuntime(
        readiness_manifest=_manifest(),
        signal_design=_signal_design(),
        request_profile=_request_profile(),
        generation_client=client or FakeGenerationClient(),
        outcome_sink=sink or RecordingSink(),
    )


def _manifest() -> dict[str, Any]:
    profile = {
        "profile_schema_version": "cx_answer_support_runtime_profile.v1",
        "profile_id": "answer-support-contradiction-aware-v2",
        "profile_version": "1.0.0",
        "status": "READY_FOR_SHADOW",
        "policy_id": "cx_answer_support_contradiction_aware_ready_v2",
        "score_semantics": "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY",
        "threshold": 0.46375,
        "threshold_inclusive": True,
        "provider_binding": {
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "model_revision": REVISION,
            "provider_alias": "general-llm-default",
            "provider_type": "vllm",
            "request_profile_id": "s136-answer-support-generation-json-v1",
            "score_semantics_id": "bounded-ordinal-answer-support-v1",
        },
        "request_profile_hash": validate_answer_support_request_profile(
            _request_profile()
        )["profile_hash"],
        "dataset": {
            "dataset_id": "dataset-v4",
            "dataset_semantic_sha256": "sha256:" + "a" * 64,
            "partition": "HOLDOUT",
        },
        "evidence_binding": {
            "execution_id": "execution",
            "authorization_hash": "sha256:" + "b" * 64,
            "receipt_hash": "sha256:" + "c" * 64,
            "evaluation_hash": "sha256:" + "d" * 64,
        },
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "runtime_activation_permitted": False,
    }
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)
    manifest = {
        "manifest_schema_version": (
            "cx_answer_support_runtime_activation_readiness_manifest.v1"
        ),
        "status": "PASS",
        "decision": "READY_FOR_SHADOW_RUNTIME_INTEGRATION",
        "activation_status": "NOT_ACTIVATED",
        "candidate_profile": profile,
        "rollout_boundary": {
            "first_stage": "SHADOW",
            "shadow_decision_user_visible": False,
            "fail_closed_on_binding_drift": True,
        },
        "holdout_reexecution_permitted": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _rehash_manifest(
    manifest: dict[str, Any],
    *,
    rehash_profile: bool,
) -> None:
    manifest.pop("manifest_hash", None)
    if rehash_profile:
        profile = manifest["candidate_profile"]
        profile.pop("profile_hash", None)
        profile["profile_hash"] = semantic_sha256_hash_ref(profile)
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)


def _request_profile() -> dict[str, Any]:
    return json.loads(
        (ROOT / "scripts/smoke/data/s136_answer_support_generation_profile_v1.json").read_text(
            encoding="utf-8"
        )
    )


def _signal_design() -> dict[str, Any]:
    return json.loads(
        (ROOT / "scripts/smoke/data/s136_answer_support_signal_v1_design.json").read_text(
            encoding="utf-8"
        )
    )


def _package(*, purpose: str = "grounded_answer") -> dict[str, Any]:
    return {
        "retrieval_package_id": "package-one",
        "status": "READY",
        "purpose": purpose,
    }


def _evidence_items() -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": f"evidence-{index}",
            "text": text,
            "permission_result": {"visible": True},
        }
        for index, text in enumerate(EVIDENCE_TEXTS, start=1)
    ]


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-one",
        subject_id="owner-one",
        request_id="request-one",
        trace_id="1" * 32,
        scopes=("service:call",),
    )
