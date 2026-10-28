from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import importlib.util
from typing import Any


DEMO_PROCESS_MANIFEST_SCHEMA_VERSION = "p8_demo_process_manifest.v1"
DEMO_APPLICATION_ARTIFACTS = (
    "nex-oa-runtime",
    "nex-ag-runtime",
    "nex-ae-runtime",
    "nex-cx-runtime",
    "nex-mo-runtime",
    "nex-wc-runtime",
    "nex-eos-runtime",
    "nex-ae-web",
)
DEMO_INSTALLED_PROCESS_IDS = (
    "nex-oa-api",
    "nex-ag-api",
    "nex-ae-api",
    "nex-cx-api",
    "nex-mo-api",
    "nex-wc-api",
    "nex-eos-api",
    "nex-ae-web",
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher",
)


class DemoProcessManifestError(ValueError):
    pass


@dataclass(frozen=True)
class DemoProcessBinding:
    process_id: str
    owner: str
    artifact_id: str
    kind: str
    execution_model: str
    command: tuple[str, ...] | None
    database_environment: str | None
    pool_workload: str | None
    health_contract: str
    sigterm_contract: str
    restart_contract: str
    required_for_release: bool
    source_modules: tuple[str, ...]
    host_process_id: str | None = None


_API_BINDINGS = (
    ("nex-oa-api", "nex-oa", "nex-oa-runtime", "nex_oa.main:app", "NEX_OA_DATABASE_URL"),
    ("nex-ag-api", "nex-ag", "nex-ag-runtime", "nex_ag.main:app", "NEX_AG_DATABASE_URL"),
    ("nex-ae-api", "nex-ae-api", "nex-ae-runtime", "nex_ae_api.main:app", "NEX_AE_DATABASE_URL"),
    ("nex-cx-api", "nex-cx", "nex-cx-runtime", "nex_cx.main:app", "NEX_CX_DATABASE_URL"),
    ("nex-mo-api", "nex-mo", "nex-mo-runtime", "nex_mo.main:app", "NEX_MO_DATABASE_URL"),
    ("nex-wc-api", "nex-wc", "nex-wc-runtime", "nex_wc.main:app", "NEX_WC_DATABASE_URL"),
    ("nex-eos-api", "nex-eos", "nex-eos-runtime", "nex_eos.main:app", "NEX_EOS_DATABASE_URL"),
)


def build_demo_process_manifest() -> tuple[DemoProcessBinding, ...]:
    bindings = tuple(
        DemoProcessBinding(
            process_id=process_id,
            owner=owner,
            artifact_id=artifact_id,
            kind="api",
            execution_model="INSTALLED_PROCESS",
            command=("python", "-m", "uvicorn", application),
            database_environment=database_environment,
            pool_workload="api",
            health_contract="HTTP:/health+HTTP:/ready",
            sigterm_contract="UVICORN_GRACEFUL_SHUTDOWN",
            restart_contract="STATE_FROM_POSTGRESQL",
            required_for_release=True,
            source_modules=(application.partition(":")[0],),
        )
        for process_id, owner, artifact_id, application, database_environment in _API_BINDINGS
    ) + (
        DemoProcessBinding(
            process_id="nex-ae-web",
            owner="nex-ae-web",
            artifact_id="nex-ae-web",
            kind="web",
            execution_model="INSTALLED_PROCESS",
            command=("npm", "start", "--silent"),
            database_environment=None,
            pool_workload=None,
            health_contract="HTTP:/",
            sigterm_contract="NODE_GRACEFUL_SHUTDOWN",
            restart_contract="STATE_FROM_BACKEND_APIS",
            required_for_release=True,
            source_modules=(),
        ),
        DemoProcessBinding(
            process_id="nex-ae-agent-runtime-worker",
            owner="nex-ae-api",
            artifact_id="nex-ae-runtime",
            kind="worker",
            execution_model="INSTALLED_PROCESS",
            command=(
                "python",
                "-m",
                "nex_ae_api.agent_runtime_process",
                "--profile",
                "staging_live",
            ),
            database_environment="NEX_AE_DATABASE_URL",
            pool_workload="worker",
            health_contract="POSTGRESQL_HEARTBEAT",
            sigterm_contract="FINISH_ACTIVE_CLAIM_THEN_STOP",
            restart_contract="LEASE_EXPIRY_AND_DURABLE_CHECKPOINT",
            required_for_release=True,
            source_modules=(
                "nex_ae_api.agent_runtime_process",
                "nex_ae_api.agent_runtime_dispatcher",
                "nex_ae_api.agent_runtime_worker",
            ),
        ),
        DemoProcessBinding(
            process_id="nex-ae-agent-runtime-dispatcher",
            owner="nex-ae-api",
            artifact_id="nex-ae-runtime",
            kind="component",
            execution_model="EMBEDDED_COMPONENT",
            command=None,
            database_environment="NEX_AE_DATABASE_URL",
            pool_workload="worker",
            health_contract="HOST_PROCESS_HEARTBEAT",
            sigterm_contract="HOST_PROCESS_OWNED",
            restart_contract="DATABASE_LEASE_FENCING",
            required_for_release=True,
            source_modules=("nex_ae_api.agent_runtime_dispatcher",),
            host_process_id="nex-ae-agent-runtime-worker",
        ),
        DemoProcessBinding(
            process_id="nex-wc-event-delivery-worker",
            owner="nex-wc",
            artifact_id="nex-wc-runtime",
            kind="worker",
            execution_model="INSTALLED_PROCESS",
            command=("python", "-m", "nex_wc.demo_runtime", "events"),
            database_environment="NEX_WC_DATABASE_URL",
            pool_workload="worker",
            health_contract="POSTGRESQL_HEARTBEAT",
            sigterm_contract="FINISH_ACTIVE_DELIVERY_THEN_STOP",
            restart_contract="JOB_QUEUE_RETRY_AND_OUTBOX_REPLAY",
            required_for_release=True,
            source_modules=(
                "nex_wc.demo_runtime",
                "nex_wc.handoff_delivery",
                "nex_wc.work_result_delivery",
                "nex_wc.approvals",
            ),
        ),
        DemoProcessBinding(
            process_id="nex-eos-outbox-publisher",
            owner="nex-eos",
            artifact_id="nex-eos-runtime",
            kind="worker",
            execution_model="INSTALLED_PROCESS",
            command=("python", "-m", "nex_eos.demo_runtime", "outbox"),
            database_environment="NEX_EOS_DATABASE_URL",
            pool_workload="worker",
            health_contract="POSTGRESQL_HEARTBEAT",
            sigterm_contract="FINISH_ACTIVE_PUBLICATION_THEN_STOP",
            restart_contract="OUTBOX_REPLAY",
            required_for_release=True,
            source_modules=("nex_eos.demo_runtime", "nex_eos.outbox_publication"),
        ),
    )
    validate_demo_process_manifest(bindings)
    return bindings


def validate_demo_process_manifest(
    bindings: Sequence[DemoProcessBinding],
    *,
    module_finder: Callable[[str], object | None] | None = None,
) -> None:
    find_module = module_finder or importlib.util.find_spec
    errors: list[str] = []
    process_ids = [item.process_id for item in bindings]
    if len(set(process_ids)) != len(process_ids):
        errors.append("duplicate process_id")
    installed = {
        item.process_id for item in bindings if item.execution_model == "INSTALLED_PROCESS"
    }
    if installed != set(DEMO_INSTALLED_PROCESS_IDS):
        errors.append("installed process inventory drift")
    artifacts = {item.artifact_id for item in bindings if item.required_for_release}
    if artifacts != set(DEMO_APPLICATION_ARTIFACTS):
        errors.append("eight-image artifact ownership is incomplete")
    for item in bindings:
        if item.execution_model not in {"INSTALLED_PROCESS", "EMBEDDED_COMPONENT"}:
            errors.append(f"unsupported execution model: {item.process_id}")
        if item.execution_model == "INSTALLED_PROCESS" and not item.command:
            errors.append(f"installed process command missing: {item.process_id}")
        if item.execution_model == "EMBEDDED_COMPONENT":
            if item.command is not None or item.host_process_id not in installed:
                errors.append(f"embedded component host invalid: {item.process_id}")
        if item.kind in {"worker", "component"} and (
            item.pool_workload != "worker" or item.database_environment is None
        ):
            errors.append(f"background persistence boundary invalid: {item.process_id}")
        if item.kind == "worker" and (
            "HEARTBEAT" not in item.health_contract
            or "STOP" not in item.sigterm_contract
        ):
            errors.append(f"worker lifecycle contract incomplete: {item.process_id}")
        for module in item.source_modules:
            try:
                found = find_module(module)
            except (ImportError, ModuleNotFoundError, ValueError):
                found = None
            if found is None:
                errors.append(f"source module missing: {item.process_id}:{module}")
        if item.command and any("tests/" in argument for argument in item.command):
            errors.append(f"test-only command is forbidden: {item.process_id}")
    if errors:
        raise DemoProcessManifestError("; ".join(errors))


def demo_process_manifest_projection(
    bindings: Sequence[DemoProcessBinding] | None = None,
) -> dict[str, Any]:
    admitted = tuple(bindings or build_demo_process_manifest())
    validate_demo_process_manifest(admitted)
    return {
        "schema_version": DEMO_PROCESS_MANIFEST_SCHEMA_VERSION,
        "processes": [
            {
                "process_id": item.process_id,
                "owner": item.owner,
                "artifact_id": item.artifact_id,
                "kind": item.kind,
                "execution_model": item.execution_model,
                "command": None if item.command is None else list(item.command),
                "database_environment": item.database_environment,
                "pool_workload": item.pool_workload,
                "health_contract": item.health_contract,
                "sigterm_contract": item.sigterm_contract,
                "restart_contract": item.restart_contract,
                "required_for_release": item.required_for_release,
                "source_modules": list(item.source_modules),
                "host_process_id": item.host_process_id,
            }
            for item in admitted
        ],
        "installed_process_count": sum(
            item.execution_model == "INSTALLED_PROCESS" for item in admitted
        ),
        "embedded_component_count": sum(
            item.execution_model == "EMBEDDED_COMPONENT" for item in admitted
        ),
        "application_artifact_count": len(
            {item.artifact_id for item in admitted if item.required_for_release}
        ),
        "in_test_function_calls_admitted": False,
    }
