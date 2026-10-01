#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_mo_mvp_acceptance,
)
from run_mo_mvp_acceptance_evaluator import (  # noqa: E402
    build_passing_evidence,
)


SCHEMA_PATH = "contracts/schemas/service/nex_mo/mvp_acceptance.v1.schema.json"
EXAMPLE_PATH = "contracts/examples/operations/mo_mvp_acceptance.mock_success.json"
NEGATIVE_PATHS = (
    "contracts/tests/negative/operations/mo_mvp_acceptance.raw_evidence_leak.json",
    "contracts/tests/negative/operations/mo_mvp_acceptance.database_url_leak.json",
)
OPENAPI_PATH = "contracts/openapi/nex-mo.openapi.yaml"
ROUTE = "/admin/v1/operations/mvp-acceptance"
COMPONENT = "MoMvpAcceptanceOperationsProjection"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def run_mo_mvp_acceptance_contracts(root: Path = ROOT) -> dict[str, Any]:
    issues: list[str] = []
    checks = {
        "canonical_schema_valid": False,
        "example_valid": False,
        "runtime_projection_valid": False,
        "privacy_negatives_rejected": False,
        "fixtures_indexed": False,
        "openapi_valid": False,
        "openapi_canonical_ref_bound": False,
        "openapi_projection_strict": False,
    }
    try:
        schema = _json(root / SCHEMA_PATH)
        validator = Draft202012Validator(schema)
        Draft202012Validator.check_schema(schema)
        checks["canonical_schema_valid"] = True

        validator.validate(_json(root / EXAMPLE_PATH))
        checks["example_valid"] = True
        runtime = {
            **evaluate_mo_mvp_acceptance(
                build_passing_evidence(),
                now=NOW,
            ),
            "request_trace_id": "b" * 32,
            "evidence_source_status": "COLLECTED",
            "server_selected": True,
        }
        validator.validate(runtime)
        checks["runtime_projection_valid"] = True

        negative_errors = [
            list(validator.iter_errors(_json(root / path)))
            for path in NEGATIVE_PATHS
        ]
        checks["privacy_negatives_rejected"] = all(
            len(errors) == 1 and errors[0].validator == "additionalProperties"
            for errors in negative_errors
        )
        examples = {
            item["path"]
            for item in _json(root / "contracts/examples/index.json")["examples"]
        }
        negatives = {
            item["path"]
            for item in _json(root / "contracts/tests/negative/index.json")[
                "negative_examples"
            ]
        }
        checks["fixtures_indexed"] = (
            EXAMPLE_PATH.removeprefix("contracts/") in examples
            and all(path.removeprefix("contracts/") in negatives for path in NEGATIVE_PATHS)
        )

        openapi = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
        validate(openapi)
        checks["openapi_valid"] = True
        operation = openapi["paths"][ROUTE]["get"]
        component = openapi["components"]["schemas"][COMPONENT]
        response_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        checks["openapi_canonical_ref_bound"] = (
            response_schema == {"$ref": f"#/components/schemas/{COMPONENT}"}
            and component.get("x-nex-canonical-json-schema")
            == SCHEMA_PATH.removeprefix("contracts/")
        )
        checks["openapi_projection_strict"] = (
            set(openapi["paths"][ROUTE]) == {"get"}
            and component.get("additionalProperties") is False
            and openapi["components"]["schemas"][
                "MoMvpAcceptanceGateResult"
            ].get("additionalProperties")
            is False
            and openapi["components"]["schemas"][
                "MoMvpAcceptanceBlocker"
            ].get("additionalProperties")
            is False
        )
    except Exception as exc:
        issues.append(type(exc).__name__)

    failed_checks = [name for name, passed in checks.items() if not passed]
    passed = not failed_checks and not issues
    return {
        "evidence_schema_version": "mo_mvp_acceptance_contracts.v1",
        "slice": "1197",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo.mvp_acceptance.contract_failed",
        "checks": checks,
        "failed_checks": failed_checks,
        "issues": issues,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "positive_fixture_count": 1,
            "negative_fixture_count": len(NEGATIVE_PATHS),
        },
        "next_slice": "1198" if passed else "blocked",
    }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_mvp_acceptance_contracts="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"fixtures={summary.get('positive_fixture_count', 0)}/"
        f"{summary.get('negative_fixture_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_mvp_acceptance_contracts()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
