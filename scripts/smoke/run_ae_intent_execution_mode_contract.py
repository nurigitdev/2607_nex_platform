#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.intent_policy import (  # noqa: E402
    IntentPolicyError,
    resolve_intent_decision,
)


def run_ae_intent_execution_mode_contract() -> dict[str, Any]:
    explicit = resolve_intent_decision(
        {
            "user_message": "요약해줘",
            "generation": {"execution_mode": "GENERAL_ANSWER"},
            "retrieval": {"enabled": True},
        }
    )
    grounded = resolve_intent_decision(
        {"user_message": "What changed?", "retrieval": {"enabled": True}}
    )
    summary = resolve_intent_decision({"user_message": "이 문서를 요약해줘"})
    document = resolve_intent_decision({"user_message": "보고서를 작성해줘"})
    invalid_code = _invalid_mode_code()
    checks = {
        "explicit_mode_wins": explicit["execution_mode"] == "GENERAL_ANSWER",
        "explicit_source_recorded": explicit["decision_source"] == "EXPLICIT",
        "retrieval_promotes_grounded": (
            grounded["execution_mode"] == "GROUNDED_ANSWER"
        ),
        "summary_detected": summary["execution_mode"] == "DOCUMENT_SUMMARY",
        "document_detected": document["execution_mode"] == "DOCUMENT_GENERATION",
        "document_template_required": document["template_required"] is True,
        "versions_are_canonical": all(
            item["intent_decision_schema_version"] == "ae_intent_decision.v1"
            for item in (explicit, grounded, summary, document)
        ),
        "decisions_are_hashed": all(
            len(item["decision_hash"]) == 64
            for item in (explicit, grounded, summary, document)
        ),
        "raw_prompt_excluded": all(
            item["raw_prompt_included"] is False
            for item in (explicit, grounded, summary, document)
        ),
        "invalid_mode_rejected": invalid_code == "ae.execution_mode_unsupported",
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "contract_schema_version": "ae_intent_execution_mode_contract.v1",
        "slice": "1023",
        "requirement": "S103",
        "status": status,
        "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "decisions": {
            "explicit": explicit,
            "grounded": grounded,
            "summary": summary,
            "document": document,
        },
        "remote_provider_required": False,
        "next_slice": "1024",
    }


def _invalid_mode_code() -> str | None:
    try:
        resolve_intent_decision(
            {
                "user_message": "hello",
                "generation": {"execution_mode": "UNSAFE_MODE"},
            }
        )
    except IntentPolicyError as exc:
        return exc.error_code
    return None


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_intent_execution_mode_contract="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_intent_execution_mode_contract()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
