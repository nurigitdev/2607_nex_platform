from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from nex_runtime import resolve_service_endpoint
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.allocation_plan_resolution_runtime import (
    build_installed_allocation_plan_resolution,
)
from nex_ae_api.delegated_work import (
    HttpWcWorkItemClient,
    SqlAlchemyDelegationRuntimeRepository,
    SqlAlchemyWaitRegistrationRepository,
)
from nex_ae_api.m1_installed_skill_runtime import (
    M1InstalledSkillRuntime,
    M1InstalledSkillRuntimeConfig,
)
from nex_ae_api.m1_transaction_preparation_runtime import (
    build_installed_m1_transaction_preparation,
)
from nex_ae_api.mybee_m1_skill_runtime import (
    build_mybee_m1_runtime_admission,
    build_mybee_m1_verified_skill_catalog,
)
from nex_ae_api.runtime_composition import RuntimeExecutorProfile
from nex_ae_api.service_auth import resolve_ae_outbound_service_token
from nex_ae_api.step_executors import (
    DelegateWorkExecutorDependencies,
    default_p7_executor_registry,
)

ROOT = Path(__file__).resolve().parents[3]
VERIFIED_PRODUCT_RELEASE_PROFILE = "VERIFIED_PRODUCT_RELEASE"


def build_product_runtime_executor_profile(
    sessions: sessionmaker[Session],
    environ: Mapping[str, str],
    *,
    runtime: M1InstalledSkillRuntime | None = None,
) -> RuntimeExecutorProfile:
    """Compose the installed product LOCAL_SKILL and controlled WRITE profile."""

    selected = str(
        environ.get("NEX_AE_PRODUCT_RUNTIME_PROFILE")
        or VERIFIED_PRODUCT_RELEASE_PROFILE
    ).strip()
    if selected != VERIFIED_PRODUCT_RELEASE_PROFILE:
        raise ValueError("NEX_AE_PRODUCT_RUNTIME_PROFILE is not admitted")
    return _build_verified_product_release_profile(
        sessions,
        environ,
        runtime=runtime,
    )


def _build_verified_product_release_profile(
    sessions: sessionmaker[Session],
    environ: Mapping[str, str],
    *,
    runtime: M1InstalledSkillRuntime | None = None,
) -> RuntimeExecutorProfile:
    expected_admission, activation = _admit_verified_product_release(environ)
    installed = runtime or _build_installed_product_skill_runtime(sessions, environ)
    wc_endpoint = resolve_service_endpoint("nex-wc", environ=environ)
    registry = default_p7_executor_registry(
        lambda _context: {},
        local_skill_dependencies=installed.dependencies,
        local_skill_handler=installed.initial,
        local_skill_continuation_handler=installed.resume,
        delegate_work_dependencies=DelegateWorkExecutorDependencies(
            runtime_repository=SqlAlchemyDelegationRuntimeRepository(sessions),
            wait_repository=SqlAlchemyWaitRegistrationRepository(sessions),
            work_item_client=HttpWcWorkItemClient(
                base_url=str(environ.get("NEX_WC_BASE_URL") or wc_endpoint.base_url),
                service_token=resolve_ae_outbound_service_token(
                    environ.get("NEX_AE_TO_WC_SERVICE_TOKEN"),
                    audience="nex-wc",
                    environ=environ,
                ),
                timeout_seconds=float(
                    environ.get("NEX_AE_TO_WC_TIMEOUT_SECONDS", "15")
                ),
            ),
        ),
    )
    readiness = {
        **dict(installed.package_readiness),
        "runtime_profile": VERIFIED_PRODUCT_RELEASE_PROFILE,
        "admission_hash": expected_admission["content_hash"],
        "activation_hash": activation["content_hash"],
    }
    return RuntimeExecutorProfile(
        registry=registry,
        executor_backends={
            kind: installed.backend_profile for kind in registry.registered_kinds
        },
        package_readiness=readiness,
        in_process_package_readiness=installed.nsl_package_readiness,
    )


def build_installed_product_skill_runtime(
    sessions: sessionmaker[Session],
    environ: Mapping[str, str],
) -> M1InstalledSkillRuntime:
    """Build the single admitted Product Skill runtime shared by worker roles."""

    _admit_verified_product_release(environ)
    return _build_installed_product_skill_runtime(sessions, environ)


def _admit_verified_product_release(
    environ: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    admission_path = _path(
        environ,
        "NEX_AE_PRODUCT_RUNTIME_ADMISSION_PATH",
        ROOT / "deployment/locks/ae-mybee-m1-runtime-admission.v2.json",
    )
    expected_admission = build_mybee_m1_runtime_admission(environ)
    if _json_object(admission_path) != expected_admission:
        raise ValueError("verified product runtime admission lock has drifted")
    activation_path = _path(
        environ,
        "NEX_AE_PRODUCT_RUNTIME_ACTIVATION_PATH",
        ROOT / "deployment/locks/ae-mybee-m1-runtime-activation.v2.json",
    )
    activation = _json_object(activation_path)
    _verify_activation_lock(
        activation,
        admission=expected_admission,
        repository_root=_path(
            environ,
            "NEX_AE_PRODUCT_REPOSITORY_ROOT",
            ROOT,
            require_existing=True,
        ),
    )
    return expected_admission, activation


def _build_installed_product_skill_runtime(
    sessions: sessionmaker[Session],
    environ: Mapping[str, str],
) -> M1InstalledSkillRuntime:
    return M1InstalledSkillRuntime(
        sessions,
        catalog=build_mybee_m1_verified_skill_catalog(environ),
        config=load_verified_product_runtime_config(environ),
        transaction_preparation=build_installed_m1_transaction_preparation(environ),
        allocation_plan_resolution=build_installed_allocation_plan_resolution(environ),
    )


def load_verified_product_runtime_config(
    environ: Mapping[str, str],
) -> M1InstalledSkillRuntimeConfig:
    return M1InstalledSkillRuntimeConfig(
        wheel_lock_path=_path(
            environ,
            "NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK",
            ROOT / "deployment/locks/nsl-v0.2.1-wheel.json",
        ),
        wheel_path=_path(
            environ,
            "NEX_AE_NSL_WHEEL",
            ROOT
            / "reports/deployment/p8-nsl-v0.2.1-wheel"
            / "nex_skill_language-0.2.1-py3-none-any.whl",
        ),
        platform_lock_path=_path(
            environ,
            "NEX_AE_NSL_PLATFORM_LOCK",
            ROOT / "deployment/locks/python-production.lock",
        ),
        tool_catalog_path=_path(
            environ,
            "NEX_AE_PRODUCT_TOOL_CATALOG_PATH",
            ROOT / "domains/mybee/skills/m1_checkpoint/tool_catalog.v1.json",
        ),
        context_path=_path(
            environ,
            "NEX_AE_PRODUCT_RUNTIME_CONTEXT_PATH",
            ROOT / "domains/mybee/skills/m1_checkpoint/context.json",
        ),
        state_root=_path(
            environ,
            "NEX_AE_NSL_STATE_ROOT",
            Path("/data/nex-platform/ae/nsl-runtime"),
            require_existing=False,
        ),
        oa_base_url=_text(environ, "NEX_OA_BASE_URL"),
        eos_base_url=_text(environ, "NEX_EOS_BASE_URL"),
        ae_to_oa_service_token=_text(environ, "NEX_AE_TO_OA_SERVICE_TOKEN"),
        ae_to_eos_service_token=_text(environ, "NEX_AE_TO_EOS_SERVICE_TOKEN"),
        approver_role=str(
            environ.get("NEX_AE_FINANCE_APPROVER_ROLE") or "finance_approver"
        ).strip(),
    )


def _path(
    environ: Mapping[str, str],
    name: str,
    default: Path,
    *,
    require_existing: bool = True,
) -> Path:
    path = Path(str(environ.get(name) or default)).expanduser()
    if require_existing and not path.exists():
        raise ValueError(f"{name} is unavailable")
    return path


def _text(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _verify_activation_lock(
    lock: Mapping[str, object],
    *,
    admission: Mapping[str, object],
    repository_root: Path,
) -> None:
    if lock.get("schema_version") != "ae.verified_product_runtime_activation.v2":
        raise ValueError("verified product runtime activation schema is unsupported")
    if lock.get("activation_state") != "ACTIVE_GENERALIZED":
        raise ValueError("verified product runtime activation is not active")
    if lock.get("runtime_profile") != VERIFIED_PRODUCT_RELEASE_PROFILE:
        raise ValueError("verified product runtime profile has drifted")
    if lock.get("runtime_admission_hash") != admission.get("content_hash"):
        raise ValueError("verified product runtime admission hash has drifted")
    rollback = lock.get("rollback_target")
    if not isinstance(rollback, Mapping):
        raise TypeError("generalized rollback receipt is required")
    if rollback.get("profile") != VERIFIED_PRODUCT_RELEASE_PROFILE:
        raise ValueError("generalized rollback profile has drifted")
    if rollback.get("golden_a_dependency") is not False:
        raise ValueError("generalized rollback cannot depend on Golden A")
    rollback_ref = rollback.get("receipt_ref")
    if not isinstance(rollback_ref, str) or not rollback_ref:
        raise ValueError("generalized rollback receipt reference is invalid")
    receipt = repository_root / rollback_ref
    if not receipt.is_file() or rollback.get("receipt_sha256") != _file_sha256(receipt):
        raise ValueError("generalized rollback receipt has drifted")
    receipt_payload = _json_object(receipt)
    if (
        receipt_payload.get("schema_version")
        != "ae.generalized_runtime_rollback_receipt.v1"
        or receipt_payload.get("golden_a_dependency") is not False
        or receipt_payload.get("runtime_admission_hash")
        != admission.get("content_hash")
    ):
        raise ValueError("generalized rollback receipt is not admitted")
    expected_hash = lock.get("content_hash")
    body = {key: value for key, value in lock.items() if key != "content_hash"}
    from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

    if expected_hash != semantic_sha256_hash_ref(body):
        raise ValueError("verified product runtime activation hash has drifted")


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
