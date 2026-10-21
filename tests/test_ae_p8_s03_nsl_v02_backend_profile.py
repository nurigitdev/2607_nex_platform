from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_BACKEND_PROFILES,
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    NSL_V02_IN_PROCESS_BACKEND,
    normalize_nsl_backend_profile,
    normalize_nsl_backend_profile_for_operation,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    NSLReadBackendRouter,
)
from nex_ae_api.nsl_step_executions import validate_nsl_step_execution_binding
from nex_ae_api.planning_capabilities import (
    build_local_skill_capability,
    validate_local_skill_binding,
)

HASH = "sha256:" + "a" * 64
NOW = "2026-10-21T00:00:00Z"


class _Backend:
    def __init__(self, profile: str) -> None:
        self.backend_profile = profile

    def execute(self, **kwargs):
        return kwargs


def _binding(profile: str) -> dict[str, object]:
    identities = [str(uuid4()) for _ in range(5)]
    return {
        "schema_version": "1.0",
        "tenant_id": "tenant-p8",
        "agent_execution_id": identities[0],
        "executable_plan_id": identities[1],
        "executable_step_id": identities[2],
        "nsl_execution_id": identities[3],
        "business_operation_id": identities[4],
        "skill_id": "NSL.FINANCE.READ",
        "exact_skill_version": "0.2.0",
        "skill_semantic_hash": HASH,
        "verified_artifact_ref": "artifact://tenant-p8/skill",
        "verified_artifact_hash": HASH,
        "request_ref": "request://tenant-p8/nsl",
        "request_hash": HASH,
        "backend_profile": profile,
        "state": "ALLOCATED",
        "result_summary_ref": None,
        "result_summary_hash": None,
        "allocated_at": NOW,
        "request_bound_at": None,
        "invocation_started_at": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_v02_profile_is_explicit_without_changing_v01_default() -> None:
    assert DEFAULT_NSL_V01_BACKEND_PROFILE == NSL_V01_IN_PROCESS_BACKEND
    assert NSL_BACKEND_PROFILES == {
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
        NSL_V02_IN_PROCESS_BACKEND,
    }
    assert normalize_nsl_backend_profile(NSL_V02_IN_PROCESS_BACKEND) == (
        NSL_V02_IN_PROCESS_BACKEND
    )


@pytest.mark.parametrize(
    "profile",
    (
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
        NSL_V02_IN_PROCESS_BACKEND,
    ),
)
def test_read_remains_compatible_with_known_profiles(profile: str) -> None:
    assert normalize_nsl_backend_profile_for_operation(profile, "READ") == profile


def test_write_requires_v02_and_unknown_values_fail_closed() -> None:
    assert normalize_nsl_backend_profile_for_operation(
        NSL_V02_IN_PROCESS_BACKEND, "WRITE"
    ) == NSL_V02_IN_PROCESS_BACKEND
    for profile in (
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    ):
        with pytest.raises(ValueError, match="WRITE requires"):
            normalize_nsl_backend_profile_for_operation(profile, "WRITE")
    with pytest.raises(ValueError, match="profile is unsupported"):
        normalize_nsl_backend_profile("UNKNOWN")
    with pytest.raises(ValueError, match="operation semantics"):
        normalize_nsl_backend_profile_for_operation(
            NSL_V02_IN_PROCESS_BACKEND, "DELETE"
        )


def test_v02_profile_flows_through_capability_and_execution_binding() -> None:
    capability = build_local_skill_capability(
        skill_id="NSL.FINANCE.READ",
        exact_skill_version="0.2.0",
        skill_semantic_hash=HASH,
        input_contract_ref="contract://nsl/read-input/v0.2",
        output_contract_ref="contract://nsl/read-output/v0.2",
        runtime_contract_ref="contract://nsl/runtime/v0.2",
        trust_policy_id="policy://nsl/trusted/v0.2",
        backend_profile=NSL_V02_IN_PROCESS_BACKEND,
    )
    assert capability["local_skill_binding"]["backend_profile"] == (
        NSL_V02_IN_PROCESS_BACKEND
    )
    assert validate_local_skill_binding(capability["local_skill_binding"])[
        "backend_profile"
    ] == NSL_V02_IN_PROCESS_BACKEND
    assert validate_nsl_step_execution_binding(
        _binding(NSL_V02_IN_PROCESS_BACKEND)
    )["backend_profile"] == NSL_V02_IN_PROCESS_BACKEND


def test_router_requires_exact_v02_profile_without_fallback() -> None:
    backend = _Backend(NSL_V02_IN_PROCESS_BACKEND)
    router = NSLReadBackendRouter({NSL_V02_IN_PROCESS_BACKEND: backend})

    assert router.backend_profiles == (NSL_V02_IN_PROCESS_BACKEND,)
    assert router.resolve(NSL_V02_IN_PROCESS_BACKEND) is backend
    with pytest.raises(NSLReadBackendError) as unavailable:
        router.resolve(NSL_V01_IN_PROCESS_BACKEND)
    assert unavailable.value.error_code == "ae.nsl_backend_profile_unavailable"

    mismatched = deepcopy({NSL_V02_IN_PROCESS_BACKEND: backend})
    mismatched[NSL_V02_IN_PROCESS_BACKEND] = _Backend(
        NSL_V01_IN_PROCESS_BACKEND
    )
    with pytest.raises(NSLReadBackendError) as mismatch:
        NSLReadBackendRouter(mismatched)
    assert mismatch.value.error_code == "ae.nsl_read_backend_unavailable"
