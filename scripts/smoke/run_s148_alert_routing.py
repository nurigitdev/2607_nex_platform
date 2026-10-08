#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_ag.platform_alerting import AlertRoutingPolicy, AlertRule, apply_slo_evaluation, route_alert


def run_alert_routing() -> dict[str, Any]:
    rule = AlertRule(
        rule_id="rule:nex-mo:provider-latency",
        policy_id="slo:nex-mo:provider-latency",
        service_id="nex-mo",
        minimum_consecutive_failures=2,
        grouping_window_seconds=300,
    )
    evaluation = {
        "policy_id": rule.policy_id,
        "service_id": rule.service_id,
        "status": "BREACHED",
        "reason_code": "SLO_CRITICAL_BURN",
        "accountable_owner": "model-ops",
        "runbook_ref": "runbook:nex-mo:provider-latency",
    }
    pending = apply_slo_evaluation(rule, evaluation, evaluated_at="2026-10-08T01:00:00Z")
    assert pending is not None
    firing = apply_slo_evaluation(
        rule, evaluation, previous=pending, evaluated_at="2026-10-08T01:00:10Z"
    )
    assert firing is not None
    policies = {
        "local_only": AlertRoutingPolicy("local_only", "test", "ag-local"),
        "private_network": AlertRoutingPolicy(
            "private_network", "test", "ag-local", "incident-private"
        ),
        "internet_connected": AlertRoutingPolicy(
            "internet_connected", "test", "ag-local"
        ),
    }
    decisions = {name: route_alert(firing, policy) for name, policy in policies.items()}
    checks = {
        "debounce_promotes_firing": pending.state == "PENDING" and firing.state == "FIRING",
        "critical_severity": firing.severity == "CRITICAL",
        "local_route_always_present": all(
            any(intent["channel"] == "LOCAL" for intent in decision["intents"])
            for decision in decisions.values()
        ),
        "private_route_activated": decisions["private_network"]["external_activation"]
        == "EXTERNAL_ACTIVATED",
        "internet_route_honest": decisions["internet_connected"]["external_activation"]
        == "EXTERNAL_NOT_ACTIVATED",
        "required_external_blocks": decisions["internet_connected"]["routing_status"] == "BLOCKED",
        "idempotency_hashes_present": all(
            intent["idempotency_key_hash"].startswith("sha256:")
            for decision in decisions.values()
            for intent in decision["intents"]
        ),
        "private_payload_absent": all(
            decision["private_payload_included"] is False for decision in decisions.values()
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s148_alert_routing.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "decision_count": len(decisions),
            "intent_count": sum(len(item["intents"]) for item in decisions.values()),
            "blocked_count": sum(item["routing_status"] == "BLOCKED" for item in decisions.values()),
            "external_activated_count": sum(
                item["external_activation"] == "EXTERNAL_ACTIVATED" for item in decisions.values()
            ),
        },
        "next_slice": "1477" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_alert_routing="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"decisions={summary.get('decision_count', 0)} "
        f"intents={summary.get('intent_count', 0)} "
        f"blocked={summary.get('blocked_count', 0)} "
        f"checks={sum(bool(value) for value in dict(result.get('checks') or {}).values())}/8 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_alert_routing()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
