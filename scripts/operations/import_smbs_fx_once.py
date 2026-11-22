#!/usr/bin/env python3
"""Parse one SMBS USD/KRW publication and optionally admit it through EOS."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "services/_shared"),
    str(ROOT / "domains/mybee"),
]

from mybee_ax.integrations.finance_inputs import (
    HttpEosFinanceInputTransport,
    load_approved_finance_input_bundle,
)
from mybee_ax.integrations.smbs_fx import (
    SMBS_TODAY_URL,
    build_smbs_fx_import_request,
    fetch_smbs_source_once,
    load_smbs_source_file,
    parse_smbs_usd_krw,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-time SMBS USD/KRW source admission through canonical EOS APIs."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-file", type=Path)
    source.add_argument("--url", default=None)
    parser.add_argument("--allow-insecure-http", action="store_true")
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--policy-version", type=int, default=1)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--eos-base-url")
    parser.add_argument(
        "--service-token-env", default="NEX_EOS_FX_IMPORT_SERVICE_TOKEN"
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--report", type=Path)
    return parser


def execute(args: argparse.Namespace) -> dict[str, object]:
    if args.input_file is not None:
        if args.raw_output is not None or args.allow_insecure_http:
            raise ValueError(
                "--raw-output and --allow-insecure-http are URL-mode options"
            )
        source = load_smbs_source_file(args.input_file)
    else:
        if args.raw_output is None:
            raise ValueError("--raw-output is required for URL capture")
        source = fetch_smbs_source_once(
            url=args.url or SMBS_TODAY_URL,
            allow_insecure_http=args.allow_insecure_http,
            raw_output=args.raw_output,
            timeout_seconds=args.timeout_seconds,
        )
    observation = parse_smbs_usd_krw(
        source, published_at=_parse_datetime(args.published_at)
    )
    request = build_smbs_fx_import_request(
        load_approved_finance_input_bundle(ROOT),
        observation,
        tenant_id=args.tenant_id,
        subject_id=args.subject_id,
        company_id=args.company_id,
        policy_id=args.policy_id,
        policy_version=args.policy_version,
    )
    report: dict[str, object] = {
        "status": "DRY_RUN",
        "operation": "FINANCE.FX_RATE.IMPORT",
        "source_sha256": observation.source_sha256,
        "source_uri": observation.source_uri,
        "transport_security": observation.transport_security,
        "rate_date": observation.rate_date.isoformat(),
        "published_rate": format(observation.published_rate, "f"),
        "request": {
            "method": request.method,
            "path": request.path,
            "tenant_id": request.tenant_id,
            "subject_id": request.subject_id,
            "payload": request.payload,
        },
    }
    if args.commit:
        if not args.eos_base_url:
            raise ValueError("--eos-base-url is required with --commit")
        token = os.environ.get(args.service_token_env, "")
        response = HttpEosFinanceInputTransport(
            base_url=args.eos_base_url,
            service_token=token,
            timeout_seconds=args.timeout_seconds,
        ).send(request)
        report["status"] = "IMPORTED"
        report["response"] = dict(response)
    if args.report is not None:
        if not args.report.parent.is_dir():
            raise ValueError("report parent directory does not exist")
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def _parse_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--published-at must include a timezone offset")
    return parsed


def main() -> int:
    args = build_parser().parse_args()
    report = execute(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
