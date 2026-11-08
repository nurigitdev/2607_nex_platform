#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_canary import (
    AnswerSupportShadowCanary,
    build_shadow_canary_operator_approval,
    validate_shadow_canary_policy,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportShadowRuntime,
    validate_answer_support_shadow_configuration,
)
from nex_mo import remote_provider
from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING
from nex_runtime.model_artifact_revision import admit_model_artifact_revision_evidence
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpt_shadow_canary_operations.v1"
SMOKE_ENV = "NEX_GB2_S20QPT_SHADOW_CANARY"
APPROVED_ENV = "NEX_GB2_S20QPT_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPT_OPERATOR_ID"
ARTIFACT_ENV = "NEX_GB2_S20QPT_GENERATION_ARTIFACT_EVIDENCE"
RECEIPT_ENV = "NEX_GB2_S20QPT_RECEIPT_PATH"
READINESS_PATH = ROOT / "reports/live/gb2_ca00_s20qpr_runtime_activation_readiness.json"
ARTIFACT_PATH = ROOT / "reports/live/gb2_s20qpi_qwen3_5_9b_revision.json"
SHADOW_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_shadow_runtime_v1_design.json"
)
CANARY_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_shadow_canary_v1_design.json"
)
POLICY_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_shadow_canary_v1_policy.json"
)
CASES_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_shadow_canary_v1_cases.json"
)
SIGNAL_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_generation_profile_v1.json"
)
DEFAULT_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpt_shadow_canary_receipt.json"
)
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpt_shadow_canary_operations.json"
PROTECTED_ENV_KEYS = (
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

HttpRequester = Callable[..., Any]
Clock = Callable[[], datetime]


class _RecordingSink:
    def __init__(self) -> None:
        self.outcomes: list[dict[str, Any]] = []

    def record(self, outcome: Mapping[str, Any]) -> None:
        self.outcomes.append(dict(outcome))


class _LiveGenerationClient:
    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        requester: HttpRequester,
    ) -> None:
        self.environ = dict(environ)
        self.requester = requester

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return remote_provider.execute_remote_generation_request(
            payload,
            request_id=request_id,
            trace_id=trace_id,
            environ=self.environ,
            requester=self.requester,
        )


def run_gb2_s20qpt_shadow_canary_operations(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    clock: Clock | None = None,
    readiness_report: Mapping[str, Any] | None = None,
    artifact_evidence: Mapping[str, Any] | None = None,
    cases_document: Mapping[str, Any] | None = None,
    shadow_design: Mapping[str, Any] | None = None,
    canary_design: Mapping[str, Any] | None = None,
    policy_document: Mapping[str, Any] | None = None,
    signal_design: Mapping[str, Any] | None = None,
    request_profile: Mapping[str, Any] | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(APPROVED_ENV) != "1" or not env.get(OPERATOR_ENV):
        return _failure("operator_approval_required")
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
    }
    issues = _configuration_issues(
        effective_env,
        artifact_supplied=artifact_evidence is not None,
    )
    if issues:
        return _failure("configuration_invalid", detail=issues)
    target_receipt = receipt_path or Path(
        effective_env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH))
    )
    if target_receipt.exists():
        return _failure("canary_authorization_already_consumed")

    now = clock or (lambda: datetime.now(UTC))
    provider_counts = {"total": 0, "generation": 0}
    cases: list[Mapping[str, Any]] = []
    try:
        report = dict(readiness_report or _load(READINESS_PATH))
        manifest = _mapping(report.get("manifest"), "readiness manifest")
        shadow_design_value = dict(shadow_design or _load(SHADOW_DESIGN_PATH))
        canary_design_value = dict(canary_design or _load(CANARY_DESIGN_PATH))
        policy = validate_shadow_canary_policy(
            dict(policy_document or _load(POLICY_PATH))
        )
        signal_design_value = dict(signal_design or _load(SIGNAL_DESIGN_PATH))
        request_profile_value = dict(
            request_profile or _load(REQUEST_PROFILE_PATH)
        )
        configuration = validate_answer_support_shadow_configuration(
            manifest,
            signal_design=signal_design_value,
            request_profile=request_profile_value,
        )
        _validate_canary_design(
            canary_design_value,
            shadow_design=shadow_design_value,
            configuration=configuration,
            policy=policy,
        )
        artifact = dict(
            artifact_evidence
            or _load(Path(effective_env.get(ARTIFACT_ENV, str(ARTIFACT_PATH))))
        )
        artifact_revision = admit_model_artifact_revision_evidence(artifact)
        binding = configuration["candidate_profile"]["provider_binding"]
        _bind_effective_provider(effective_env, binding, artifact_revision)
        case_source = dict(cases_document or _load(CASES_PATH))
        cases = _validate_cases(
            case_source, maximum_calls=policy["maximum_provider_calls"]
        )
        approved_at = now().astimezone(UTC)
        approval = build_shadow_canary_operator_approval(
            operator_id=effective_env[OPERATOR_ENV],
            policy=policy,
            manifest_hash=manifest["manifest_hash"],
            profile_hash=configuration["candidate_profile"]["profile_hash"],
            provider_binding=binding,
            approved_at=_iso(approved_at),
            expires_at=_iso(approved_at + timedelta(minutes=30)),
        )
        reservation = {
            "receipt_schema_version": "cx_answer_support_shadow_canary_receipt.v1",
            "status": "RUNNING",
            "approval_hash": approval["approval_hash"],
            "policy_hash": policy["policy_hash"],
            "manifest_hash": manifest["manifest_hash"],
            "profile_hash": configuration["candidate_profile"]["profile_hash"],
            "provider_binding_hash": semantic_sha256_hash_ref(dict(binding)),
            "maximum_provider_calls": policy["maximum_provider_calls"],
            "started_at": _iso(approved_at),
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        reservation["receipt_hash"] = semantic_sha256_hash_ref(reservation)
        _write_exclusive_json(target_receipt, reservation)

        guarded = _budgeted_requester(
            requester,
            environ=effective_env,
            counts=provider_counts,
            maximum_requests=policy["maximum_provider_calls"],
        )
        sink = _RecordingSink()
        runtime = AnswerSupportShadowRuntime(
            readiness_manifest=manifest,
            signal_design=signal_design_value,
            request_profile=request_profile_value,
            generation_client=_LiveGenerationClient(
                environ=effective_env,
                requester=guarded,
            ),
            outcome_sink=sink,
        )
        canary = AnswerSupportShadowCanary(
            runtime=runtime,
            policy=policy,
            approval=approval,
            clock=now,
        )
        for index, case in enumerate(cases, start=1):
            canary.observe(
                query_text=str(case["query"]),
                evidence_items=[
                    {
                        "evidence_id": f"{case['case_id']}-evidence-{candidate_index}",
                        "text": text,
                        "permission_result": {"visible": True},
                    }
                    for candidate_index, text in enumerate(
                        case["candidates"], start=1
                    )
                ],
                primary_package={
                    "retrieval_package_id": f"s20qpt-package-{index}",
                    "status": case["primary_status"],
                    "purpose": case["purpose"],
                },
                access_context=CxAccessContext(
                    caller_service_id="nex-ae-api",
                    tenant_id="s20qpt-public-synthetic",
                    subject_id="shadow-canary",
                    request_id=f"s20qpt-request-{index}",
                    trace_id=f"{index:032x}",
                    scopes=("service:call",),
                ),
            )
            if canary.snapshot()["status"] == "HALTED":
                break
        snapshot = canary.snapshot()
        checks = {
            "operator_approval_bound": snapshot["approval_hash"]
            == approval["approval_hash"],
            "one_shot_budget_completed": snapshot["status"] == "COMPLETED",
            "provider_calls_exact": provider_counts
            == {
                "total": policy["maximum_provider_calls"],
                "generation": policy["maximum_provider_calls"],
            },
            "no_provider_failures": snapshot["failed_count"] == 0,
            "latency_samples_complete": snapshot["latency_sample_count"]
            == policy["maximum_provider_calls"],
            "latency_budget_passed": snapshot["p95_latency_ms"]
            <= policy["maximum_p95_latency_ms"],
            "token_budget_passed": snapshot["total_tokens"]
            <= policy["maximum_total_tokens"],
            "holdout_not_accessed": True,
            "shadow_not_user_visible": snapshot["user_visible"] is False,
            "runtime_activation_prohibited": snapshot[
                "runtime_activation_permitted"
            ]
            is False,
            "production_cutover_prohibited": snapshot[
                "production_cutover_permitted"
            ]
            is False,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        terminal = {
            **{key: value for key, value in reservation.items() if key != "receipt_hash"},
            "status": status,
            "completed_at": _iso(now().astimezone(UTC)),
            "snapshot": snapshot,
            "provider_http_requests": dict(provider_counts),
            "checks": checks,
            "decision": (
                "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED"
                if status == "PASS"
                else "SHADOW_CANARY_HALTED_FALLBACK_PRESERVED"
            ),
        }
        terminal["receipt_hash"] = semantic_sha256_hash_ref(terminal)
        _replace_json(target_receipt, terminal)
    except Exception as exc:  # noqa: BLE001 - protected boundary consumes failures
        failure = _failure(
            "shadow_canary_execution_failed",
            detail={"exception": exc.__class__.__name__},
        )
        failure.update(
            {
                "provider_http_requests": dict(provider_counts),
                "runtime_activation_permitted": False,
                "production_cutover_permitted": False,
            }
        )
        _assert_redacted(failure, effective_env, cases=cases)
        return failure

    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-T",
        "status": terminal["status"],
        "decision": terminal["decision"],
        "approval_hash": approval["approval_hash"],
        "policy_hash": policy["policy_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "profile_hash": configuration["candidate_profile"]["profile_hash"],
        "provider_binding_hash": semantic_sha256_hash_ref(dict(binding)),
        "provider_http_requests": dict(provider_counts),
        "canary_snapshot": snapshot,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "SEPARATE_RUNTIME_CUTOVER_OPERATOR_DECISION",
    }
    _assert_redacted(result, effective_env, cases=cases)
    return result


def _validate_canary_design(
    design: Mapping[str, Any],
    *,
    shadow_design: Mapping[str, Any],
    configuration: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    source = _mapping(design.get("source_binding"), "source binding")
    execution = _mapping(design.get("execution_boundary"), "execution boundary")
    stop = _mapping(design.get("stop_conditions"), "stop conditions")
    safety = _mapping(design.get("safety"), "safety")
    profile = configuration["candidate_profile"]
    if (
        design.get("design_schema_version")
        != "cx_answer_support_shadow_canary_design.v1"
        or design.get("status") != "FROZEN_LIMITED_LIVE_CANARY"
        or source.get("shadow_runtime_design_hash")
        != semantic_sha256_hash_ref(dict(shadow_design))
        or source.get("readiness_manifest_hash")
        != configuration["manifest"]["manifest_hash"]
        or source.get("runtime_profile_hash") != profile["profile_hash"]
        or source.get("request_profile_hash")
        != configuration["request_profile"]["profile_hash"]
        or source.get("signal_design_hash")
        != configuration["signal_design"]["design_hash"]
        or execution.get("operator_approval_required_before_provider_call") is not True
        or execution.get("approval_scope") != "SHADOW_CANARY_EXECUTION_ONLY"
        or execution.get("one_shot_receipt_required") is not True
        or execution.get("public_synthetic_cases_only") is not True
        or execution.get("holdout_access_permitted") is not False
        or execution.get("maximum_concurrency")
        != policy["maximum_concurrency"]
        or execution.get("fallback_policy") != policy["fallback_policy"]
        or stop.get("provider_binding_drift") != "IMMEDIATE"
        or stop.get("permission_or_contract_drift") != "IMMEDIATE"
        or stop.get("provider_failure_budget_exceeded") != "IMMEDIATE"
        or stop.get("disagreement") != "OBSERVE_ONLY"
        or safety.get("raw_query_or_candidate_persistence_permitted") is not False
        or safety.get("shadow_decision_user_visible") is not False
        or safety.get("runtime_activation_permitted") is not False
        or safety.get("production_cutover_permitted") is not False
        or safety.get("post_canary_operator_review_required") is not True
    ):
        raise ValueError("shadow canary design binding drifted")


def _validate_cases(
    document: Mapping[str, Any], *, maximum_calls: int
) -> list[Mapping[str, Any]]:
    cases = document.get("cases")
    if (
        document.get("case_schema_version")
        != "cx_answer_support_shadow_canary_cases.v1"
        or document.get("status") != "FROZEN_PUBLIC_SYNTHETIC"
        or not isinstance(cases, list)
        or len(cases) != maximum_calls
    ):
        raise ValueError("shadow canary case set is invalid")
    normalized = []
    for case in cases:
        row = _mapping(case, "canary case")
        candidates = row.get("candidates")
        if (
            set(row)
            != {"case_id", "primary_status", "purpose", "query", "candidates"}
            or row.get("primary_status") not in {"READY", "LOW_CONFIDENCE"}
            or row.get("purpose") not in {"grounded_answer", "document_generation"}
            or not isinstance(candidates, list)
            or not candidates
            or not all(isinstance(value, str) and value.strip() for value in candidates)
            or not isinstance(row.get("query"), str)
            or not str(row["query"]).strip()
        ):
            raise ValueError("shadow canary case is invalid")
        normalized.append(row)
    return normalized


def _bind_effective_provider(
    environ: dict[str, str],
    binding: Mapping[str, Any],
    artifact_revision: str,
) -> None:
    revision = str(binding["model_revision"])
    deployment = str(binding["deployment_id"])
    if artifact_revision != revision:
        raise ValueError("generation artifact revision differs from readiness binding")
    configured_revision = environ.get("NEX_MO_VLLM_MODEL_REVISION")
    configured_deployment = environ.get("NEX_MO_VLLM_DEPLOYMENT_ID")
    if configured_revision not in {None, "", revision}:
        raise ValueError("configured generation revision differs from readiness binding")
    if configured_deployment not in {
        None,
        "",
        "vllm-generation-http",
        CANONICAL_GENERATION_BINDING.deployment_id,
        deployment,
    }:
        raise ValueError("configured generation deployment differs from readiness binding")
    environ["NEX_MO_VLLM_MODEL_REVISION"] = revision
    environ["NEX_MO_VLLM_DEPLOYMENT_ID"] = deployment


def _budgeted_requester(
    requester: HttpRequester | None,
    *,
    environ: Mapping[str, str],
    counts: dict[str, int],
    maximum_requests: int,
) -> HttpRequester:
    base = requester or remote_provider.httpx.request
    config = remote_provider.build_remote_generation_execution_config(dict(environ))
    lock = Lock()

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        with lock:
            if url != config.url:
                raise ValueError("shadow canary attempted an unbound provider route")
            if counts["total"] >= maximum_requests:
                raise ValueError("shadow canary provider HTTP budget exceeded")
            counts["total"] += 1
            counts["generation"] += 1
        return base(method, url, **kwargs)

    return guarded


def _configuration_issues(
    environ: Mapping[str, str], *, artifact_supplied: bool = False
) -> list[str]:
    issues = []
    if not (
        environ.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
        or environ.get("NEX_MO_VLLM_BASE_URL")
    ):
        issues.append("generation_endpoint")
    for key in ("NEX_MO_VLLM_API_KEY", "NEX_MO_VLLM_MODEL"):
        if not environ.get(key):
            issues.append(key)
    artifact_path = Path(environ.get(ARTIFACT_ENV, str(ARTIFACT_PATH)))
    if not artifact_supplied and not artifact_path.is_file():
        issues.append(ARTIFACT_ENV)
    return issues


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-T",
        "status": "FAIL",
        "failure_code": code,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    *,
    cases: list[Mapping[str, Any]],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)
    ]
    protected.extend(str(case["query"]) for case in cases)
    protected.extend(
        str(candidate) for case in cases for candidate in case["candidates"]
    )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q-P-T evidence contains protected data")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        snapshot = result.get("canary_snapshot")
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
        return (
            "gb2_s20qpt_shadow_canary_operations=pass "
            f"calls={snapshot.get('provider_calls')} "
            f"failures={snapshot.get('failed_count')} "
            f"p95_ms={snapshot.get('p95_latency_ms')} "
            f"disagreements={snapshot.get('disagreement_count')} "
            "cutover=operator_review_required"
        )
    if status == "skipped":
        return "gb2_s20qpt_shadow_canary_operations=skipped"
    return (
        "gb2_s20qpt_shadow_canary_operations=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpt_shadow_canary_operations()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
