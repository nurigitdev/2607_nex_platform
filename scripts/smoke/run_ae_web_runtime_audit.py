#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
AE_PATH = ROOT / "services" / "nex-ae-api"
sys.path.insert(0, str(AE_PATH))

from nex_ae_api.web_runtime_audit import build_ae_web_runtime_audit  # noqa: E402


def run_ae_web_runtime_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_ae_web_runtime_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "ae_web_runtime_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"readiness={evidence.get('web_readiness', 'UNKNOWN')} "
        f"source={summary.get('source_file_count', 0)} "
        f"tests={summary.get('test_file_count', 0)} "
        f"main_lines={summary.get('main_js_line_count', 0)} "
        f"playwright={summary.get('playwright_script_count', 0)}/"
        f"{summary.get('playwright_test_count', 0)} "
        f"refactors={summary.get('refactor_required_count', 0)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_web_runtime_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
