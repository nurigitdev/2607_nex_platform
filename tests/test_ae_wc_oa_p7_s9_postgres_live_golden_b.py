from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import run_p7_s9_postgres_live_golden_b as smoke

AE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:test-secret@127.0.0.1:5432/nex_wc_test"
OA_URL = "postgresql://nex_oa_user:test-secret@127.0.0.1:5432/nex_oa_test"


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _Client:
    def __init__(self, *, valid_authorization: bool = True) -> None:
        self.posts = 0
        self.gets = 0
        self.valid_authorization = valid_authorization

    def post(self, *_args, **_kwargs):
        self.posts += 1
        return _Response({"membership": {"status": "ACTIVE"}})

    def get(self, *_args, **_kwargs):
        self.gets += 1
        authorization: object = {
            "scopes": ["work:delegate", "work:claim", "work:result:submit"],
            "revision_hash": "a" * 64,
        }
        if not self.valid_authorization:
            authorization = []
        return _Response({"authorization": authorization})


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def _environment() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.AE_DATABASE_ENV: AE_URL,
        smoke.WC_DATABASE_ENV: WC_URL,
        smoke.OA_DATABASE_ENV: OA_URL,
        smoke.NSL_SOURCE_ENV: "/tmp",
    }


def test_s9_is_protected_and_requires_all_exact_test_targets() -> None:
    assert smoke.run_p7_s9_postgres_live_golden_b({})["status"] == "SKIPPED"
    for database_env in (
        smoke.AE_DATABASE_ENV,
        smoke.WC_DATABASE_ENV,
        smoke.OA_DATABASE_ENV,
    ):
        env = _environment()
        env[database_env] = env[database_env].replace("_test", "_dev")
        rejected = smoke.run_p7_s9_postgres_live_golden_b(env)
        assert rejected["failure_code"] == "target_not_allowed"


def test_s9_reports_missing_nsl_and_provider_configuration(monkeypatch) -> None:
    env = _environment()
    del env[smoke.NSL_SOURCE_ENV]
    assert smoke.run_p7_s9_postgres_live_golden_b(env)["failure_code"] == (
        "nsl_source_missing"
    )

    monkeypatch.setattr(
        smoke.p65_s7,
        "_missing_provider_configuration",
        lambda _env: ["NEX_MO_VLLM_API_KEY"],
    )
    assert (
        smoke.run_p7_s9_postgres_live_golden_b(_environment())["failure_code"]
        == "provider_configuration_missing"
    )


def test_s9_composes_three_migrations_and_sanitized_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.p65_s7, "_missing_provider_configuration", lambda _env: []
    )
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    heads = {
        "nex-ae-api": "2405_ae_claimed_planning_source",
        "nex-wc": "1003_wc_work_item_authorization",
        "nex-oa": "1303_oa_mvp_acceptance",
    }
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: SimpleNamespace(
            planned=(heads[service],), applied=(), skipped=(heads[service],)
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_golden_b",
        lambda **_kwargs: {
            "checks": {"deterministic_parent_report_completed": True},
            "provider": {"semantic_stages": ["INTENT", "CONTEXT", "PLAN"]},
            "row_counts": {"golden_agent_execution": 2, "golden_resume": 1},
            "cleanup_counts": {"oa_remaining": 0},
        },
    )
    monkeypatch.setattr(smoke, "_source_revision", lambda: "abc123")

    evidence = smoke.run_p7_s9_postgres_live_golden_b(_environment())

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["actual_remote_provider"] is True
    assert evidence["source_revision"] == "abc123"
    assert evidence["migration_heads"] == heads
    assert "test-secret" not in str(evidence["redacted_database_urls"])
    assert "checks=2/2" in smoke.summary_line(evidence)


def test_s9_marks_failed_acceptance_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.p65_s7, "_missing_provider_configuration", lambda _env: []
    )
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: SimpleNamespace(
            planned=(service,), applied=(), skipped=(service,)
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_golden_b",
        lambda **_kwargs: {"checks": {"golden_b": False}},
    )

    evidence = smoke.run_p7_s9_postgres_live_golden_b(_environment())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "p7_s9_acceptance_failed"


def test_oa_api_source_bootstraps_once_and_reads_each_authorization() -> None:
    client = _Client()
    source = smoke._OaApiAuthorizationSource(client)  # noqa: SLF001

    first = source.effective_authorization(
        tenant_id="tenant-a", subject_id="employee-100"
    )
    second = source.effective_authorization(
        tenant_id="tenant-a", subject_id="employee-100"
    )
    third = source.effective_authorization(
        tenant_id="tenant-a", subject_id="employee-100"
    )

    assert first == second == third
    assert first["active"] is True
    assert client.posts == source.bootstrap_calls == 1
    assert client.gets == source.authorization_calls == 3
    assert source.observed_gates == [
        "work:delegate",
        "work:claim",
        "work:result:submit",
    ]
    assert source.tenant_ids == ("tenant-a",)


def test_oa_api_source_rejects_invalid_authorization_payload() -> None:
    source = smoke._OaApiAuthorizationSource(  # noqa: SLF001
        _Client(valid_authorization=False)
    )
    with pytest.raises(RuntimeError, match="authorization response"):
        source.effective_authorization(tenant_id="tenant-a", subject_id="employee-100")


def test_s9_execution_failure_redacts_all_database_passwords(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.p65_s7, "_missing_provider_configuration", lambda _env: []
    )
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(OA_URL)),
    )

    evidence = smoke.run_p7_s9_postgres_live_golden_b(_environment())

    assert evidence["failure_code"] == "execution_failed"
    assert "test-secret" not in evidence["detail"]


def test_source_revision_has_an_unavailable_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="not a repository"
        ),
    )
    assert smoke._source_revision() == "unavailable"  # noqa: SLF001


def test_golden_b_rejects_unavailable_oa_persistence(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "build_service_app", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            api_engine=None, api_session_factory=None, worker_engine=None
        ),
    )
    with pytest.raises(RuntimeError, match="OA PostgreSQL runtime"):
        smoke._execute_golden_b(  # noqa: SLF001
            urls={"ae": AE_URL, "wc": WC_URL, "oa": OA_URL},
            nsl_source=smoke.ROOT,
            runtime_environ={},
        )


def test_golden_b_disposes_partial_runtime_when_oa_client_start_fails(
    monkeypatch,
) -> None:
    disposed: list[bool] = []
    engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    persistence = SimpleNamespace(
        api_engine=engine, api_session_factory=object(), worker_engine=None
    )

    class _BrokenClient:
        def __enter__(self):
            raise RuntimeError("client startup failed")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(smoke, "build_service_app", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *_args, **_kwargs: persistence,
    )
    monkeypatch.setattr(
        smoke, "build_subject_registry_for_runtime", lambda *_args: object()
    )
    monkeypatch.setattr(
        smoke,
        "build_tenant_membership_registry_for_runtime",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        smoke, "build_authorization_repository_for_runtime", lambda *_args: object()
    )
    monkeypatch.setattr(
        smoke, "OaEffectiveAuthorizationResolver", lambda *_args: object()
    )
    monkeypatch.setattr(smoke, "OaAuthorizationService", lambda *_args: object())
    monkeypatch.setattr(
        smoke, "register_identity_membership_routes", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        smoke, "register_authorization_routes", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(smoke, "TestClient", lambda *_args: _BrokenClient())

    with pytest.raises(RuntimeError, match="client startup"):
        smoke._execute_golden_b(  # noqa: SLF001
            urls={"ae": AE_URL, "wc": WC_URL, "oa": OA_URL},
            nsl_source=smoke.ROOT,
            runtime_environ={},
        )
    assert disposed == [True]


def test_parent_completion_metadata_is_promoted_without_duplicate_check_payloads(
    monkeypatch,
) -> None:
    completed = {
        "checks": {"parent_completed": True},
        "row_counts": {"golden_parent_step_result": 2},
        "claim_generation": 1,
        "prompt_registry_versions": [{"binding_key": "intent", "version": "v1"}],
        "hash_safe_lineage": {"work_item": "sha256:work"},
    }
    monkeypatch.setattr(smoke, "_complete_parent_report", lambda _fixture: completed)
    evidence: dict[str, object] = {}

    result = smoke._capture_parent_completion(  # noqa: SLF001
        {"tenant_id": "tenant-a"}, evidence=evidence
    )

    assert result == completed
    assert evidence == {
        "claim_generation": 1,
        "prompt_registry_versions": [{"binding_key": "intent", "version": "v1"}],
        "hash_safe_lineage": {"work_item": "sha256:work"},
    }


def _patch_parent_completion_dependencies(monkeypatch, *, claims, executions) -> None:
    queue = SimpleNamespace(claim=lambda **_kwargs: next(claims))
    engine = SimpleNamespace(schedule_next=lambda **_kwargs: None)
    worker = SimpleNamespace(run_claim=lambda **_kwargs: next(executions))
    monkeypatch.setattr(smoke, "SqlAlchemyRuntimeJobQueue", lambda *_args: queue)
    monkeypatch.setattr(smoke, "SqlAlchemyMultiStepEngine", lambda *_args: engine)
    monkeypatch.setattr(smoke, "SqlAlchemyWorkItemRepository", lambda *_args: object())
    monkeypatch.setattr(
        smoke, "WorkItemService", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        smoke, "SqlAlchemyDelegationRuntimeRepository", lambda *_args: object()
    )
    monkeypatch.setattr(
        smoke, "SqlAlchemyWaitRegistrationRepository", lambda *_args: object()
    )
    monkeypatch.setattr(
        smoke, "DelegateWorkExecutorDependencies", lambda **_kwargs: object()
    )
    monkeypatch.setattr(smoke, "P7DelegateWorkExecutor", lambda **_kwargs: object())
    monkeypatch.setattr(smoke, "P5DeterministicProjectionExecutor", lambda: object())
    monkeypatch.setattr(smoke, "P5StepExecutorRegistry", lambda *_args: object())
    monkeypatch.setattr(
        smoke, "SqlAlchemyWorkResultResumeSource", lambda *_args: object()
    )
    monkeypatch.setattr(smoke, "P5StepExecutionWorker", lambda **_kwargs: worker)


def _parent_fixture() -> dict[str, object]:
    return {
        "factory": object(),
        "wc_factory": object(),
        "authorization_source": _Authorization(),
        "tenant_id": "tenant-a",
        "parent_execution": {
            "agent_execution_id": "00000000-0000-4000-8000-000000000001"
        },
        "now": "2026-10-19T00:00:00Z",
    }


def test_parent_completion_requires_resume_claim(monkeypatch) -> None:
    _patch_parent_completion_dependencies(
        monkeypatch, claims=iter((None,)), executions=iter(())
    )
    with pytest.raises(RuntimeError, match="resume job"):
        smoke._complete_parent_report(_parent_fixture())  # noqa: SLF001


def test_parent_completion_requires_successful_resume(monkeypatch) -> None:
    claim = SimpleNamespace(job={"job_type": "RESUME_EXECUTION"})
    failed = SimpleNamespace(step_result=None, disposition="TERMINAL")
    _patch_parent_completion_dependencies(
        monkeypatch, claims=iter((claim,)), executions=iter((failed,))
    )
    with pytest.raises(RuntimeError, match="parent resume did not succeed"):
        smoke._complete_parent_report(_parent_fixture())  # noqa: SLF001


def test_parent_completion_requires_report_claim(monkeypatch) -> None:
    resume_claim = SimpleNamespace(job={"job_type": "RESUME_EXECUTION"})
    resumed = SimpleNamespace(
        step_result={"status": "SUCCEEDED"}, disposition="TERMINAL"
    )
    _patch_parent_completion_dependencies(
        monkeypatch,
        claims=iter((resume_claim, None)),
        executions=iter((resumed,)),
    )
    with pytest.raises(RuntimeError, match="parent report"):
        smoke._complete_parent_report(_parent_fixture())  # noqa: SLF001


def test_main_renders_summary_and_propagates_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_p7_s9_postgres_live_golden_b",
        lambda: {"status": "PASS", "checks": {"ok": True}},
    )
    assert smoke.main(["--summary"]) == 0
    assert "golden_b=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_p7_s9_postgres_live_golden_b",
        lambda: {"status": "FAIL", "failure_code": "expected"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "expected"' in capsys.readouterr().out


@pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in (
            smoke.AE_DATABASE_ENV,
            smoke.WC_DATABASE_ENV,
            smoke.OA_DATABASE_ENV,
            smoke.NSL_SOURCE_ENV,
        )
    ),
    reason="AE/WC/OA test databases and admitted NSL source are required",
)
def test_s9_actual_postgres_remote_provider_golden_b_and_zero_residue() -> None:
    evidence = smoke.run_p7_s9_postgres_live_golden_b(
        {**os.environ, smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"]["remaining"] == 0
    assert evidence["cleanup_counts"]["delegate_runtime_remaining"] == 0
    assert evidence["cleanup_counts"]["oa_remaining"] == 0
    assert evidence["claim_generation"] == 1
    assert len(evidence["prompt_registry_versions"]) == 3
    assert set(evidence["hash_safe_lineage"]) == {"work_item", "work_result"}
