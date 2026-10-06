from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from nex_runtime.generation_golden import (
    GENERATION_GOLDEN_EVIDENCE_SCHEMA_VERSION,
    GENERATION_GOLDEN_SCENARIOS,
    build_generation_golden_evidence,
    build_generation_golden_matrix,
    evaluate_generation_golden_evidence,
)
import run_platform_generation_golden_scenarios as runner


ROOT = Path(__file__).resolve().parents[1]


def _record(spec_index: int) -> dict[str, object]:
    spec = GENERATION_GOLDEN_SCENARIOS[spec_index]
    return build_generation_golden_evidence(
        spec.scenario_id,
        checks={name: True for name in spec.required_signals},
        components=("component-b", "component-a", "component-a"),
    )


def _payload() -> dict[str, object]:
    return {
        "production_deployment_approved": False,
        "evidence": [_record(index) for index in range(10)],
    }


def test_matrix_freezes_exact_ten_named_scenarios() -> None:
    matrix = build_generation_golden_matrix()

    assert matrix["execution_mode"] == "deterministic"
    assert matrix["protected_dependencies_required"] is False
    assert [item["scenario_id"] for item in matrix["scenarios"]] == [
        f"GEN-E2E-{index:03d}" for index in range(1, 11)
    ]


def test_builder_normalizes_components_and_fails_incomplete_signals() -> None:
    passing = _record(0)
    incomplete = build_generation_golden_evidence(
        "GEN-E2E-001",
        checks={"general_mode_selected": True},
        components=("nex-ae-api",),
    )

    assert passing["status"] == "PASS"
    assert passing["components"] == ["component-a", "component-b"]
    assert len(passing["evidence_digest"]) == 64
    assert incomplete["status"] == "FAIL"
    with pytest.raises(ValueError, match="unknown generation golden scenario"):
        build_generation_golden_evidence(
            "GEN-E2E-999", checks={}, components=()
        )


def test_complete_deterministic_evidence_passes() -> None:
    result = evaluate_generation_golden_evidence(_payload())

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "required_scenario_count": 10,
        "observed_scenario_count": 10,
        "passed_scenario_count": 10,
        "protected_execution_count": 0,
        "privacy_violation_count": 0,
    }
    assert len(result["evidence"]) == 10


@pytest.mark.parametrize(
    ("change", "condition"),
    [
        ({"evidence_schema_version": "bad"}, "schema_valid"),
        ({"scenario_name": "bad"}, "name_matches"),
        ({"status": "FAIL"}, "status_pass"),
        ({"checks": {"unexpected": True}}, "signals_exact"),
        (
            {
                "checks": {
                    "general_mode_selected": False,
                    "retrieval_skipped": True,
                    "citations_not_claimed": True,
                }
            },
            "signals_pass",
        ),
        ({"deterministic_execution": False}, "deterministic_execution"),
        ({"protected_execution": True}, "protected_execution_absent"),
        ({"private_payload_included": True}, "private_payload_excluded"),
        ({"components": []}, "components_present"),
        ({"evidence_digest": "0" * 64}, "digest_valid"),
    ],
)
def test_scenario_conditions_fail_closed(
    change: dict[str, object],
    condition: str,
) -> None:
    payload = _payload()
    record = payload["evidence"][0]  # type: ignore[index]
    record.update(change)  # type: ignore[union-attr]

    result = evaluate_generation_golden_evidence(payload)

    assert result["status"] == "FAIL"
    assert result["scenario_checks"]["GEN-E2E-001"]["conditions"][condition] is False


def test_inventory_duplicates_privacy_and_release_claim_block() -> None:
    missing = _payload()
    missing["evidence"] = missing["evidence"][:-1]  # type: ignore[index]
    duplicate = _payload()
    duplicate["evidence"].append(deepcopy(duplicate["evidence"][0]))  # type: ignore[union-attr,index]
    private = _payload()
    private["raw_prompt"] = "must-not-pass"
    production = _payload()
    production["production_deployment_approved"] = True

    assert evaluate_generation_golden_evidence(missing)["checks"][
        "scenario_inventory_exact"
    ] is False
    duplicate_result = evaluate_generation_golden_evidence(duplicate)
    assert duplicate_result["checks"]["scenario_ids_unique"] is False
    assert duplicate_result["duplicate_scenario_ids"] == ["GEN-E2E-001"]
    private_result = evaluate_generation_golden_evidence(private)
    assert private_result["checks"]["privacy_safe"] is False
    assert private_result["privacy_violations"] == ["$.raw_prompt"]
    assert evaluate_generation_golden_evidence(production)["checks"][
        "release_candidate_only"
    ] is False


def test_non_sequence_and_malformed_records_are_missing() -> None:
    not_a_list = evaluate_generation_golden_evidence(
        {"production_deployment_approved": False, "evidence": "bad"}
    )
    malformed = evaluate_generation_golden_evidence(
        {
            "production_deployment_approved": False,
            "evidence": [None, {}, {"scenario_id": ""}],
        }
    )

    assert not_a_list["summary"]["observed_scenario_count"] == 0
    assert malformed["summary"]["observed_scenario_count"] == 0
    assert not_a_list["status"] == malformed["status"] == "FAIL"


@pytest.fixture(scope="module")
def golden_result() -> dict[str, object]:
    return runner.run_platform_generation_golden_scenarios(ROOT)


def test_runner_executes_all_ten_scenarios_without_protected_dependencies(
    golden_result: dict[str, object],
) -> None:
    assert golden_result["status"] == "PASS"
    assert golden_result["failed_checks"] == []
    assert golden_result["summary"] == {
        "required_scenario_count": 10,
        "observed_scenario_count": 10,
        "passed_scenario_count": 10,
        "protected_execution_count": 0,
        "privacy_violation_count": 0,
    }
    assert golden_result["decision"] == {
        "mock_or_in_memory_execution": True,
        "actual_postgresql_execution": False,
        "actual_remote_provider_execution": False,
        "actual_browser_execution": False,
        "private_payload_persisted_in_evidence": False,
        "next_slice": "1395",
    }
    assert set(golden_result["source_statuses"].values()) == {"PASS"}


def test_runner_report_and_guardrail_helpers_execute_production_logic() -> None:
    report = runner._run_report_artifact_export(ROOT)
    no_answer = runner._run_no_answer_guardrail()
    mismatch = runner._run_template_prompt_mismatch()
    retry = runner._run_render_retry_plan()

    assert report == {
        "status": "PASS",
        "report_contract_selected": True,
        "md_created": True,
        "docx_created": True,
        "owner_only_links": True,
    }
    assert all(no_answer.values())
    assert all(mismatch.values())
    assert all(retry.values())


def test_runner_helpers_fail_closed_on_invalid_inputs(tmp_path: Path) -> None:
    assert runner._read_json(tmp_path / "missing.json") == {}
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    sequence = tmp_path / "sequence.json"
    sequence.write_text("[]", encoding="utf-8")

    assert runner._read_json(invalid) == {}
    assert runner._read_json(sequence) == {}
    assert runner._mapping(None) == {}
    assert runner._first_mapping(None) == {}
    assert runner._first_mapping([{"id": "first"}]) == {"id": "first"}
    assert runner._nested({"one": {"two": 2}}, "one", "two") == 2
    assert runner._nested({"one": None}, "one", "two") is None
    assert runner._safe_run(lambda: []) == {"status": "FAIL"}

    def fail() -> dict[str, object]:
        raise RuntimeError("private failure")

    assert runner._safe_run(fail) == {
        "status": "FAIL",
        "error_type": "RuntimeError",
    }


def test_runner_summary_and_cli_outputs(
    golden_result: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runner.summary_line(golden_result) == (
        "platform_generation_golden_scenarios=pass scenarios=10/10 "
        "protected=0 privacy=0 next=1395"
    )
    monkeypatch.setattr(
        runner,
        "run_platform_generation_golden_scenarios",
        lambda: golden_result,
    )
    assert runner.main(["--summary"]) == 0
    assert "scenarios=10/10" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = deepcopy(golden_result)
    failed["status"] = "FAIL"
    failed["decision"]["next_slice"] = "blocked"  # type: ignore[index]
    monkeypatch.setattr(
        runner,
        "run_platform_generation_golden_scenarios",
        lambda: failed,
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out


def test_safe_evidence_schema_is_private_payload_free(
    golden_result: dict[str, object],
) -> None:
    serialized = json.dumps(golden_result["evidence"], sort_keys=True)

    assert GENERATION_GOLDEN_EVIDENCE_SCHEMA_VERSION in serialized
    for token in (
        '"raw_prompt":',
        '"source_text":',
        '"generated_text":',
        '"storage_ref":',
        '"provider_endpoint":',
        '"database_url":',
    ):
        assert token not in serialized
