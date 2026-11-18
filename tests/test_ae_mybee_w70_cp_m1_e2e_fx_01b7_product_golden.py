from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import mybee_m1_product_acceptance_support as support
import run_mybee_w70_cp_m1_product_golden_journey as acceptance


def test_product_golden_source_admission_uses_installed_m1_registry() -> None:
    result = acceptance.run_m1_product_golden_journey({}, root=ROOT)

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["executed"] is False
    assert result["product_capability_id"] == "FINANCE.VOUCHER.APPROVE_AND_POST"
    assert result["product_capability_version"] == "1.0.0"
    assert result["platform_integrated"] is True
    assert result["runtime_transition_fixture"] is False
    assert result["manual_domain_transition"] is False
    assert result["installed_process_continuity"] is True
    assert result["non_identical_positive_request_count"] == 2
    assert result["post_request_direct_transition_allowed"] is False
    assert result["isolated_eight_database_schema_required"] is True
    assert support.PROJECT_REFERENCE_RESOLVE_SCOPE in support._OA_SCOPES["requester"]


def test_product_seed_cannot_delete_public_authority_or_bypass_protection() -> None:
    source = Path(support.__file__).read_text(encoding="utf-8")

    assert "cleanup_acceptance_tenant" not in source
    assert 'schema="public"' not in source
    assert "DISABLE TRIGGER" not in source


def test_product_golden_execution_is_protected_and_contains_failures() -> None:
    calls: list[dict[str, str]] = []

    def protected(environ, *, root):
        calls.append(dict(environ))
        assert root == ROOT
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
        }

    skipped = acceptance.run_m1_product_golden_journey(
        {}, execute=True, root=ROOT, protected_runner=protected
    )
    passed = acceptance.run_m1_product_golden_journey(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=protected,
    )
    failed = acceptance.run_m1_product_golden_journey(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("bounded product failure")
        ),
    )

    assert skipped["status"] == "SOURCE_ADMITTED"
    assert passed["status"] == "PASS"
    assert passed["executed"] is True
    assert len(calls) == 1
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["bounded product failure"]
    assert failed["secret_included"] is False
    assert failed["token_value_included"] is False


def test_product_acceptance_baseline_is_typed_hash_bound_and_non_identical() -> None:
    baseline = support.load_acceptance_baseline()
    prompts = tuple(
        support.build_transaction_prompt(baseline, transaction_index=index)
        for index in range(2)
    )

    assert support.baseline_digest(baseline).startswith("sha256:")
    assert len(support.baseline_digest(baseline)) == 71
    assert len(set(prompts)) == 2
    assert all(baseline["company"]["company_code"] in prompt for prompt in prompts)
    assert all(project["project_code"] in prompts[0] for project in baseline["projects"])
    assert "USD 10000.00" in prompts[0]
    assert "USD 12000.00" in prompts[1]


def test_product_live_checks_require_exact_product_outcomes() -> None:
    baseline = support.load_acceptance_baseline()
    database = {
        "execution_count": 2,
        "agent_result_count": 2,
        "result_delivery_count": 2,
        "acknowledged_delivery_count": 2,
        "approval_decision_count": 6,
        "voucher_candidate_count": 2,
        "journal_count": 2,
        "distinct_journal_count": 2,
        "allocation_batch_count": 2,
        "distinct_allocation_batch_count": 2,
        "allocation_line_count": 4,
        "pnl_projection_count": 2,
        "wa_work_asset_count": 2,
        "first_batch_allocated_total": "13502000.0000",
        "first_batch_unallocated_total": "0.0000",
        "first_batch_project_amounts": ["5400800.0000", "8101200.0000"],
    }

    checks = acceptance._live_checks(
        browser={"status": "PASS"}, database=database, baseline=baseline
    )

    assert all(checks.values())
    assert acceptance._live_checks(
        browser={"status": "PASS"},
        database={**database, "journal_count": 3},
        baseline=baseline,
    )["two_immutable_journals"] is False
    assert acceptance._live_checks(
        browser={"status": "PASS"},
        database={
            **database,
            "first_batch_project_amounts": ["8101200.0000", "5400800.0000"],
        },
        baseline=baseline,
    )["first_project_amounts_exact"] is False


def test_product_semantic_calibration_is_exact_revision_scoped() -> None:
    payload = json.loads(
        acceptance._semantic_calibration_json(model_ref="hf:immutable-revision")
    )

    assert [item["semantic_stage"] for item in payload] == [
        "INTENT",
        "CONTEXT",
        "PLAN",
    ]
    assert {item["model_ref"] for item in payload} == {"hf:immutable-revision"}
    assert {item["model_profile"] for item in payload} == {
        acceptance.MODEL_PROFILE
    }


def test_product_browser_failure_summary_is_bounded_and_body_free() -> None:
    summary = acceptance._browser_failure_summary(
        {
            "failure_code": "TimeoutError",
            "observations": {
                "stage": "requester_login",
                "recent_api_responses": [
                    {
                        "route": "auth_session",
                        "status": 401,
                        "body": "must-not-be-projected",
                    }
                ],
            },
        }
    )

    assert summary == (
        "TimeoutError stage=requester_login responses=auth_session:401"
    )
    assert "must-not-be-projected" not in summary


def test_product_semantic_runtime_failure_keeps_only_exception_type() -> None:
    logs = (
        "nex-ae-api | Unexpected semantic candidate admission failure; "
        "exception_type=GenerationResponseError\n"
        "nex-ae-api | protected prompt and token must-not-be-projected\n"
    )

    assert acceptance._semantic_runtime_failure(logs) == "GenerationResponseError"
    assert (
        acceptance._semantic_runtime_failure(
            'nex-ae-api | {"exception_type":"CandidateSchemaError"}'
        )
        == "CandidateSchemaError"
    )
    assert (
        acceptance._semantic_runtime_failure(
            "nex-ae-api-1 | Traceback (most recent call last):\n"
            "nex-ae-api-1 |   protected payload omitted\n"
            "nex-ae-api-1 | TypeError: bounded message\n"
        )
        == "TypeError"
    )
    assert acceptance._semantic_runtime_failure("unrelated logs") == "not_observed"


def test_product_semantic_runtime_failure_summary_is_bounded() -> None:
    assert (
        acceptance._semantic_runtime_failure_summary(
            "first line\nsecret-bearing line\n", returncode=17
        )
        == "not_observed(rc=17,lines=2)"
    )


def test_product_runtime_log_collection_uses_running_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "ps":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="a" * 64 + "\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="exception_type=CandidateSchemaError\n",
            stderr=None,
        )

    monkeypatch.setattr(acceptance.subprocess, "run", run)

    output, returncode = acceptance._collect_ae_runtime_logs({}, root=ROOT)

    assert returncode == 0
    assert output == "exception_type=CandidateSchemaError\n"
    assert calls[0][0:2] == ("docker", "ps")
    assert calls[-1] == ("docker", "logs", "--tail", "2000", "a" * 64)


def test_product_baseline_rejects_duplicate_projects_and_one_transaction(
    tmp_path: Path,
) -> None:
    baseline = support.load_acceptance_baseline()
    baseline["projects"][1]["project_code"] = baseline["projects"][0][
        "project_code"
    ]
    path = tmp_path / "duplicate-project.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(
        support.M1ProductAcceptanceSupportError, match="Project codes"
    ):
        support.load_acceptance_baseline(path)

    baseline = support.load_acceptance_baseline()
    baseline["transactions"] = baseline["transactions"][:1]
    path.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(
        support.M1ProductAcceptanceSupportError, match="two Projects and two transactions"
    ):
        support.load_acceptance_baseline(path)
