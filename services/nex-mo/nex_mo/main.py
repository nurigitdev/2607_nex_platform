from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    build_service_token_admission_runtime,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)

from nex_mo.catalog_lifecycle_api import register_catalog_lifecycle_routes
from nex_mo.catalog_lifecycle_runtime import build_catalog_lifecycle_service
from nex_mo.catalog_route_source import CatalogProviderRouteSource
from nex_mo.model_rollout_api import register_model_rollout_routes
from nex_mo.model_rollout_runtime import build_model_rollout_service
from nex_mo.mvp_acceptance_api import register_mo_mvp_acceptance_routes
from nex_mo.operations_api import register_operations_routes
from nex_mo.operations_service import MOOperationsService
from nex_mo.provider_readiness_api import register_provider_readiness_routes
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.provider_registry import configure_provider_route_source
from nex_mo.provider_telemetry_runtime import build_provider_telemetry_store
from nex_mo.providers import register_mock_provider_routes
from nex_mo.remote_provider import (
    configure_remote_provider_telemetry_store,
    list_remote_provider_telemetry,
)
from nex_mo.runtime_observability_api import register_runtime_observability_routes
from nex_mo.runtime_observability_service import RuntimeObservabilityService
from nex_mo.trace_projection import (
    MoTraceProjectionSource,
    register_mo_trace_projection_routes,
)

SERVICE_SPEC = SERVICE_SPECS["nex-mo"]
PROVIDER_READINESS = ProviderReadinessService()
RUNTIME_OBSERVABILITY = RuntimeObservabilityService()
SERVICE_TOKEN_ADMISSION = build_service_token_admission_runtime(
    expected_audience=SERVICE_SPEC.service_id
)
app = build_service_app(
    SERVICE_SPEC,
    readiness_checks=(PROVIDER_READINESS.check,),
    service_token_admission=SERVICE_TOKEN_ADMISSION,
)
app.state.provider_readiness_service = PROVIDER_READINESS
app.state.runtime_observability_service = RUNTIME_OBSERVABILITY
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
PROVIDER_TELEMETRY_STORE = build_provider_telemetry_store(SERVICE_PERSISTENCE)
CATALOG_LIFECYCLE = build_catalog_lifecycle_service(SERVICE_PERSISTENCE)
MODEL_ROLLOUTS = build_model_rollout_service(SERVICE_PERSISTENCE)
MO_OPERATIONS = MOOperationsService(
    catalog_service=CATALOG_LIFECYCLE,
    readiness_service=PROVIDER_READINESS,
    runtime_service=RUNTIME_OBSERVABILITY,
    telemetry_reader=list_remote_provider_telemetry,
)
MO_TRACE_PROJECTION_SOURCE = MoTraceProjectionSource(
    SERVICE_PERSISTENCE.operational_event_store
)
configure_provider_route_source(CatalogProviderRouteSource(CATALOG_LIFECYCLE))
configure_remote_provider_telemetry_store(PROVIDER_TELEMETRY_STORE)
app.state.provider_telemetry_store = PROVIDER_TELEMETRY_STORE
app.state.catalog_lifecycle_service = CATALOG_LIFECYCLE
app.state.model_rollout_service = MODEL_ROLLOUTS
app.state.mo_operations_service = MO_OPERATIONS
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
register_mock_provider_routes(app)
register_catalog_lifecycle_routes(app, service=CATALOG_LIFECYCLE)
register_model_rollout_routes(app, service=MODEL_ROLLOUTS)
register_provider_readiness_routes(app, service=PROVIDER_READINESS)
register_runtime_observability_routes(app, service=RUNTIME_OBSERVABILITY)
register_operations_routes(app, service=MO_OPERATIONS)
register_mo_mvp_acceptance_routes(app)
register_mo_trace_projection_routes(app, source=MO_TRACE_PROJECTION_SOURCE)
