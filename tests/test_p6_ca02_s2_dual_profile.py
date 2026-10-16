from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeWorkerError,
    build_agent_runtime_worker_profile,
    validate_agent_runtime_worker_profile,
)
from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_V01_BACKEND_PROFILES,
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    normalize_nsl_backend_profile,
)
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    validate_nsl_step_execution_binding,
)
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    build_local_skill_capability,
)

ROOT = Path(__file__).resolve().parents[1]
P6_CONTRACTS = ROOT / "docs/transition/P6/contracts"
MIGRATION = ROOT / "database/nex-ae-api/migrations/2205_ae_nsl_dual_profile.sql"
NOW = "2026-10-16T06:00:00Z"


def _capability(**overrides: str) -> dict[str, object]:
    values = {
        "skill_id": "FINANCE.PROJECT_BUDGET_CHECK",
        "exact_skill_version": "1.0.0",
        "skill_semantic_hash": "sha256:" + "a" * 64,
        "input_contract_ref": "contract://nex/p6/skill-execution-request/v1",
        "output_contract_ref": "contract://nex/p6/step-result/v1.2",
        "runtime_contract_ref": "contract://nex/nsl/read-runtime/v1",
        "trust_policy_id": "p6-signed-active-v1",
    }
    return build_local_skill_capability(**{**values, **overrides})


def _binding() -> dict[str, object]:
    return json.loads(
        (P6_CONTRACTS / "examples/p6-golden-step-execution-binding-v1.json").read_text(
            encoding="utf-8"
        )
    )


def test_profile_catalog_has_in_process_default_and_historical_profile() -> None:
    assert DEFAULT_NSL_V01_BACKEND_PROFILE == NSL_V01_IN_PROCESS_BACKEND
    assert NSL_V01_BACKEND_PROFILES == {
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    }
    for profile in NSL_V01_BACKEND_PROFILES:
        assert normalize_nsl_backend_profile(profile) == profile
    for value in (None, "", " NSL_V01_IN_PROCESS", "NSL_V02_REMOTE"):
        with pytest.raises(ValueError, match="unsupported"):
            normalize_nsl_backend_profile(value)


def test_new_capability_defaults_in_process_and_historical_is_explicit() -> None:
    assert _capability()["local_skill_binding"]["backend_profile"] == (
        NSL_V01_IN_PROCESS_BACKEND
    )
    assert _capability(backend_profile=NSL_V01_PROCESS_ISOLATED_BACKEND)[
        "local_skill_binding"
    ]["backend_profile"] == (NSL_V01_PROCESS_ISOLATED_BACKEND)
    with pytest.raises(CapabilitySnapshotError, match="unsupported"):
        _capability(backend_profile="NSL_V02_REMOTE")


def test_binding_contract_and_runtime_validator_accept_exact_dual_profiles() -> None:
    schema = json.loads(
        (P6_CONTRACTS / "p6-nsl-step-execution-binding-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for profile in NSL_V01_BACKEND_PROFILES:
        value = _binding()
        value["backend_profile"] = profile
        validator.validate(value)
        assert validate_nsl_step_execution_binding(value)["backend_profile"] == profile

    unknown = _binding()
    unknown["backend_profile"] = "NSL_V02_REMOTE"
    with pytest.raises(ValidationError):
        validator.validate(unknown)
    with pytest.raises(NSLStepExecutionError, match="profile"):
        validate_nsl_step_execution_binding(unknown)


def test_worker_profile_accepts_known_profiles_and_rejects_unknown() -> None:
    profile = build_agent_runtime_worker_profile(
        worker_id="worker-dual",
        declared_at=NOW,
        supported_backend_profiles=(
            NSL_V01_IN_PROCESS_BACKEND,
            NSL_V01_PROCESS_ISOLATED_BACKEND,
        ),
    )
    assert validate_agent_runtime_worker_profile(profile.to_record())[
        "supported_backend_profiles"
    ] == [NSL_V01_IN_PROCESS_BACKEND, NSL_V01_PROCESS_ISOLATED_BACKEND]

    record = copy.deepcopy(profile.to_record())
    record["supported_backend_profiles"] = ["NSL_V02_REMOTE"]
    with pytest.raises(AgentRuntimeWorkerError, match="unsupported"):
        validate_agent_runtime_worker_profile(record)


def test_migration_widens_only_the_profile_check_without_rewriting_rows() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "2205_ae_nsl_dual_profile" in sql
    assert "ck_ae_nsl_step_profile" in sql
    assert "'NSL_V01_IN_PROCESS'" in sql
    assert "'NSL_V01_PROCESS_ISOLATED'" in sql
    assert "UPDATE ae_nsl_step_execution" not in sql
    assert "DELETE FROM ae_nsl_step_execution" not in sql
