from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_ag.generation_audit import register_generation_audit_routes
from nex_ag.generation_quality_disposition import (
    register_generation_quality_disposition_routes,
)
from nex_ag.generation_remediation import (
    default_generation_remediation_task_store,
    register_generation_remediation_task_routes,
)
from nex_ag.generation_remediation_execution import (
    register_generation_remediation_execution_routes,
)
from nex_ag.operations import (
    attach_ag_operations_source_runtime,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_service_log_routes,
    register_unified_operation_routes,
)
from nex_ag.processing_operations import (
    build_cx_processing_run_operation_stores,
    register_cx_processing_run_operation_routes,
)
from nex_ag.readiness import register_readiness_routes
from nex_ag.remediation_execution_operations import (
    build_remediation_execution_operations_projection,
    build_remediation_execution_operation_stores,
    register_remediation_execution_operation_routes,
)
from nex_ag.retrieval_policies import register_retrieval_policy_routes
from nex_ag.retrieval_operations import (
    build_retrieval_package_operation_stores,
    register_retrieval_package_operation_routes,
)


SERVICE_SPEC = SERVICE_SPECS["nex-ag"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_service_job_control_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
register_service_log_retention_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    store=SERVICE_PERSISTENCE.service_log_store,
)
OPERATIONS_SOURCE_RUNTIME = attach_ag_operations_source_runtime(app)
OPERATIONS_SOURCE_REGISTRY = OPERATIONS_SOURCE_RUNTIME.registry
RETRIEVAL_PACKAGE_OPERATION_STORES = build_retrieval_package_operation_stores(
    runtime=OPERATIONS_SOURCE_RUNTIME
)
CX_PROCESSING_RUN_OPERATION_STORES = build_cx_processing_run_operation_stores(
    runtime=OPERATIONS_SOURCE_RUNTIME
)
REMEDIATION_EXECUTION_OPERATION_STORES = (
    build_remediation_execution_operation_stores(runtime=OPERATIONS_SOURCE_RUNTIME)
)
GENERATION_REMEDIATION_TASK_STORE = default_generation_remediation_task_store(app)
GENERATION_REMEDIATION_TASK_STORES = {
    "nex-ag": GENERATION_REMEDIATION_TASK_STORE,
}
register_readiness_routes(app)
register_generation_audit_routes(app)
register_generation_quality_disposition_routes(
    app,
    audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
)
register_generation_remediation_task_routes(
    app,
    store=GENERATION_REMEDIATION_TASK_STORE,
    audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
)
register_generation_remediation_execution_routes(
    app,
    store=GENERATION_REMEDIATION_TASK_STORE,
)
register_retrieval_policy_routes(app)
register_cx_processing_run_operation_routes(
    app,
    stores=CX_PROCESSING_RUN_OPERATION_STORES,
    runtime=OPERATIONS_SOURCE_RUNTIME,
)
register_retrieval_package_operation_routes(
    app,
    stores=RETRIEVAL_PACKAGE_OPERATION_STORES,
    runtime=OPERATIONS_SOURCE_RUNTIME,
)
register_remediation_execution_operation_routes(
    app,
    task_stores=GENERATION_REMEDIATION_TASK_STORES,
    execution_stores=REMEDIATION_EXECUTION_OPERATION_STORES,
    runtime=OPERATIONS_SOURCE_RUNTIME,
)
register_operation_source_readiness_routes(app, runtime=OPERATIONS_SOURCE_RUNTIME)
register_unified_operation_routes(
    app,
    event_store=SERVICE_PERSISTENCE.operational_event_store,
    retrieval_package_stores=RETRIEVAL_PACKAGE_OPERATION_STORES,
    cx_processing_run_stores=CX_PROCESSING_RUN_OPERATION_STORES,
    generation_remediation_task_stores=GENERATION_REMEDIATION_TASK_STORES,
    remediation_execution_task_stores=GENERATION_REMEDIATION_TASK_STORES,
    remediation_execution_stores=REMEDIATION_EXECUTION_OPERATION_STORES,
    remediation_execution_projection_builder=(
        build_remediation_execution_operations_projection
    ),
    registry=OPERATIONS_SOURCE_REGISTRY,
    runtime=OPERATIONS_SOURCE_RUNTIME,
)
register_operational_event_taxonomy_routes(app)
if OPERATIONS_SOURCE_REGISTRY is None:
    register_operational_event_routes(
        app,
        store=SERVICE_PERSISTENCE.operational_event_store,
    )
    register_service_log_routes(
        app,
        service_log_stores={"nex-ag": SERVICE_PERSISTENCE.service_log_store},
        audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
    )
else:
    register_operational_event_routes(app, registry=OPERATIONS_SOURCE_REGISTRY)
    register_service_log_routes(
        app,
        registry=OPERATIONS_SOURCE_REGISTRY,
        audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
    )
register_job_operation_routes(
    app,
    event_store=SERVICE_PERSISTENCE.operational_event_store,
    registry=OPERATIONS_SOURCE_REGISTRY,
    audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
)
