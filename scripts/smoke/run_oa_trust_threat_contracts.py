#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.trust_threat_policy import (  # noqa: E402
    build_trust_threat_evidence,
    evidence_privacy_violations,
)


def run_oa_trust_threat_contracts(root: Path = ROOT) -> dict[str, Any]:
    schema = _load_json(
        root
        / "contracts/schemas/service/nex_oa/trust_threat_evidence.v1.schema.json"
    )
    example = _load_json(
        root / "contracts/examples/auth/oa_trust_threat_evidence.pass.json"
    )
    negative = _load_json(
        root
        / "contracts/tests/negative/auth/oa_trust_threat_evidence.raw_token.json"
    )
    generated = build_trust_threat_evidence(
        evaluated_at="2026-10-03T12:00:00Z"
    )
    validator = Draft202012Validator(schema)
    example_errors = list(validator.iter_errors(example))
    generated_errors = list(validator.iter_errors(generated))
    negative_rejected = False
    try:
        validator.validate(negative)
    except ValidationError:
        negative_rejected = True
    checks = {
        "schema_is_valid": not list(Draft202012Validator.check_schema(schema) or []),
        "canonical_example_valid": not example_errors,
        "generated_evidence_valid": not generated_errors,
        "raw_token_negative_rejected": negative_rejected,
        "canonical_example_privacy_safe": (
            evidence_privacy_violations(example) == ()
        ),
        "generated_evidence_privacy_safe": (
            evidence_privacy_violations(generated) == ()
        ),
    }
    passed = all(checks.values())
    return {
        "contract_evidence_schema_version": "oa_trust_threat_contracts.v1",
        "slice": "1249",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_trust_threat_contracts_failed",
        "threat_count": len(generated["threats"]),
        "privacy_violation_count": len(evidence_privacy_violations(generated)),
        "checks": checks,
        "next_slice": "1250",
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_trust_threat_contracts="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"threats={evidence.get('threat_count')} "
        f"privacy_violations={evidence.get('privacy_violation_count')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_trust_threat_contracts()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
