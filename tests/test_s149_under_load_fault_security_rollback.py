from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from nex_runtime.preproduction_live_workload import build_protected_live_soak_profile
from nex_runtime.preproduction_load import OperationOutcome
from nex_runtime.preproduction_workload import admit_workload_profile
import run_s149_under_load_fault_security_rollback as smoke


RC = "rc:s149:under-load-test"
RELEASE_DIGEST = "sha256:" + "a" * 64


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_CX_TEST_DATABASE_URL": "postgresql://user:private-db@localhost/test",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
        "NEX_MO_VLLM_BASE_URL": "http://private-provider.example:9111",
    }


def _predecessor() -> dict[str, object]:
    return {
        "evidence_schema_version": "s149_release_bound_target_workload.v1",
        "requirement": "S149",
        "slice": "1491",
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": RELEASE_DIGEST,
        },
    }


def _write_predecessor(path: Path, value: object | None = None) -> None:
    path.write_text(json.dumps(_predecessor() if value is None else value))


def _shadow(_env, _admitted, _plan) -> dict[str, object]:
    time.sleep(0.05)
    return {
        "status": "PASS",
        "elapsed_seconds": 179.9,
        "load_result": {
            "status": "PASS",
            "metrics": {
                "request_count": smoke.SHADOW_REQUEST_COUNT,
                "success_count": smoke.SHADOW_REQUEST_COUNT,
                "error_count": 0,
                "error_rate": 0.0,
                "p95_latency_ms": 20.0,
                "throughput_rps": 8.0,
                "max_saturation_ratio": 0.4,
                "peak_active": 4,
                "duplicate_side_effect_count": 0,
                "isolation_violation_count": 0,
            },
        },
        "statistics": {
            "operation_counts": dict(smoke.SHADOW_OPERATION_COUNTS),
            "operation_outcome_counts": {
                name: {
                    "SUCCESS": count,
                    "ERROR": 0,
                    "TIMEOUT": 0,
                    "DENIED": 0,
                }
                for name, count in smoke.SHADOW_OPERATION_COUNTS.items()
            },
            "provider_call_counts": {
                "embedding": 90,
                "reranking": 90,
                "generation": 6,
            },
            "generation_reasoning_mode": "disabled",
        },
        "cleanup": {"status": "PASS", "residue_count": 0},
    }


def _faults(_env, admitted) -> dict[str, object]:
    return {
        "status": "PASS",
        "fault_plan_digest": "b" * 64,
        "evaluation": {
            "status": "PASS",
            "checks": {"zero_data_loss": True, "zero_isolation_violations": True},
            "summary": {
                "scenario_count": 8,
                "recovered_count": 8,
                "residue_count": 0,
            },
        },
        "injected_outcome_counts": {"ERROR": 6, "DENIED": 2},
        "recovery_outcome_counts": {"SUCCESS": 8},
        "cleanup": {"status": "PASS", "residue_count": 0},
        "release_candidate_id": admitted["release_candidate_id"],
    }


def _trust(_env, _path) -> dict[str, object]:
    return {
        "status": "PASS",
        "release_set_digest": RELEASE_DIGEST,
        "decision": {
            "protected_acceptance_passed": True,
            "production_deployment_approved": False,
        },
    }


def _storage(_env, _path) -> dict[str, object]:
    return {
        "status": "PASS",
        "rustfs": {"restart_recovery_verified": True},
        "cleanup": {"status": "PASS"},
        "decision": {"production_deployment_approved": False},
    }


def _providers(_env, _path) -> dict[str, object]:
    return {
        "status": "PASS",
        "summary": {
            "live_provider_count": 3,
            "runtime_ready_count": 3,
            "generation_reasoning_mode": "disabled",
        },
        "cleanup": {"residue": 0},
    }


def _run(tmp_path: Path, **overrides: object) -> dict[str, object]:
    predecessor = tmp_path / "predecessor.json"
    _write_predecessor(predecessor)
    passing = lambda: {"status": "PASS"}
    return smoke.run_s149_under_load_acceptance(
        _env(),
        execute=True,
        predecessor_report=predecessor,
        report_path=tmp_path / "report.json",
        shadow_executor=overrides.get("shadow_executor", _shadow),  # type: ignore[arg-type]
        fault_executor=overrides.get("fault_executor", _faults),  # type: ignore[arg-type]
        trust_runner=overrides.get("trust_runner", _trust),  # type: ignore[arg-type]
        storage_runner=overrides.get("storage_runner", _storage),  # type: ignore[arg-type]
        provider_runner=overrides.get("provider_runner", _providers),  # type: ignore[arg-type]
        deterministic_fault_runner=overrides.get("deterministic_fault_runner", passing),  # type: ignore[arg-type]
        security_runner=overrides.get("security_runner", passing),  # type: ignore[arg-type]
        rollback_runner=overrides.get("rollback_runner", passing),  # type: ignore[arg-type]
    )


class _Runtime:
    def __init__(self, *, failing_operation: str | None = None) -> None:
        self.failing_operation = failing_operation
        self.requests = []
        self.closed = False

    def __call__(self, request):
        self.requests.append(request)
        if request.operation_id == self.failing_operation:
            return OperationOutcome("ERROR", "failed", 0.0)
        return OperationOutcome("SUCCESS", "completed", 0.0)

    def cleanup(self):
        return {"status": "PASS", "residue_count": 0}

    def statistics(self):
        return {"request_count": len(self.requests)}

    def close(self):
        self.closed = True


def test_acceptance_requires_opt_in_and_test_profile() -> None:
    skipped = smoke.run_s149_under_load_acceptance({})
    wrong = smoke.run_s149_under_load_acceptance(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "staging"},
        execute=True,
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in skipped["skip_reason"]
    assert wrong["failure_code"] == "profile_not_allowed"


def test_shadow_plan_has_exact_interleaved_mix() -> None:
    admitted = admit_workload_profile(
        build_protected_live_soak_profile(RC),
        expected_release_candidate_id=RC,
    )
    plan = smoke._build_shadow_plan(admitted)

    assert len(plan) == smoke.SHADOW_REQUEST_COUNT
    assert plan[0].scheduled_offset_seconds == 0.0
    assert plan[-1].scheduled_offset_seconds == pytest.approx(179.875)
    assert plan[0].request_id.startswith("shadow:")


def test_shadow_plan_rejects_operation_mix_drift(monkeypatch) -> None:
    admitted = admit_workload_profile(
        build_protected_live_soak_profile(RC),
        expected_release_candidate_id=RC,
    )
    drifted = list(smoke.build_protected_live_load_plan(admitted))
    drifted[0] = smoke.LoadRequest(
        request_id=drifted[0].request_id,
        operation_id="grounded_generation",
        scheduled_offset_seconds=drifted[0].scheduled_offset_seconds,
    )
    monkeypatch.setattr(
        smoke,
        "build_protected_live_load_plan",
        lambda _admitted: tuple(drifted),
    )

    with pytest.raises(ValueError, match="operation mix drift"):
        smoke._build_shadow_plan(admitted)


def test_acceptance_passes_and_writes_redacted_metadata(tmp_path: Path) -> None:
    result = _run(tmp_path)
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["release_binding"]["release_candidate_id"] == RC
    assert result["faults"]["summary"]["recovered_count"] == 8
    assert result["next_slice"] == "1493"
    assert "private-provider-key" not in serialized
    assert "private-provider.example" not in serialized
    assert json.loads((tmp_path / "report.json").read_text()) == result


@pytest.mark.parametrize(
    ("override", "failed_check"),
    [
        ({"shadow_executor": lambda *_args: {**_shadow(*_args), "status": "FAIL"}}, "actual_shadow_load_passed"),
        (
            {
                "shadow_executor": lambda *_args: _mutated_shadow(
                    lambda value: value["load_result"]["metrics"].update(request_count=1)
                )
            },
            "shadow_request_and_mix_exact",
        ),
        (
            {
                "shadow_executor": lambda *_args: _mutated_shadow(
                    lambda value: value["statistics"]["operation_outcome_counts"][
                        "grounded_generation"
                    ].update(SUCCESS=5, ERROR=1)
                )
            },
            "shadow_provider_operations_succeeded",
        ),
        (
            {
                "shadow_executor": lambda *_args: _mutated_shadow(
                    lambda value: value["statistics"].update(
                        generation_reasoning_mode="provider_default"
                    )
                )
            },
            "generation_reasoning_disabled",
        ),
        ({"fault_executor": lambda *_args: {**_faults(*_args), "status": "FAIL"}}, "eight_client_faults_recovered"),
        ({"deterministic_fault_runner": lambda: {"status": "FAIL"}}, "deterministic_fault_contract_passed"),
        ({"security_runner": lambda: {"status": "FAIL"}}, "security_privacy_under_load_passed"),
        ({"rollback_runner": lambda: {"status": "FAIL"}}, "rollback_under_load_passed"),
        ({"storage_runner": lambda *_args: {"status": "FAIL"}}, "object_storage_restart_and_isolation_passed"),
        ({"provider_runner": lambda *_args: {"status": "FAIL"}}, "provider_recovery_passed"),
        (
            {"trust_runner": lambda *_args: {**_trust(*_args), "release_set_digest": "sha256:" + "f" * 64}},
            "release_digest_preserved",
        ),
    ],
)
def test_acceptance_fails_closed_for_source_drift(
    tmp_path: Path, override: dict[str, object], failed_check: str
) -> None:
    result = _run(tmp_path, **override)

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["next_slice"] == "blocked"


def _mutated_shadow(mutation) -> dict[str, object]:
    value = deepcopy(_shadow(None, None, None))
    mutation(value)
    return value


def test_client_fault_matrix_recovers_all_scenarios_and_closes_runtime() -> None:
    admitted = admit_workload_profile(
        build_protected_live_soak_profile(RC),
        expected_release_candidate_id=RC,
    )
    runtime = _Runtime()

    result = smoke._execute_client_fault_matrix(
        {},
        admitted,
        runtime_factory=lambda _env: runtime,
    )

    assert result["status"] == "PASS"
    assert result["evaluation"]["summary"]["recovered_count"] == 8
    assert result["injected_outcome_counts"] == {"ERROR": 6, "DENIED": 2}
    assert result["recovery_outcome_counts"] == {"SUCCESS": 8}
    assert len(runtime.requests) == 8
    assert runtime.closed is True


def test_client_fault_matrix_records_failed_recovery() -> None:
    admitted = admit_workload_profile(
        build_protected_live_soak_profile(RC),
        expected_release_candidate_id=RC,
    )
    runtime = _Runtime(failing_operation="readiness_probe")

    result = smoke._execute_client_fault_matrix(
        {},
        admitted,
        runtime_factory=lambda _env: runtime,
    )

    assert result["status"] == "FAIL"
    assert result["evaluation"]["summary"]["recovered_count"] == 7
    assert result["recovery_outcome_counts"] == {"SUCCESS": 7, "ERROR": 1}
    assert runtime.closed is True


def test_default_fault_runtime_builds_all_service_engines(monkeypatch) -> None:
    built: list[tuple[str, str]] = []
    engines = object()
    runtime = object()
    monkeypatch.setattr(
        smoke.target_workload,
        "_build_service_engine",
        lambda service_id, database_env, _env: built.append(
            (service_id, database_env)
        )
        or f"engine:{service_id}",
    )
    monkeypatch.setattr(
        smoke.target_workload,
        "ProtectedLiveOperationRuntime",
        lambda actual_engines, env: runtime
        if actual_engines == {
            service_id: f"engine:{service_id}"
            for service_id in smoke.target_workload.DATABASE_TARGETS
        }
        and env == {"marker": "value"}
        else engines,
    )

    result = smoke._build_fault_runtime({"marker": "value"})

    assert result is runtime
    assert built == list(smoke.target_workload.DATABASE_TARGETS.items())


def test_injected_outcome_distinguishes_denial_from_error() -> None:
    denied = smoke._injected_outcome("edge_or_trust_degradation")
    failed = smoke._injected_outcome("provider_degradation")

    assert (denied.status, denied.reason_code) == ("DENIED", "fault_injected")
    assert (failed.status, failed.reason_code) == ("ERROR", "fault_injected")


@pytest.mark.parametrize(
    "predecessor",
    [
        {"slice": "1491", "status": "FAIL", "release_binding": {}},
        {
            "slice": "wrong",
            "status": "PASS",
            "release_binding": {
                "release_candidate_id": RC,
                "release_set_digest": RELEASE_DIGEST,
            },
        },
        {
            "slice": "1491",
            "status": "PASS",
            "release_binding": {
                "release_candidate_id": "wrong",
                "release_set_digest": RELEASE_DIGEST,
            },
        },
        {
            "slice": "1491",
            "status": "PASS",
            "release_binding": {
                "release_candidate_id": RC,
                "release_set_digest": "bad",
            },
        },
    ],
)
def test_invalid_predecessor_fails_closed(tmp_path: Path, predecessor: object) -> None:
    path = tmp_path / "predecessor.json"
    _write_predecessor(path, predecessor)

    result = smoke.run_s149_under_load_acceptance(
        _env(),
        execute=True,
        predecessor_report=path,
        report_path=tmp_path / "report.json",
    )

    assert result["failure_code"] == "under_load_acceptance_execution_failed"
    assert result["diagnostics"] == {"exception_type": "ValueError"}


def _oci_build_report() -> dict[str, object]:
    return {
        "image_build": {
            "status": "RELEASE_SET_BUILT",
            "source_revision": "b" * 40,
            "release_set_digest": RELEASE_DIGEST,
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "image_reference": f"local/{artifact_id}@sha256:" + "c" * 64,
                }
                for artifact_id in smoke.staging.IMAGE_ENV_BY_ARTIFACT
            ],
        }
    }


def test_pinned_release_environment_admits_non_runtime_changes(
    monkeypatch, tmp_path: Path
) -> None:
    report = tmp_path / "oci.json"
    report.write_text(json.dumps(_oci_build_report()))
    monkeypatch.setattr(smoke, "_git", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        smoke,
        "_git_output",
        lambda _root, *args: (
            "docs/slices/1492.md\nscripts/smoke/run_s149.py\ntests/test_s149.py"
            if args[0] == "diff"
            else ""
        ),
    )

    environment, digest, admission = smoke._load_pinned_release_environment(
        _predecessor(),
        root=tmp_path,
        oci_report_path=report,
    )

    assert set(environment) == set(smoke.staging.IMAGE_ENV_BY_ARTIFACT.values())
    assert digest == RELEASE_DIGEST
    assert admission["status"] == "ADMITTED"
    assert admission["non_runtime_change_count"] == 3


def test_pinned_release_environment_admits_exact_build_revision(
    monkeypatch, tmp_path: Path
) -> None:
    report = tmp_path / "oci.json"
    report.write_text(json.dumps(_oci_build_report()))
    monkeypatch.setattr(smoke, "_git", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(smoke, "_git_output", lambda _root, *args: "")

    _, digest, admission = smoke._load_pinned_release_environment(
        _predecessor(),
        root=tmp_path,
        oci_report_path=report,
    )

    assert digest == RELEASE_DIGEST
    assert admission["status"] == "ADMITTED"
    assert admission["non_runtime_change_count"] == 0


@pytest.mark.parametrize(
    "failure_case",
    [
        "not_built",
        "digest_drift",
        "bad_revision",
        "not_ancestor",
        "runtime_change",
        "dirty_worktree",
        "invalid_artifacts",
        "artifact_coverage",
        "mutable_reference",
    ],
)
def test_pinned_release_environment_fails_closed(
    monkeypatch, tmp_path: Path, failure_case: str
) -> None:
    value = _oci_build_report()
    image_build = value["image_build"]
    assert isinstance(image_build, dict)
    predecessor = _predecessor()
    ancestor_status = 0
    changed = "docs/slices/1492.md"
    dirty = ""
    if failure_case == "not_built":
        image_build["status"] = "FAILED"
    elif failure_case == "digest_drift":
        image_build["release_set_digest"] = "sha256:" + "f" * 64
    elif failure_case == "bad_revision":
        image_build["source_revision"] = "bad"
    elif failure_case == "not_ancestor":
        ancestor_status = 1
    elif failure_case == "runtime_change":
        changed = "services/nex-oa/main.py"
    elif failure_case == "dirty_worktree":
        dirty = " M services/nex-oa/main.py"
    elif failure_case == "invalid_artifacts":
        image_build["artifacts"] = None
    elif failure_case == "artifact_coverage":
        image_build["artifacts"] = image_build["artifacts"][:-1]
    elif failure_case == "mutable_reference":
        image_build["artifacts"][0]["image_reference"] = "local/mutable:latest"
    report = tmp_path / "oci.json"
    report.write_text(json.dumps(value))
    monkeypatch.setattr(
        smoke,
        "_git",
        lambda *_args, **_kwargs: ancestor_status,
    )
    monkeypatch.setattr(
        smoke,
        "_git_output",
        lambda _root, *args: changed if args[0] == "diff" else dirty,
    )

    with pytest.raises(ValueError):
        smoke._load_pinned_release_environment(
            predecessor,
            root=tmp_path,
            oci_report_path=report,
        )


def test_git_metadata_helpers_fail_closed(monkeypatch, tmp_path: Path) -> None:
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout=" clean \n"),
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout=" value \n"),
            SimpleNamespace(returncode=1, stdout=""),
        )
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    assert smoke._git(tmp_path, "status") == 0
    with pytest.raises(ValueError, match="git metadata"):
        smoke._git(tmp_path, "status")
    assert smoke._git(tmp_path, "status", check=False) == 1
    assert smoke._git_output(tmp_path, "status") == "value"
    with pytest.raises(ValueError, match="git metadata"):
        smoke._git_output(tmp_path, "status")


def test_acceptance_uses_pinned_release_for_default_trust_runner(
    monkeypatch, tmp_path: Path
) -> None:
    predecessor = tmp_path / "predecessor.json"
    _write_predecessor(predecessor)
    pinned_images = {"NEX_OA_RUNTIME_IMAGE": "oa@sha256:" + "d" * 64}
    monkeypatch.setattr(
        smoke,
        "_load_pinned_release_environment",
        lambda _predecessor: (
            pinned_images,
            RELEASE_DIGEST,
            {
                "status": "ADMITTED",
                "source_revision": "b" * 40,
                "release_set_digest": RELEASE_DIGEST,
                "non_runtime_change_count": 1,
                "non_runtime_change_digest": "sha256:" + "e" * 64,
            },
        ),
    )

    def run_trust(_env, _path, **kwargs):
        assert kwargs["image_environment"] == pinned_images
        assert kwargs["release_set_digest"] == RELEASE_DIGEST
        return _trust(None, None)

    monkeypatch.setattr(smoke, "_run_trust", run_trust)
    passing = lambda: {"status": "PASS"}
    result = smoke.run_s149_under_load_acceptance(
        _env(),
        execute=True,
        predecessor_report=predecessor,
        report_path=tmp_path / "report.json",
        shadow_executor=_shadow,
        fault_executor=_faults,
        storage_runner=_storage,
        provider_runner=_providers,
        deterministic_fault_runner=passing,
        security_runner=passing,
        rollback_runner=passing,
    )

    assert result["status"] == "PASS"
    assert result["checks"]["pinned_release_set_admitted"] is True
    assert result["release_binding"]["pinned_image_source_revision"] == "b" * 40


def test_source_projection_keeps_only_safe_failure_metadata() -> None:
    safe = smoke._source_projection(
        {
            "status": "FAIL",
            "failure_code": "provider_not_ready",
            "issues": ["RuntimeError", "unsafe issue with spaces"],
        }
    )
    unsafe = smoke._source_projection(
        {
            "status": "FAIL",
            "failure_code": "secret value with spaces",
            "issues": "not-a-list",
        }
    )
    empty_issues = smoke._source_projection(
        {"status": "FAIL", "issues": ["unsafe issue with spaces"]}
    )

    assert safe["failure_code"] == "provider_not_ready"
    assert safe["issues"] == ["RuntimeError"]
    assert "failure_code" not in unsafe
    assert "issues" not in unsafe
    assert "issues" not in empty_issues


def test_default_source_adapters(monkeypatch, tmp_path: Path) -> None:
    pinned_images = {"NEX_OA_RUNTIME_IMAGE": "oa@sha256:" + "a" * 64}

    def run_trust(env, **kwargs):
        loader = kwargs["image_environment_loader"]
        images, digest = loader(tmp_path) if loader is not None else (None, None)
        return {
            "status": "PASS",
            "enabled": env[smoke.trust.ENABLE_ENV],
            "images": images,
            "digest": digest,
        }

    monkeypatch.setattr(
        smoke.trust,
        "run_s144_protected_acceptance",
        run_trust,
    )
    monkeypatch.setattr(
        smoke.storage,
        "run_s146_object_storage_acceptance",
        lambda env, **kwargs: {"status": "PASS", "enabled": env[smoke.storage.ENABLE_ENV], **kwargs},
    )
    monkeypatch.setattr(
        smoke.providers,
        "run_s147_model_rollout_live_acceptance",
        lambda env: {
            "status": "PASS",
            "mode": env["NEX_MO_PROVIDER_MODE"],
            "runtime_mode": env["NEX_MO_RUNTIME_OBSERVABILITY_MODE"],
        },
    )

    trust_result = smoke._run_trust(
        {},
        tmp_path / "trust",
        image_environment=pinned_images,
        release_set_digest=RELEASE_DIGEST,
    )
    assert trust_result["enabled"] == "1"
    assert trust_result["images"] == pinned_images
    assert trust_result["digest"] == RELEASE_DIGEST
    assert smoke._run_trust({}, tmp_path / "strict")["images"] is None
    assert smoke._run_storage({}, tmp_path / "storage")["enabled"] == "1"
    provider_result = smoke._run_providers({}, tmp_path / "providers")
    assert provider_result["mode"] == "live"
    assert provider_result["runtime_mode"] == "live"


def test_helpers_redaction_summary_and_main(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = _run(tmp_path)
    skipped = smoke.run_s149_under_load_acceptance({})

    assert smoke.summary_line(skipped) == "s149_under_load_acceptance=skipped"
    assert smoke.summary_line(passing) == (
        "s149_under_load_acceptance=pass checks=16/16 "
        "requests=1440/1440 faults=8/8 residue=0 next=1493"
    )
    assert smoke._mapping([]) == {}
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"leak": "private-provider-key"}, _env())
    monkeypatch.setattr(
        smoke,
        "run_s149_under_load_acceptance",
        lambda **_kwargs: passing,
    )
    assert smoke.main(["--summary", "--report-path", str(tmp_path / "x")]) == 0
    assert "s149_under_load_acceptance=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s149_under_load_acceptance",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
