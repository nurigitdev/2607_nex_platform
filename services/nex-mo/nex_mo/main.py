from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_mo.providers import register_mock_provider_routes
from nex_mo.catalog_lifecycle_api import register_catalog_lifecycle_routes
from nex_mo.catalog_route_source import CatalogProviderRouteSource
from nex_mo.catalog_lifecycle_runtime import build_catalog_lifecycle_service
from nex_mo.provider_readiness_api import register_provider_readiness_routes
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.provider_telemetry_runtime import build_provider_telemetry_store
from nex_mo.provider_registry import configure_provider_route_source
from nex_mo.remote_provider import configure_remote_provider_telemetry_store
from nex_mo.runtime_observability_api import register_runtime_observability_routes
from nex_mo.runtime_observability_service import RuntimeObservabilityService


SERVICE_SPEC = SERVICE_SPECS["nex-mo"]
PROVIDER_READINESS = ProviderReadinessService()
RUNTIME_OBSERVABILITY = RuntimeObservabilityService()
app = build_service_app(
    SERVICE_SPEC,
    readiness_checks=(PROVIDER_READINESS.check,),
)
app.state.provider_readiness_service = PROVIDER_READINESS
app.state.runtime_observability_service = RUNTIME_OBSERVABILITY
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
PROVIDER_TELEMETRY_STORE = build_provider_telemetry_store(SERVICE_PERSISTENCE)
CATALOG_LIFECYCLE = build_catalog_lifecycle_service(SERVICE_PERSISTENCE)
configure_provider_route_source(CatalogProviderRouteSource(CATALOG_LIFECYCLE))
configure_remote_provider_telemetry_store(PROVIDER_TELEMETRY_STORE)
app.state.provider_telemetry_store = PROVIDER_TELEMETRY_STORE
app.state.catalog_lifecycle_service = CATALOG_LIFECYCLE
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
register_provider_readiness_routes(app, service=PROVIDER_READINESS)
register_runtime_observability_routes(app, service=RUNTIME_OBSERVABILITY)
