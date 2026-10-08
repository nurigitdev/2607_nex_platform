#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quality"))

from validate_contracts import (
    load_structured_file,
    validate_contract_tree,
    validate_payload,
)

CONTRACT_ROOT = ROOT / "contracts"
CONTRACTS = (
    ("schemas/common/platform_observability_signal.v1.schema.json", "examples/operations/platform_observability_signal.healthy.json", "tests/negative/operations/platform_observability_signal.prompt_leak.json"),
    ("schemas/service/nex_ag/platform_slo_evaluation.v1.schema.json", "examples/operations/ag_platform_slo_evaluation.no_data.json", "tests/negative/operations/ag_platform_slo_evaluation.raw_samples.json"),
    ("schemas/service/nex_ag/platform_alert.v1.schema.json", "examples/operations/ag_platform_alert.firing.json", "tests/negative/operations/ag_platform_alert.private_content.json"),
    ("schemas/service/nex_ag/platform_alert_routing.v1.schema.json", "examples/operations/ag_platform_alert_routing.mock_external.json", "tests/negative/operations/ag_platform_alert_routing.endpoint_leak.json"),
    ("schemas/service/nex_ag/platform_notification_delivery.v1.schema.json", "examples/operations/ag_platform_notification_delivery.mock_accepted.json", "tests/negative/operations/ag_platform_notification_delivery.authorization_leak.json"),
    ("schemas/service/nex_ag/platform_observability_dashboard.v1.schema.json", "examples/operations/ag_platform_observability_dashboard.mock_external.json", "tests/negative/operations/ag_platform_observability_dashboard.database_url.json"),
)
REQUIRED_PATHS = (
    "/admin/v1/observability/dashboard",
    "/admin/v1/observability/slos",
    "/admin/v1/observability/alerts",
    "/admin/v1/observability/notifications",
    "/admin/v1/observability/alerts/{alert_id}/acknowledge",
    "/admin/v1/observability/alerts/{alert_id}/suppress",
)


def run_contract_mock_acceptance() -> dict[str, Any]:
    summary = validate_contract_tree(CONTRACT_ROOT)
    positive_count = 0
    rejected_count = 0
    positives: list[dict[str, Any]] = []
    for schema_path, positive_path, negative_path in CONTRACTS:
        schema = load_structured_file(CONTRACT_ROOT / schema_path)
        positive = load_structured_file(CONTRACT_ROOT / positive_path)
        negative = load_structured_file(CONTRACT_ROOT / negative_path)
        validate_payload(schema, positive)
        positive_count += 1
        positives.append(positive)
        try:
            validate_payload(schema, negative)
        except ValidationError:
            rejected_count += 1

    openapi = load_structured_file(CONTRACT_ROOT / "openapi/nex-ag.openapi.yaml")
    paths = dict(openapi.get("paths") or {})
    delivery = positives[4]
    delivery_result = delivery["results"][0]
    dashboard = positives[5]
    serialized = json.dumps(positives, sort_keys=True).lower()
    checks = {
        "contract_tree_valid": summary.schema_count >= 174,
        "six_positive_examples_valid": positive_count == 6,
        "six_privacy_negatives_rejected": rejected_count == 6,
        "six_openapi_paths_present": all(path in paths for path in REQUIRED_PATHS),
        "all_paths_protected": all(
            operation.get("security") == [{"serviceBearer": []}]
            for path in REQUIRED_PATHS
            for operation in paths[path].values()
        ),
        "dashboard_schema_linked": openapi["components"]["schemas"]["AgPlatformObservabilityDashboard"]["x-nex-canonical-json-schema"].endswith("platform_observability_dashboard.v1.schema.json"),
        "alert_schema_linked": openapi["components"]["schemas"]["AgPlatformAlert"]["x-nex-canonical-json-schema"].endswith("platform_alert.v1.schema.json"),
        "mock_acceptance_explicit": delivery_result["acceptance_status"] == "MOCK_ACCEPTED",
        "mock_not_live_delivery": delivery_result["delivery_state"] == "BLOCKED",
        "external_not_activated": delivery_result["external_activation"] == "EXTERNAL_NOT_ACTIVATED",
        "dashboard_external_not_activated": dashboard["external_activation"] == "EXTERNAL_NOT_ACTIVATED",
        "no_endpoint_material": "http://" not in serialized and "https://" not in serialized,
        "no_authorization_material": "authorization" not in serialized,
        "no_private_content": "private_content" not in serialized and "raw_prompt" not in serialized,
        "metadata_only_markers": all(item.get("private_payload_included") is False for item in positives),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s148_contract_mock_acceptance.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "contract_counts": {
            "schemas": summary.schema_count,
            "examples": summary.example_count,
            "negative_examples": summary.negative_example_count,
            "openapi": summary.openapi_count,
        },
        "external_acceptance": "MOCK_ACCEPTED",
        "external_activation": "EXTERNAL_NOT_ACTIVATED",
        "next_slice": "1482" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    counts = dict(result.get("contract_counts") or {})
    return (
        "s148_contract_mock_acceptance="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"schemas={counts.get('schemas', 0)} "
        f"examples={counts.get('examples', 0)} "
        f"negative={counts.get('negative_examples', 0)} "
        f"openapi={counts.get('openapi', 0)} "
        f"checks={sum(bool(value) for value in result.get('checks', {}).values())}/15 "
        f"acceptance={result.get('external_acceptance', 'unknown')} "
        f"activation={result.get('external_activation', 'unknown')} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_contract_mock_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
