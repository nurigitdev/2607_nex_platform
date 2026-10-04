from __future__ import annotations

from copy import deepcopy

import pytest

from nex_runtime.platform_trust_evidence import (
    REQUIRED_DENIALS,
    REQUIRED_HOPS,
    evaluate_platform_trust_evidence,
)
import run_platform_trust_evidence as runner


def _payload() -> dict:
    result = runner.sample_platform_trust_evidence()
    return {
        "hops": result["hops"],
        "denials": result["denials"],
        "restart": result["restart"],
        "databases": result["databases"],
    }


def test_complete_trust_evidence_passes_with_safe_projection() -> None:
    result = evaluate_platform_trust_evidence(_payload())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "hop_count": 5,
        "passed_hop_count": 5,
        "denial_count": 4,
        "passed_denial_count": 4,
        "restart_generation_count": 2,
        "database_service_count": 5,
        "cleanup_residue_count": 0,
        "privacy_violation_count": 0,
    }
    assert [item["hop_id"] for item in result["hops"]] == list(REQUIRED_HOPS)
    assert [item["scenario"] for item in result["denials"]] == list(REQUIRED_DENIALS)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["hops"].pop(),
        lambda value: value["hops"][0].update(status_code=503),
        lambda value: value["hops"][0].update(jwks_verified=False),
        lambda value: value["hops"][1].update(owner_claim_authoritative=False),
        lambda value: value["denials"].pop(),
        lambda value: value["denials"][0].update(status_code=200),
        lambda value: value["restart"].update(generation_count=1),
        lambda value: value["restart"].update(user_session_restored=False),
        lambda value: value["databases"].update(service_count=4),
        lambda value: value["databases"].update(cleanup_residue_count=1),
        lambda value: value["databases"].update(temporary_key_residue_count=1),
    ],
)
def test_trust_evidence_fails_closed_for_incomplete_proof(mutation) -> None:
    payload = _payload()
    mutation(payload)

    result = evaluate_platform_trust_evidence(payload)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]


@pytest.mark.parametrize(
    ("path", "value", "secret_value"),
    [
        (("password",), "password-material", "password-material"),
        (("nested", "client_secret"), "client-material", "client-material"),
        (("nested", "raw_token"), "header.payload.signature", "header.payload.signature"),
        (("items",), [{"session_id": "private-session"}], "private-session"),
    ],
)
def test_trust_evidence_rejects_sensitive_fields(path, value, secret_value) -> None:
    payload = _payload()
    if len(path) == 1:
        payload[path[0]] = value
    else:
        payload[path[0]] = {path[1]: value}

    result = evaluate_platform_trust_evidence(payload)

    assert result["status"] == "FAIL"
    assert result["checks"]["privacy_safe"] is False
    assert result["privacy_violations"]
    assert secret_value not in str(result)


def test_evaluator_handles_malformed_collections_and_duplicate_ids() -> None:
    malformed = evaluate_platform_trust_evidence(
        {"hops": "bad", "denials": None, "restart": [], "databases": []}
    )
    duplicate = _payload()
    duplicate["hops"].append(deepcopy(duplicate["hops"][0]))

    assert malformed["status"] == "FAIL"
    assert evaluate_platform_trust_evidence(duplicate)["status"] == "PASS"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.sample_platform_trust_evidence()
    assert runner.summary_line(passing) == (
        "platform_trust_evidence=pass hops=5/5 denials=4/4 restarts=2 databases=5 next=1337"
    )
    assert "fail checks=1 privacy=1" in runner.summary_line(
        {"status": "FAIL", "failed_checks": ["privacy_safe"], "summary": {"privacy_violation_count": 1}}
    )

    monkeypatch.setattr(runner, "sample_platform_trust_evidence", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1337" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(runner, "sample_platform_trust_evidence", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1
