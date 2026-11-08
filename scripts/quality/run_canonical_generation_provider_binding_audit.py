#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-cx"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_cx.retrieval_answer_support_controlled_activation import (  # noqa: E402
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_provider_relocation import (  # noqa: E402
    load_provider_relocation,
)
from nex_mo.provider_catalog import build_model_profile_catalog  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_generation_execution_config,
)
from nex_runtime.canonical_generation_binding import (  # noqa: E402
    CANONICAL_GENERATION_BINDING,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "canonical_generation_provider_binding_audit.v1"
SLICE = "GB2-CA00-S20S"
DEFAULT_REPORT = ROOT / "reports/quality/gb2-ca00-s20s-generation-binding.json"
EXPECTED_BINDING = {
    "profile_name": "qwen3_5_9b_bf16",
    "alias": "general-llm-default",
    "model_name": "Qwen3.5-9B",
    "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    "deployment_id": "dgx-qwen3-5-9b-9111",
    "provider_port": 9111,
    "precision": "BF16",
    "reasoning_mode": "disabled",
}
ENV_EXPECTATIONS = {
    "NEX_MO_GENERATION_PROFILE": EXPECTED_BINDING["profile_name"],
    "NEX_MO_GENERATION_MODEL_PATH": (
        "/data/nex-platform/models/qwen3.5-9b-bf16"
    ),
    "NEX_MO_GENERATION_QWEN35_9B_MODEL_PATH": (
        "/data/nex-platform/models/qwen3.5-9b-bf16"
    ),
    "NEX_MO_VLLM_MODEL": EXPECTED_BINDING["model_name"],
    "NEX_MO_VLLM_MODEL_REVISION": EXPECTED_BINDING["model_revision"],
    "NEX_MO_VLLM_DEPLOYMENT_ID": EXPECTED_BINDING["deployment_id"],
    "NEX_MO_GENERATION_MODEL_NAME": EXPECTED_BINDING["model_name"],
    "NEX_MO_GENERATION_MODEL_PRECISION": EXPECTED_BINDING["precision"],
    "NEX_MO_GENERATION_REASONING_MODE": EXPECTED_BINDING["reasoning_mode"],
    "NEX_MO_RUNTIME_GENERATION_PORT": str(EXPECTED_BINDING["provider_port"]),
    "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": EXPECTED_BINDING["model_name"],
    "NEX_CX_ANSWER_SUPPORT_PROVIDER_RELOCATION_PATH": (
        "services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json"
    ),
}
COMPOSE_MO_EXPECTATIONS = {
    "NEX_MO_VLLM_MODEL": "${NEX_MO_VLLM_MODEL:-Qwen3.5-9B}",
    "NEX_MO_VLLM_MODEL_REVISION": (
        "${NEX_MO_VLLM_MODEL_REVISION:-"
        "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a}"
    ),
    "NEX_MO_VLLM_DEPLOYMENT_ID": (
        "${NEX_MO_VLLM_DEPLOYMENT_ID:-dgx-qwen3-5-9b-9111}"
    ),
    "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": (
        "${NEX_MO_LIVE_EXPECTED_GENERATION_MODELS:-Qwen3.5-9B}"
    ),
    "NEX_MO_GENERATION_PROFILE": (
        "${NEX_MO_GENERATION_PROFILE:-qwen3_5_9b_bf16}"
    ),
    "NEX_MO_GENERATION_MODEL_NAME": (
        "${NEX_MO_GENERATION_MODEL_NAME:-Qwen3.5-9B}"
    ),
    "NEX_MO_GENERATION_MODEL_PRECISION": (
        "${NEX_MO_GENERATION_MODEL_PRECISION:-BF16}"
    ),
    "NEX_MO_GENERATION_REASONING_MODE": (
        "${NEX_MO_GENERATION_REASONING_MODE:-disabled}"
    ),
    "NEX_MO_RUNTIME_GENERATION_PORT": (
        "${NEX_MO_RUNTIME_GENERATION_PORT:-9111}"
    ),
}
COMPOSE_RELOCATION_PATH = (
    "/app/services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json"
)


def audit_canonical_generation_provider_binding(
    root: Path = ROOT,
) -> dict[str, Any]:
    issues: list[str] = []
    checks: dict[str, bool] = {}

    checks["canonical_binding_exact"] = (
        asdict(CANONICAL_GENERATION_BINDING) == EXPECTED_BINDING
    )
    _record(checks, issues, "canonical_binding_exact")

    env_values = _read_env(root / ".env.example", issues)
    checks["environment_defaults_exact"] = all(
        env_values.get(key) == value for key, value in ENV_EXPECTATIONS.items()
    )
    _record(checks, issues, "environment_defaults_exact")
    checks["four_b_is_not_environment_default"] = (
        env_values.get("NEX_MO_GENERATION_PROFILE") != "qwen3_5_4b_bf16"
        and env_values.get("NEX_MO_GENERATION_MODEL_PATH")
        != "/data/nex-platform/models/qwen3.5-4b-bf16"
    )
    _record(checks, issues, "four_b_is_not_environment_default")

    compose = _read_compose(
        root / "deployment/compose/canonical-platform.override.yaml",
        issues,
    )
    mo_environment = _service_environment(compose, "nex-mo")
    cx_environment = _service_environment(compose, "nex-cx")
    checks["compose_generation_defaults_exact"] = all(
        mo_environment.get(key) == value
        for key, value in COMPOSE_MO_EXPECTATIONS.items()
    )
    _record(checks, issues, "compose_generation_defaults_exact")
    checks["compose_relocation_admitted"] = (
        cx_environment.get("NEX_CX_ANSWER_SUPPORT_PROVIDER_RELOCATION_PATH")
        == COMPOSE_RELOCATION_PATH
    )
    _record(checks, issues, "compose_relocation_admitted")

    profiles = build_model_profile_catalog({})
    selected = [
        profile
        for profile in profiles
        if profile.provider_capability == "generation" and profile.selected
    ]
    rollback = [
        profile
        for profile in profiles
        if profile.provider_capability == "generation"
        and profile.profile_name == "qwen3_5_4b_bf16"
    ]
    checks["catalog_primary_exact"] = len(selected) == 1 and all(
        (
            selected[0].profile_name == EXPECTED_BINDING["profile_name"],
            selected[0].alias == EXPECTED_BINDING["alias"],
            selected[0].model_name == EXPECTED_BINDING["model_name"],
            selected[0].precision == EXPECTED_BINDING["precision"],
            selected[0].candidate_role == "primary",
        )
    )
    _record(checks, issues, "catalog_primary_exact")
    checks["four_b_rollback_explicit"] = (
        len(rollback) == 1
        and rollback[0].selected is False
        and rollback[0].candidate_role == "rollback"
        and rollback[0].alias == "general-llm-rollback"
    )
    _record(checks, issues, "four_b_rollback_explicit")

    execution = build_remote_generation_execution_config({})
    checks["remote_execution_binding_exact"] = all(
        (
            execution.model_name == EXPECTED_BINDING["model_name"],
            execution.model_revision == EXPECTED_BINDING["model_revision"],
            execution.deployment_id == EXPECTED_BINDING["deployment_id"],
        )
    )
    _record(checks, issues, "remote_execution_binding_exact")

    live_defaults = protected_dgx_vllm_profile_defaults()
    checks["protected_live_profile_exact"] = all(
        (
            live_defaults.get("NEX_MO_VLLM_MODEL")
            == EXPECTED_BINDING["model_name"],
            live_defaults.get("NEX_MO_VLLM_MODEL_REVISION")
            == EXPECTED_BINDING["model_revision"],
            live_defaults.get("NEX_MO_VLLM_DEPLOYMENT_ID")
            == EXPECTED_BINDING["deployment_id"],
            live_defaults.get("NEX_MO_LIVE_EXPECTED_GENERATION_MODELS")
            == EXPECTED_BINDING["model_name"],
        )
    )
    _record(checks, issues, "protected_live_profile_exact")

    try:
        activation = load_controlled_activation_bundle(DEFAULT_ACTIVATION_BUNDLE_PATH)
        relocation = load_provider_relocation(
            root
            / "services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json",
            activation_bundle=activation,
        )
        target = relocation["target_provider_binding"]
        checks["calibration_relocation_exact"] = all(
            (
                target["provider_alias"] == EXPECTED_BINDING["alias"],
                target["model_revision"] == EXPECTED_BINDING["model_revision"],
                target["deployment_id"] == EXPECTED_BINDING["deployment_id"],
                relocation["model_artifact_changed"] is False,
                relocation["request_profile_changed"] is False,
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        issues.append(f"calibration_relocation_invalid:{exc.__class__.__name__}")
        checks["calibration_relocation_exact"] = False
    _record(checks, issues, "calibration_relocation_exact")

    return {
        "schema_version": SCHEMA_VERSION,
        "slice": SLICE,
        "status": "PASS" if all(checks.values()) and not issues else "FAIL",
        "canonical_binding": EXPECTED_BINDING,
        "checks": checks,
        "issues": sorted(set(issues)),
        "compatibility_policy": {
            "qwen3_5_4b": "EXPLICIT_ROLLBACK_OR_LEGACY_ONLY",
            "calibrated_9116_binding": "IMMUTABLE_HISTORICAL_SOURCE",
            "runtime_9111_binding": "APPROVED_ENDPOINT_RELOCATION",
        },
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "secret_included": False,
    }


def _record(checks: Mapping[str, bool], issues: list[str], name: str) -> None:
    if not checks[name]:
        issues.append(f"check_failed:{name}")


def _read_env(path: Path, issues: list[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        issues.append(f"environment_defaults_unavailable:{exc.__class__.__name__}")
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _read_compose(path: Path, issues: list[str]) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        issues.append(f"compose_unavailable:{exc.__class__.__name__}")
        return {}
    return value if isinstance(value, dict) else {}


def _service_environment(compose: Mapping[str, Any], service: str) -> Mapping[str, Any]:
    services = compose.get("services")
    if not isinstance(services, Mapping):
        return {}
    definition = services.get(service)
    if not isinstance(definition, Mapping):
        return {}
    environment = definition.get("environment")
    return environment if isinstance(environment, Mapping) else {}


def _write_report(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks")
    passed = (
        sum(value is True for value in checks.values())
        if isinstance(checks, Mapping)
        else 0
    )
    total = len(checks) if isinstance(checks, Mapping) else 0
    return (
        "canonical_generation_provider_binding="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={passed}/{total} model={EXPECTED_BINDING['model_name']} "
        f"port={EXPECTED_BINDING['provider_port']}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = audit_canonical_generation_provider_binding()
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "slice": SLICE,
            "status": "FAIL",
            "checks": {},
            "issues": [f"audit_failed:{exc.__class__.__name__}"],
            "secret_included": False,
        }
    _write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
