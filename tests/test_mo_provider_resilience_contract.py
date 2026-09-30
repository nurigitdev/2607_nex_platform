from __future__ import annotations

import json
from pathlib import Path

from nex_mo.provider_resilience_contract import (
    build_mo_provider_resilience_contract,
)
import run_mo_provider_resilience_contract as runner


ROOT = Path(__file__).resolve().parents[1]


def _fixture() -> dict:
    return json.loads(
        (
            ROOT
            / "contracts/examples/provider/mo_provider_telemetry_snapshot.mock.json"
        ).read_text(encoding="utf-8")
    )


def test_resilience_contract_matches_canonical_openapi_and_fixture() -> None:
    audit = build_mo_provider_resilience_contract()

    assert audit["status"] == "PASS"
    assert audit["summary"] == {
        "canonical_property_count": 26,
        "openapi_property_count": 26,
        "retry_field_count": 5,
        "runtime_item_count": 1,
        "failed_check_count": 0,
    }


def test_resilience_contract_fails_closed_for_missing_sources(tmp_path: Path) -> None:
    audit = build_mo_provider_resilience_contract(tmp_path)

    assert audit["status"] == "FAIL"
    assert audit["failure_code"] == "mo_provider_resilience_contract_failed"
    assert audit["next_slice"] == "blocked"
    assert audit["summary"]["failed_check_count"] >= 1


def test_resilience_contract_rejects_missing_retry_fields_and_private_keys() -> None:
    payload = _fixture()
    payload["data"][0].pop("retry_count")
    payload["data"][0]["api_key"] = "private"

    audit = build_mo_provider_resilience_contract(telemetry_payload=payload)

    assert audit["status"] == "FAIL"
    assert audit["checks"]["runtime_payload_contract_valid"] is False
    assert audit["checks"]["runtime_retry_fields_complete"] is False
    assert audit["checks"]["private_runtime_keys_absent"] is False


def test_resilience_contract_rejects_non_mapping_runtime_items() -> None:
    payload = _fixture()
    payload["data"] = ["invalid"]
    audit = build_mo_provider_resilience_contract(telemetry_payload=payload)
    assert audit["checks"]["runtime_retry_fields_complete"] is False


def test_resilience_contract_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_resilience_contract()
    assert passing["status"] == "PASS"
    assert "drift=0" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_resilience_contract",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "checks=4/4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_resilience_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
