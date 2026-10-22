from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from nex_eos import parse_create_voucher_draft_command
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref

ROOT = Path(__file__).resolve().parents[1]
WHEEL = (
    ROOT
    / "reports/deployment/p8-nsl-v0.2-wheel"
    / "nex_skill_language-0.2.0-py3-none-any.whl"
)
SMOKE_ENABLED = os.getenv("NEX_P8_S57A_ACTUAL_WHEEL_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not WHEEL.is_file(),
    reason="Protected P8-S57A actual-wheel hash smoke is disabled",
)


def test_actual_nsl_v02_wheel_and_eos_share_golden_a_payload_hash() -> None:
    command = json.loads(
        (
            ROOT
            / "contracts/examples/service/eos_create_voucher_draft_command.golden_a.json"
        ).read_text(encoding="utf-8")
    )
    business_payload = parse_create_voucher_draft_command(command).business_payload()
    platform_hash = nsl_write_payload_hash_ref(business_payload)
    completed = subprocess.run(
        [sys.executable, "-c", _WHEEL_PROBE, str(WHEEL)],
        input=json.dumps(business_payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["package_version"] == "0.2.0"
    assert evidence["origin"].startswith(str(WHEEL))
    assert evidence["payload_hash"] == platform_hash == command["payload_hash"]


_WHEEL_PROBE = r"""
import importlib.metadata
import json
import sys

sys.path.insert(0, sys.argv[1])
import nsl
from nsl.api import compute_payload_hash
from nsl.core import STRING, ValueEnvelope

payload = json.load(sys.stdin)
arguments = {
    key: ValueEnvelope.complete(value, STRING)
    for key, value in payload.items()
}
print(json.dumps({
    "package_version": importlib.metadata.version("nex-skill-language"),
    "origin": nsl.__file__,
    "payload_hash": str(compute_payload_hash(arguments)),
}))
"""
