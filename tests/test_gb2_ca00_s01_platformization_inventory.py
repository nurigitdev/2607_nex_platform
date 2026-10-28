from __future__ import annotations

import json
import re
from pathlib import Path

from nex_runtime.demo_processes import build_demo_process_manifest
from nex_runtime.deployment_artifacts import build_current_deployment_artifact_catalog
from nex_runtime.process_manifest import build_current_platform_runtime_manifest

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = (
    ROOT
    / "docs/transition/GB2/"
    "GB2_CA00_Platform_Runtime_Process_and_Dependency_Inventory_v1.0.md"
)
PROMOTION_PROCESS_IDS = {
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher",
}
CURRENT_PROMOTED_PROCESS_IDS = {"nex-ae-agent-runtime-worker"}
REQUIRED_REFERENCES = (
    "services/nex-ae-api/nex_ae_api/p8_demo_runtime_composition.py",
    "services/nex-ae-api/nex_ae_api/p8_demo_controlled_skill.py",
    "services/nex-ae-api/nex_ae_api/p8_demo_semantic_activation.py",
    "services/nex-ae-api/nex_ae_api/demo_runtime.py",
    "services/nex-wc/nex_wc/demo_runtime.py",
    "services/nex-eos/nex_eos/demo_runtime.py",
    "services/_shared/nex_runtime/demo_processes.py",
    "services/_shared/nex_runtime/demo_domain_activation.py",
    "services/_shared/nex_runtime/demo_domain_installation.py",
    "services/nex-ae-api/nex_ae_api/agent_runtime_dispatcher.py",
    "services/nex-ae-api/nex_ae_api/agent_runtime_worker.py",
    "services/nex-ae-api/nex_ae_api/multi_step_engine.py",
    "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py",
    "services/nex-ae-api/nex_ae_api/nsl_approval_resume.py",
    "services/nex-ae-api/nex_ae_api/workspace_result_publication.py",
    "services/nex-wc/nex_wc/handoff_delivery.py",
    "services/nex-wc/nex_wc/work_result_delivery.py",
    "services/nex-wc/nex_wc/approval_event_delivery.py",
    "services/nex-eos/nex_eos/outbox_publication.py",
    "services/_shared/nex_runtime/process_manifest.py",
    "services/_shared/nex_runtime/deployment_artifacts.py",
    "services/_shared/nex_runtime/deployment_entrypoints.py",
    "services/_shared/nex_runtime/production_container_bootstrap.py",
    "services/_shared/nex_runtime/openbao_secret_resolver.py",
    "services/_shared/nex_runtime/object_storage.py",
    "services/_shared/nex_runtime/object_storage_lifecycle.py",
    "services/_shared/nex_runtime/rustfs_iam.py",
    "services/nex-mo/nex_mo/provider_readiness_service.py",
)


def _contract() -> dict[str, object]:
    text = INVENTORY.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- gb2-s01-contract:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- gb2-s01-contract:end -->",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_inventory_references_exist_and_are_classified() -> None:
    text = INVENTORY.read_text(encoding="utf-8")

    for reference in REQUIRED_REFERENCES:
        assert reference in text
        assert (ROOT / reference).is_file()
    for classification in ("`P`", "`D`", "`T`", "`H`", "`X`"):
        assert classification in text


def test_inventory_counts_match_current_and_demo_source_manifests() -> None:
    contract = _contract()
    manifest = build_current_platform_runtime_manifest(
        environ={}, python_executable="python"
    )
    catalog = build_current_deployment_artifact_catalog()
    current_ids = {process.process_id for process in manifest.processes}
    demo_installed_ids = {
        process.process_id
        for process in build_demo_process_manifest()
        if process.execution_model == "INSTALLED_PROCESS"
    }

    assert contract["current_artifact_count"] == len(catalog.artifacts) == 9
    assert contract["current_installed_process_count"] == len(current_ids) == 18
    assert set(contract["promotion_process_ids"]) == PROMOTION_PROCESS_IDS
    assert set(contract["current_promoted_process_ids"]) == (
        CURRENT_PROMOTED_PROCESS_IDS
    )
    assert PROMOTION_PROCESS_IDS & current_ids == CURRENT_PROMOTED_PROCESS_IDS
    assert PROMOTION_PROCESS_IDS.issubset(demo_installed_ids)
    assert contract["target_artifact_count"] == 9
    remaining_promotions = PROMOTION_PROCESS_IDS - current_ids
    assert contract["target_installed_process_count"] == (
        len(current_ids) + len(remaining_promotions)
    ) == 20
    assert contract["embedded_component_ids"] == [
        "nex-ae-agent-runtime-dispatcher"
    ]


def test_inventory_freezes_non_migration_boundary_and_authorizes_s02() -> None:
    contract = _contract()
    text = INVENTORY.read_text(encoding="utf-8")

    assert contract["database_migration"] == "NO"
    assert contract["new_business_table"] == "NO"
    assert contract["new_public_business_api"] == "NO"
    assert "S02 Runtime Process Capability Taxonomy | AUTHORIZED" in text
