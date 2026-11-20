from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mybee_ax.integrations import (
    M1_D04_CAPABILITY_ID,
    M1_D12_CAPABILITY_ID,
    load_m1_signed_skill_release,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.nsl_eos_journal_execution import (
    EOS_JOURNAL_POST_OPERATION,
    build_default_eos_journal_execution_port,
)
from nex_ae_api.nsl_eos_journal_reconciliation import (
    EOS_JOURNAL_RECONCILE_OPERATION,
    build_default_eos_journal_reconciliation_adapter,
)
from nex_ae_api.nsl_eos_journal_verification import (
    build_default_eos_journal_verification_adapter,
)
from nex_ae_api.nsl_eos_project_work_code_read import (
    EOS_PROJECT_WORK_CODE_GET_OPERATION,
    HttpEosProjectWorkCodeReadAdapter,
)
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_skill_catalog import (
    ProductOperationAdapterContext,
    ProductOperationAdapterRegistration,
    ProductOperationAdapterRegistry,
    ProductOperationAdapterSet,
    ProductSkillCatalogError,
    VerifiedProductSkillCatalog,
)

MYBEE_M1_BACKEND_PROFILE = "NSL_V02_IN_PROCESS"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_M1_RELEASE_LOCK = (
    ROOT / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v3.json"
)


def build_mybee_m1_operation_adapter_registry() -> ProductOperationAdapterRegistry:
    return ProductOperationAdapterRegistry(
        (
            ProductOperationAdapterRegistration(
                capability_id=M1_D04_CAPABILITY_ID,
                operation_semantics="WRITE",
                backend_profile=MYBEE_M1_BACKEND_PROFILE,
                adapter_id="nex-ae:eos-journal-controlled-write:v1",
                operation_ids=(
                    EOS_JOURNAL_POST_OPERATION,
                    EOS_JOURNAL_RECONCILE_OPERATION,
                ),
                factory=_build_d04_adapters,
            ),
            ProductOperationAdapterRegistration(
                capability_id=M1_D12_CAPABILITY_ID,
                operation_semantics="READ",
                backend_profile=MYBEE_M1_BACKEND_PROFILE,
                adapter_id="nex-ae:eos-project-work-code-read:v1",
                operation_ids=(EOS_PROJECT_WORK_CODE_GET_OPERATION,),
                factory=_build_d12_adapters,
            ),
        )
    )


def build_mybee_m1_verified_skill_catalog(
    environ: Mapping[str, str],
) -> VerifiedProductSkillCatalog:
    release = load_mybee_m1_signed_release(environ)
    capabilities = load_product_capability_registry(environ)
    return VerifiedProductSkillCatalog(
        release=release,
        capability_registry=capabilities,
        operation_registry=build_mybee_m1_operation_adapter_registry(),
    )


def build_mybee_m1_runtime_admission(
    environ: Mapping[str, str],
) -> dict[str, object]:
    capabilities = load_product_capability_registry(environ)
    operations = build_mybee_m1_operation_adapter_registry()
    release = load_mybee_m1_signed_release(environ)
    catalog = VerifiedProductSkillCatalog(
        release=release,
        capability_registry=capabilities,
        operation_registry=operations,
    )
    admission: dict[str, object] = {
        "schema_version": "ae.mybee_m1_runtime_admission.v1",
        "release_id": release.release_id,
        "release_hash": release.content_hash,
        "package_ref": release.package_ref,
        "package_hash": release.package_hash,
        "signing_key_id": release.signing_key_id,
        "capability_registry_id": capabilities.registry_id,
        "capability_registry_version": capabilities.registry_version,
        "capability_registry_hash": capabilities.registry_hash,
        "operation_registry": operations.to_projection(),
        "operation_registry_hash": operations.registry_hash,
        "skill_catalog": catalog.to_projection(),
        "skill_catalog_hash": catalog.catalog_hash,
        "backend_profiles": [MYBEE_M1_BACKEND_PROFILE],
        "runtime_selectable_capabilities": [
            item.capability.capability_id for item in catalog.selections
        ],
        "remote_provider_required": False,
        "database_migration_required": False,
    }
    admission["content_hash"] = semantic_sha256_hash_ref(admission)
    return admission


def load_mybee_m1_signed_release(environ: Mapping[str, str]):
    lock = Path(
        str(environ.get("NEX_AE_M1_SIGNED_SKILL_LOCK") or DEFAULT_M1_RELEASE_LOCK)
    )
    repository_root = Path(str(environ.get("NEX_AE_M1_REPOSITORY_ROOT") or ROOT))
    return load_m1_signed_skill_release(lock, repository_root=repository_root)


def _build_d12_adapters(
    context: ProductOperationAdapterContext,
) -> ProductOperationAdapterSet:
    base_url = str(context.environ.get("NEX_EOS_BASE_URL") or "").strip()
    if not base_url:
        raise ProductSkillCatalogError(
            "PRODUCT_OPERATION_CONFIGURATION_REQUIRED",
            "NEX_EOS_BASE_URL is required for D12 Project WorkCode READ.",
        )
    handler = HttpEosProjectWorkCodeReadAdapter(
        base_url=base_url,
        service_token=(
            str(context.environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or "").strip()
            or None
        ),
    )
    return ProductOperationAdapterSet(
        tool_handlers={EOS_PROJECT_WORK_CODE_GET_OPERATION: handler}
    )


def _build_d04_adapters(
    context: ProductOperationAdapterContext,
) -> ProductOperationAdapterSet:
    if (
        context.public_api is None
        or context.result_type is None
        or context.result_classification is None
    ):
        raise ProductSkillCatalogError(
            "PRODUCT_OPERATION_CONTEXT_REQUIRED",
            "D04 Journal adapters require the admitted NSL public API and result contract.",
        )
    return ProductOperationAdapterSet(
        write_port=build_default_eos_journal_execution_port(
            public_api=context.public_api,
            result_type=context.result_type,
            result_classification=context.result_classification,
            environ=context.environ,
        ),
        verification_port=build_default_eos_journal_verification_adapter(
            public_api=context.public_api,
            environ=context.environ,
        ),
        reconciliation_port=build_default_eos_journal_reconciliation_adapter(
            public_api=context.public_api,
            result_type=context.result_type,
            result_classification=context.result_classification,
            environ=context.environ,
        ),
    )
