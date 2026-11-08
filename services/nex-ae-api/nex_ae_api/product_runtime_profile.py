from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.product_controlled_skill import (
    ProductControlledSkillConfig,
    ProductControlledSkillRuntime,
)
from nex_ae_api.runtime_composition import RuntimeExecutorProfile
from nex_ae_api.step_executors import default_p6_executor_registry

ROOT = Path(__file__).resolve().parents[3]


def build_product_runtime_executor_profile(
    sessions: sessionmaker[Session],
    environ: Mapping[str, str],
) -> RuntimeExecutorProfile:
    """Compose the installed product LOCAL_SKILL and controlled WRITE profile."""

    controlled = ProductControlledSkillRuntime(
        sessions,
        load_product_controlled_skill_config(environ),
        environ=environ,
    )
    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=controlled.dependencies,
        local_skill_handler=controlled.initial,
        local_skill_continuation_handler=controlled.resume,
    )
    return RuntimeExecutorProfile(
        registry=registry,
        executor_backends={
            kind: controlled.backend_profile for kind in registry.registered_kinds
        },
        package_readiness=controlled.package_readiness,
    )


def load_product_controlled_skill_config(
    environ: Mapping[str, str],
) -> ProductControlledSkillConfig:
    return ProductControlledSkillConfig(
        manifest_path=_path(
            environ,
            "NEX_AE_NSL_BUNDLE_MANIFEST",
            ROOT / "deployment/locks/ae-product-nsl-runtime-bundle.v1.json",
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
        skill_root=_path(
            environ,
            "NEX_AE_NSL_SKILL_ROOT",
            Path("/home/tprover/2608_nsl/examples/golden_a_voucher_draft"),
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
