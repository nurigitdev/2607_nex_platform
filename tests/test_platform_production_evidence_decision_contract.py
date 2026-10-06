from __future__ import annotations

from pathlib import Path

import run_platform_production_evidence_decision_contract as contract


def test_repository_contract_freezes_production_evidence_decision_rules() -> None:
    result = contract.run_platform_production_evidence_decision_contract()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "requirement_count": 9,
        "evidence_field_count": 20,
        "forbidden_category_count": 13,
        "freshness_class_count": 4,
        "rollback_field_count": 9,
        "decision_gate_count": 10,
        "decision_state_count": 2,
    }
    assert result["decision"] == {
        "raw_private_values_allowed": False,
        "stale_evidence_allowed": False,
        "conditional_go_allowed": False,
        "production_deployment_performed": False,
        "next_slice": "1411",
    }


def test_empty_repository_fails_documentation_and_deployment_checks(
    tmp_path: Path,
) -> None:
    result = contract.run_platform_production_evidence_decision_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == [
        "all_contract_terms_documented",
        "implicit_deployment_forbidden",
    ]
    assert result["decision"]["next_slice"] == "blocked"


def test_privacy_scanner_rejects_raw_values_but_allows_safe_metadata() -> None:
    unsafe = {
        "service": {
            "api-key": "raw",
            "token_digest": "sha256:ok",
            "private_payload_hash": "sha256:ok",
        },
        "items": [{"database_url": "raw"}, "plain"],
    }
    assert contract._forbidden_paths(unsafe) == (
        "$.service.api-key",
        "$.items[0].database_url",
    )
    assert contract._forbidden_paths(contract._safe_sample_evidence()) == ()
    assert contract._sensitive_key("Authorization") is True
    assert contract._sensitive_key("authorization_status") is False


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert contract._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert contract._read_text(source) == "value"

    passing = contract.run_platform_production_evidence_decision_contract()
    assert contract.summary_line(passing) == (
        "platform_production_evidence_decision_contract=pass requirements=9 "
        "fields=20 forbidden=13 freshness=4 rollback=9 gates=10 next=1411"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert contract.summary_line(failing) == (
        "platform_production_evidence_decision_contract=fail issues=1"
    )

    monkeypatch.setattr(
        contract, "run_platform_production_evidence_decision_contract", lambda: passing
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        contract,
        "run_platform_production_evidence_decision_contract",
        lambda: failing,
    )
    assert contract.main([]) == 1
