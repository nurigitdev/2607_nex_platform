#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "reports/quality/gb2-ca00-s17a-product-runtime.json"

ACTIVE_DEPLOYMENT_PATHS = (
    "deployment/compose/p8-demo.override.yaml",
    "deployment/oci/p8-demo-ae-runtime.Containerfile",
    "scripts/deployment/build_p8_demo_ae_runtime_image.py",
)
PRODUCT_RUNTIME_PATHS = (
    "services/nex-ae-api/nex_ae_api/agent_runtime_process.py",
    "services/nex-ae-api/nex_ae_api/product_runtime_profile.py",
    "services/nex-ae-api/nex_ae_api/product_controlled_skill.py",
)


def audit_product_runtime_deployment(root: Path = ROOT) -> dict[str, Any]:
    issues: list[str] = []
    sources = {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in (*ACTIVE_DEPLOYMENT_PATHS, *PRODUCT_RUNTIME_PATHS)
    }
    for relative in ACTIVE_DEPLOYMENT_PATHS:
        source = sources[relative]
        if "nex_ae_api.demo_runtime" in source:
            issues.append(f"active deployment uses Demo runtime: {relative}")
        if "NEX_AE_DEMO_" in source:
            issues.append(f"active deployment uses Demo AE environment: {relative}")
    for relative in PRODUCT_RUNTIME_PATHS:
        source = sources[relative]
        if "nex_ae_api.demo_runtime" in source or "NEX_AE_DEMO_" in source:
            issues.append(f"product runtime depends on Demo boundary: {relative}")
    controlled_runtime = sources[
        "services/nex-ae-api/nex_ae_api/product_controlled_skill.py"
    ]
    fixture_runtime_tokens = (
        "protected_input",
        "finance_golden_a_activation",
        "authority_profile_path",
        "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH",
    )
    fixture_runtime_use = any(
        token in controlled_runtime for token in fixture_runtime_tokens
    )
    if fixture_runtime_use:
        issues.append("product runtime reads protected fixture-like business input")

    compose = yaml.safe_load(
        sources["deployment/compose/p8-demo.override.yaml"]
    )
    worker = compose["services"]["nex-ae-agent-runtime-worker"]
    expected_command = [
        "python",
        "-m",
        "nex_ae_api.agent_runtime_process",
        "--profile",
        "staging_live",
    ]
    if worker.get("command") != expected_command:
        issues.append("AE worker does not use the canonical product entrypoint")
    worker_environment = worker.get("environment")
    if not isinstance(worker_environment, Mapping):
        issues.append("AE worker environment is unavailable")
    elif str(worker_environment.get("NEX_AE_AGENT_WORKER_EXECUTOR_KINDS") or "").split(
        ","
    ) != [
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
        "P4_CHAT_RAG_COMPATIBILITY",
    ]:
        issues.append("AE worker product executor profile is incomplete")

    container = sources["deployment/oci/p8-demo-ae-runtime.Containerfile"]
    if "COPY --chown=65532:65532 fixtures" in container:
        issues.append("business fixtures are packaged into the product runtime image")
    if "NEX_AE_NSL_BUNDLE_MANIFEST" not in container:
        issues.append("product NSL bundle is not packaged")

    bundle = json.loads(
        (root / "deployment/locks/ae-product-nsl-runtime-bundle.v1.json").read_text(
            encoding="utf-8"
        )
    )
    skill_files = bundle.get("skill", {}).get("files", {})
    if any("fixture" in str(name).lower() for name in skill_files):
        issues.append("product NSL bundle contains a business fixture")
    registry = json.loads(
        (
            root
            / "deployment/environments/ae-product-capability-registry.v1.json"
        ).read_text(encoding="utf-8")
    )
    artifact = registry["registrations"][0]["skill_artifact"]
    if artifact.get("bundle_id") != bundle.get("bundle_id"):
        issues.append("Product Capability Registry bundle identity drift")

    return {
        "schema_version": "gb2_product_runtime_deployment_audit.v1",
        "slice": "GB2-CA00-S17A",
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "entrypoint": "nex_ae_api.agent_runtime_process",
        "executor_profile": "PRODUCT_LOCAL_SKILL_CONTROLLED_WRITE",
        "business_fixture_runtime_use": fixture_runtime_use,
        "business_fixture_allowed_use": "PRE_REQUEST_DATABASE_SEED_ONLY",
        "authoritative_sources": [
            "PRODUCT_CAPABILITY_REGISTRY",
            "AE_POSTGRESQL",
            "OA",
            "WC",
            "EOS",
        ],
        "active_deployment_paths": list(ACTIVE_DEPLOYMENT_PATHS),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "secret_included": False,
    }


def _write_report(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = audit_product_runtime_deployment()
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        result = {
            "schema_version": "gb2_product_runtime_deployment_audit.v1",
            "slice": "GB2-CA00-S17A",
            "status": "FAIL",
            "issues": [str(exc)],
            "secret_included": False,
        }
    _write_report(args.report, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
