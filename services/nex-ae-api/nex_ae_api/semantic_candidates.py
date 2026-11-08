from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass


SEMANTIC_CALIBRATION_POLICIES_ENV = (
    "NEX_AE_P65_SEMANTIC_CALIBRATION_POLICIES_JSON"
)
SEMANTIC_STAGES = frozenset({"INTENT", "CONTEXT", "PLAN"})

_POLICY_KEYS = {
    "semantic_stage",
    "policy_ref",
    "policy_version",
    "model_profile",
    "model_ref",
    "minimum_confidence",
    "golden_evidence_ref",
    "adversarial_evidence_ref",
}
_POLICY_REF = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S{1,240}$")


@dataclass(frozen=True)
class SemanticCandidateStageError(Exception):
    status_code: int
    error_code: str
    detail: str
    directive: str = "BLOCKED"
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class SemanticCalibrationPolicy:
    semantic_stage: str
    policy_ref: str
    policy_version: str
    model_profile: str
    model_ref: str
    minimum_confidence: float
    golden_evidence_ref: str
    adversarial_evidence_ref: str


@dataclass(frozen=True)
class SemanticCalibrationRegistry:
    policies: tuple[SemanticCalibrationPolicy, ...] = ()

    def __post_init__(self) -> None:
        identities: set[tuple[str, str, str]] = set()
        for policy in self.policies:
            _validate_calibration_policy(policy)
            identity = (
                policy.semantic_stage,
                policy.model_profile,
                policy.model_ref,
            )
            if identity in identities:
                raise _configuration_error(
                    "Duplicate semantic calibration stage/model identity."
                )
            identities.add(identity)

    def select(
        self,
        *,
        semantic_stage: str,
        model_profile: str,
        model_ref: str,
    ) -> SemanticCalibrationPolicy | None:
        matches = [
            policy
            for policy in self.policies
            if policy.semantic_stage == semantic_stage
            and policy.model_profile == model_profile
            and policy.model_ref == model_ref
        ]
        return matches[0] if matches else None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "SemanticCalibrationRegistry":
        env = os.environ if environ is None else environ
        raw_value = env.get(SEMANTIC_CALIBRATION_POLICIES_ENV, "[]")
        try:
            records = json.loads(raw_value)
        except (TypeError, ValueError) as exc:
            raise _configuration_error(
                f"{SEMANTIC_CALIBRATION_POLICIES_ENV} must be valid JSON."
            ) from exc
        if not isinstance(records, list) or len(records) > 96:
            raise _configuration_error(
                f"{SEMANTIC_CALIBRATION_POLICIES_ENV} must contain at most 96 policies."
            )
        policies: list[SemanticCalibrationPolicy] = []
        for record in records:
            if not isinstance(record, dict) or set(record) != _POLICY_KEYS:
                raise _configuration_error(
                    "Semantic calibration policy fields do not match the contract."
                )
            threshold = record["minimum_confidence"]
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(float(threshold))
            ):
                raise _configuration_error(
                    "Semantic calibration minimum_confidence must be finite."
                )
            for field_name in _POLICY_KEYS - {"minimum_confidence"}:
                if not isinstance(record[field_name], str):
                    raise _configuration_error(
                        f"Semantic calibration {field_name} must be text."
                    )
            policies.append(
                SemanticCalibrationPolicy(
                    semantic_stage=record["semantic_stage"],
                    policy_ref=record["policy_ref"],
                    policy_version=record["policy_version"],
                    model_profile=record["model_profile"],
                    model_ref=record["model_ref"],
                    minimum_confidence=float(threshold),
                    golden_evidence_ref=record["golden_evidence_ref"],
                    adversarial_evidence_ref=record["adversarial_evidence_ref"],
                )
            )
        return cls(tuple(policies))


def _validate_calibration_policy(policy: SemanticCalibrationPolicy) -> None:
    if policy.semantic_stage not in SEMANTIC_STAGES:
        raise _configuration_error("Semantic calibration stage is invalid.")
    for value, field_name, maximum in (
        (policy.policy_version, "policy_version", 64),
        (policy.model_profile, "model_profile", 128),
        (policy.model_ref, "model_ref", 256),
    ):
        _bounded_text(value, field_name, maximum)
    if not isinstance(policy.policy_ref, str) or _POLICY_REF.fullmatch(policy.policy_ref) is None:
        raise _configuration_error("Semantic calibration policy_ref is invalid.")
    if (
        isinstance(policy.minimum_confidence, bool)
        or not isinstance(policy.minimum_confidence, (int, float))
        or not math.isfinite(float(policy.minimum_confidence))
        or not 0.0 <= float(policy.minimum_confidence) <= 1.0
    ):
        raise _configuration_error(
            "Semantic calibration minimum_confidence must be between zero and one."
        )
    for evidence_ref in (
        policy.golden_evidence_ref,
        policy.adversarial_evidence_ref,
    ):
        if not isinstance(evidence_ref, str) or _POLICY_REF.fullmatch(evidence_ref) is None:
            raise _configuration_error("Semantic calibration evidence ref is invalid.")


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _configuration_error(
            f"Semantic calibration {field_name} must be bounded text."
        )
    return value.strip()


def _configuration_error(detail: str) -> SemanticCandidateStageError:
    return SemanticCandidateStageError(
        500,
        "SEMANTIC_CALIBRATION_CONFIG_INVALID",
        detail,
    )
