from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

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
    assert result["browser_action_timeout_ms"] == 60_000
    assert result["browser_semantic_submit_timeout_ms"] == 180_000
    assert result["browser_result_timeout_ms"] == 900_000
    assert result["browser_process_timeout_seconds"] == 2_340
    assert support.PROJECT_REFERENCE_RESOLVE_SCOPE in support._OA_SCOPES["requester"]
    assert {"approval:read", "approval:decide"}.issubset(support._OA_SCOPES["approver"])
    assert support.M1_APPROVAL_POSITION_TYPE == "TEAM_LEAD"


def test_product_acceptance_approver_role_matches_eos_policy_position() -> None:
    source = Path(support.__file__).read_text(encoding="utf-8")

    assert "ApprovalPolicyStageInput(M1_APPROVAL_POSITION_TYPE)" in source
    assert "[M1_APPROVAL_POSITION_TYPE]" in source
    assert 'ApprovalPolicyStageInput("TEAM_LEAD")' not in source


def test_product_golden_projects_structured_cleanup_failure_evidence() -> None:
    def runner(_env, *, root):
        assert root == ROOT
        raise acceptance.M1ProductGoldenJourneyExecutionError(
            "bounded live failure",
            evidence={
                "database_isolation": {
                    "cleanup": {
                        "dropped_database_count": 8,
                        "residue_service_ids": [],
                        "cleanup_error_types": [],
                        "zero_residue": True,
                    }
                },
                "zero_residue": True,
            },
        )

    result = acceptance.run_m1_product_golden_journey(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=runner,
    )

    assert result["status"] == "FAIL"
    assert result["issues"] == ["bounded live failure"]
    assert result["zero_residue"] is True
    assert (
        result["failure_evidence"]["database_isolation"]["cleanup"][
            "dropped_database_count"
        ]
        == 8
    )


def test_product_cleanup_continues_after_database_owner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def connect(database_url: str, *, autocommit: bool):
        assert autocommit is True
        attempts.append(database_url)
        raise RuntimeError("protected cleanup failure")

    monkeypatch.setattr(acceptance.psycopg, "connect", connect)
    result = acceptance._drop_isolated_database_schemas(
        (
            {
                "service_id": "nex-ae-api",
                "database_url": "postgresql://owner@localhost/ae",
                "schema_name": "m1_01b7_nex_ae_api_0123456789ab",
            },
            {
                "service_id": "nex-wc",
                "database_url": "postgresql://owner@localhost/wc",
                "schema_name": "m1_01b7_nex_wc_0123456789ab",
            },
        )
    )

    assert len(attempts) == 2
    assert result == {
        "schema_version": "mybee_m1_isolated_database_cleanup.v1",
        "dropped_database_count": 0,
        "residue_service_ids": ["nex-ae-api", "nex-wc"],
        "cleanup_error_types": ["RuntimeError"],
        "zero_residue": False,
    }


def test_product_execution_preserves_original_failure_and_cleanup_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handles = (
        {
            "service_id": "nex-ae-api",
            "database_url": "postgresql://owner@localhost/ae",
            "schema_name": "m1_01b7_nex_ae_api_0123456789ab",
        },
    )
    isolation = {
        "handles": handles,
        "evidence": {
            "schema_version": "mybee_m1_isolated_database_set.v1",
            "database_count": 1,
        },
    }
    cleanup = {
        "schema_version": "mybee_m1_isolated_database_cleanup.v1",
        "dropped_database_count": 1,
        "residue_service_ids": [],
        "cleanup_error_types": [],
        "zero_residue": True,
    }
    monkeypatch.setattr(
        acceptance,
        "_prepare_isolated_database_environment",
        lambda env: (dict(env), isolation),
    )
    monkeypatch.setattr(
        acceptance.installed,
        "execute_canonical_platform_acceptance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("authoritative live failure")
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "_drop_isolated_database_schemas",
        lambda actual: cleanup if actual == handles else pytest.fail("wrong handles"),
    )

    with pytest.raises(
        acceptance.M1ProductGoldenJourneyExecutionError,
        match="authoritative live failure",
    ) as captured:
        acceptance.execute_m1_product_golden_journey(
            {
                acceptance.MODEL_REF_ENV: "Qwen3.5-9B",
                acceptance.MODEL_REVISION_ENV: "hf:immutable",
                acceptance.MODEL_DEPLOYMENT_ENV: "dgx-test",
            },
            root=ROOT,
        )

    assert captured.value.evidence["zero_residue"] is True
    assert captured.value.evidence["database_isolation"]["cleanup"] == cleanup


def test_product_seed_cannot_delete_public_authority_or_bypass_protection() -> None:
    source = Path(support.__file__).read_text(encoding="utf-8")

    assert "cleanup_acceptance_tenant" not in source
    assert 'schema="public"' not in source
    assert "DISABLE TRIGGER" not in source


def test_product_seed_uses_scope_compatible_approval_policies(monkeypatch) -> None:
    policies = []

    class Repository:
        def __init__(self, _factory) -> None:
            pass

        def create_policy(self, value) -> None:
            policies.append(value)

    monkeypatch.setattr(support, "SqlAlchemyEosApprovalPolicyRepository", Repository)
    baseline = support.load_acceptance_baseline()

    support._seed_approval_policies(
        object(), baseline, now=datetime(2026, 11, 18, 1, tzinfo=UTC)
    )

    by_type = {value.transaction_type: value for value in policies}
    assert by_type["DOCUMENT_SIGNOFF"].project_id is None
    assert (
        by_type["ACCOUNTING_POSTING"].project_id
        == baseline["projects"][0]["project_id"]
    )


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
    assert all(
        project["project_code"] in prompts[0] for project in baseline["projects"]
    )
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
    assert (
        acceptance._live_checks(
            browser={"status": "PASS"},
            database={**database, "journal_count": 3},
            baseline=baseline,
        )["two_immutable_journals"]
        is False
    )
    assert (
        acceptance._live_checks(
            browser={"status": "PASS"},
            database={
                **database,
                "first_batch_project_amounts": ["8101200.0000", "5400800.0000"],
            },
            baseline=baseline,
        )["first_project_amounts_exact"]
        is False
    )


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
    assert {item["model_profile"] for item in payload} == {acceptance.MODEL_PROFILE}


def test_product_browser_failure_summary_is_bounded_and_body_free() -> None:
    summary = acceptance._browser_failure_summary(
        {
            "failure_code": "TimeoutError",
            "observations": {
                "stage": "requester_login",
                "semantic_stage": "CONTEXT",
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
        "TimeoutError stage=requester_login semantic_stage=CONTEXT "
        "responses=auth_session:401 progress=none"
    )
    assert "must-not-be-projected" not in summary


def test_product_semantic_runtime_failure_keeps_only_exception_type() -> None:
    logs = (
        "nex-ae-api | Unexpected semantic candidate admission failure; "
        "exception_type=GenerationResponseError\n"
        "nex-ae-api | protected prompt and token must-not-be-projected\n"
    )

    assert acceptance._semantic_runtime_failure(
        logs.replace(
            "exception_type=GenerationResponseError",
            "exception_type=GenerationResponseError "
            "error_code=CANDIDATE_PLAN_INVALID "
            "diagnostic_code=CONTEXT_RESOURCE_TYPE_IS_INVALID",
        )
    ) == (
        "GenerationResponseError:CANDIDATE_PLAN_INVALID:"
        "CONTEXT_RESOURCE_TYPE_IS_INVALID"
    )
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


def test_product_wc_delivery_failure_summary_is_bounded() -> None:
    assert (
        acceptance._wc_delivery_failure_summary(
            "HTTP 409 (ae.product_approval_wait_drifted: protected detail)",
            returncode=1,
        )
        == "ae.product_approval_wait_drifted"
    )
    assert (
        acceptance._wc_delivery_failure_summary(
            "ae.business_approval_delivery_failed "
            "(EOS_DOCUMENT_SIGNOFF_NOT_FOUND)",
            returncode=2,
        )
        == "EOS_DOCUMENT_SIGNOFF_NOT_FOUND"
    )
    assert (
        acceptance._wc_delivery_failure_summary(
            '{"detail":"WC approval event delivery failed: '
            'wc.approval_delivery_failed","failure_code":'
            '"wc.event_delivery_process.unavailable"}',
            returncode=2,
        )
        == "wc.approval_delivery_failed"
    )
    assert (
        acceptance._wc_delivery_failure_summary(
            "Traceback\nWcEventDeliveryProcessError: bounded detail",
            returncode=1,
        )
        == "WcEventDeliveryProcessError"
    )


def test_product_runtime_database_failure_summary_is_bounded(tmp_path: Path) -> None:
    database = tmp_path / "runtime-diagnostic.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_agent_execution ("
                "tenant_id TEXT, agent_type TEXT, state TEXT, phase TEXT, "
                "updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_runtime_job_attempt ("
                "tenant_id TEXT, outcome TEXT, error_ref TEXT, started_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_wait_registration (tenant_id TEXT, state TEXT, "
                "wait_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_product_prep_wait_binding (tenant_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_external_event_inbox (tenant_id TEXT, state TEXT, "
                "event_type TEXT, received_at TEXT)"
            )
        )
        connection.execute(
            text("CREATE TABLE ae_product_prep_event_binding (tenant_id TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE ae_runtime_job (tenant_id TEXT, state TEXT, "
                "job_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_product_prep_checkpoint (tenant_id TEXT, "
                "stage TEXT, stage_kind TEXT, created_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "('V101','IA','FAILED','FINALIZE','2026-11-18T00:00:00Z'),"
                "('V101','PA','WAITING_APPROVAL','PLAN_BUILD',"
                "'2026-11-18T00:00:01Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_runtime_job_attempt VALUES "
                "('V101','FAILED','ae.wc_work_item_http_failed',"
                "'2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_wait_registration VALUES "
                "('V101','WAITING','PRODUCT_PREPARATION',"
                "'2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text("INSERT INTO ae_product_prep_wait_binding VALUES ('V101')")
        )
        connection.execute(
            text(
                "INSERT INTO ae_runtime_job VALUES "
                "('V101','DONE','START_EXECUTION','2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_product_prep_checkpoint VALUES "
                "('V101','WAITING_APPROVAL','WAITING',"
                "'2026-11-18T00:00:00Z')"
            )
        )
    engine.dispose()

    assert acceptance._runtime_database_failure_summary(
        f"sqlite+pysqlite:///{database}", tenant_id="V101"
    ) == (
        "executions=IA:FAILED:FINALIZE|PA:WAITING_APPROVAL:PLAN_BUILD,"
        "attempt=FAILED:ae.wc_work_item_http_failed,"
        "waits=1:WAITING:PRODUCT_PREPARATION,wait_bindings=1,"
        "events=0:none,event_bindings=0,jobs=1:DONE:START_EXECUTION,"
        "checkpoints=1:WAITING_APPROVAL:WAITING"
    )
    assert acceptance._diagnostic_token("secret value") == "invalid"


def test_product_wc_database_progress_summary_is_bounded(tmp_path: Path) -> None:
    database = tmp_path / "wc-progress.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE wc_work_item (tenant_id TEXT, state TEXT, "
                "required_agent_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE wc_assignment (tenant_id TEXT, status TEXT, "
                "agent_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE wc_claim (tenant_id TEXT, state TEXT, "
                "lease_expires_at TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE wc_approval_work_item (tenant_id TEXT, state TEXT, "
                "approval_domain TEXT, created_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE wc_event_outbox (tenant_id TEXT, delivery_state TEXT, "
                "event_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE wc_approval_outbox (tenant_id TEXT, "
                "delivery_state TEXT, event_type TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_work_item VALUES "
                "('V101','IN_PROGRESS','PA','2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_assignment VALUES "
                "('V101','ACTIVE','PA','2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_claim VALUES "
                "('V101','EXPIRED','2020-01-01T00:00:00Z',"
                "'2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_approval_work_item VALUES "
                "('V101','PENDING','BUSINESS_FORMAL','2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_event_outbox VALUES "
                "('V101','DELIVERED','WORK_ITEM_CLAIMED','2026-11-18T00:00:00Z')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_approval_outbox VALUES "
                "('V101','RETRY','BUSINESS_FORMAL_DECIDED',"
                "'2026-11-18T00:00:00Z')"
            )
        )
    engine.dispose()

    assert acceptance._wc_database_progress_summary(
        f"sqlite+pysqlite:///{database}", tenant_id="V101"
    ) == (
        "work=IN_PROGRESS:PA,assignment=ACTIVE:PA,claim=EXPIRED:EXPIRED,"
        "approval=PENDING:BUSINESS_FORMAL,outbox=DELIVERED:WORK_ITEM_CLAIMED,"
        "approval_outbox=RETRY:BUSINESS_FORMAL_DECIDED"
    )


def test_product_playwright_timeout_returns_last_bounded_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = tmp_path / "progress.json"
    monkeypatch.setattr(acceptance, "DEFAULT_BROWSER_PROGRESS_REPORT", progress)

    def timeout_run(_arguments, **kwargs):
        progress.write_text(
            json.dumps(
                {
                    "state": "RUNNING",
                    "stage": "transaction_1_approval_and_result",
                    "sequence": 8,
                    "transaction_index": 1,
                    "poll_count": 44,
                    "approval_count": 0,
                    "pending_gate_count": 0,
                    "private": "must-not-be-projected",
                }
            ),
            encoding="utf-8",
        )
        assert kwargs["timeout"] == acceptance.BROWSER_PROCESS_TIMEOUT_SECONDS
        assert kwargs["env"]["NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS"] == "60000"
        assert (
            kwargs["env"]["NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS"] == "180000"
        )
        assert kwargs["env"]["NEX_MYBEE_M1_GOLDEN_RESULT_TIMEOUT_MS"] == "900000"
        raise subprocess.TimeoutExpired(_arguments, kwargs["timeout"])

    monkeypatch.setattr(acceptance.subprocess, "run", timeout_run)
    baseline = {
        "tenant": {"tenant_id": "V101"},
        "principals": {
            "requester": {"employee_id": "8101"},
            "approver": {"employee_id": "8201"},
        },
    }

    result = acceptance._run_playwright(
        {},
        baseline=baseline,
        prompts=("first bounded prompt", "second bounded prompt"),
        requester_password="private-requester",
        approver_password="private-approver",
    )

    assert result["failure_code"] == "PLAYWRIGHT_PROCESS_TIMEOUT"
    assert result["observations"] == {
        "stage": "transaction_1_approval_and_result",
        "progress_state": "RUNNING",
        "progress_sequence": 8,
        "transaction_index": 1,
        "poll_count": 44,
        "approval_count": 0,
        "pending_gate_count": 0,
    }
    assert "must-not-be-projected" not in json.dumps(result)


def test_product_playwright_failure_merges_last_bounded_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = tmp_path / "progress.json"
    monkeypatch.setattr(acceptance, "DEFAULT_BROWSER_PROGRESS_REPORT", progress)

    def failed_run(_arguments, **_kwargs):
        progress.write_text(
            json.dumps(
                {
                    "state": "FAIL",
                    "stage": "transaction_1_approval_and_result",
                    "sequence": 11,
                    "transaction_index": 1,
                    "poll_count": 91,
                    "approval_count": 2,
                    "pending_gate_count": 0,
                    "private": "must-not-be-projected",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=_arguments,
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "FAIL",
                    "failure_code": "ProductResultTimeout",
                    "observations": {
                        "stage": "transaction_1_approval_and_result",
                        "recent_api_responses": [],
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(acceptance.subprocess, "run", failed_run)
    baseline = {
        "tenant": {"tenant_id": "V101"},
        "principals": {
            "requester": {"employee_id": "8101"},
            "approver": {"employee_id": "8201"},
        },
    }

    result = acceptance._run_playwright(
        {},
        baseline=baseline,
        prompts=("first bounded prompt", "second bounded prompt"),
        requester_password="private-requester",
        approver_password="private-approver",
    )

    assert result["failure_code"] == "ProductResultTimeout"
    assert result["observations"]["progress_state"] == "FAIL"
    assert result["observations"]["poll_count"] == 91
    assert result["observations"]["approval_count"] == 2
    assert "must-not-be-projected" not in json.dumps(result)


def test_product_browser_progress_reader_rejects_unbounded_values(
    tmp_path: Path,
) -> None:
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps(
            {
                "state": "unsafe",
                "stage": "secret value",
                "sequence": -1,
                "poll_count": "private",
            }
        ),
        encoding="utf-8",
    )

    assert acceptance._read_browser_progress(progress) == {
        "stage": "invalid",
        "progress_state": "INVALID",
        "progress_sequence": 0,
        "poll_count": 0,
    }


def test_product_runtime_log_collection_uses_running_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
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
    baseline["projects"][1]["project_code"] = baseline["projects"][0]["project_code"]
    path = tmp_path / "duplicate-project.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(support.M1ProductAcceptanceSupportError, match="Project codes"):
        support.load_acceptance_baseline(path)

    baseline = support.load_acceptance_baseline()
    baseline["transactions"] = baseline["transactions"][:1]
    path.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(
        support.M1ProductAcceptanceSupportError,
        match="two Projects and two transactions",
    ):
        support.load_acceptance_baseline(path)
