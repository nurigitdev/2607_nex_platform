from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    build_service_token_admission_runtime,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)

from nex_wc.work_item_api import register_work_item_routes
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)


SERVICE_SPEC = SERVICE_SPECS["nex-wc"]
SERVICE_TOKEN_ADMISSION = build_service_token_admission_runtime(
    expected_audience=SERVICE_SPEC.service_id
)
app = build_service_app(
    SERVICE_SPEC,
    service_token_admission=SERVICE_TOKEN_ADMISSION,
)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
WORK_ITEM_REPOSITORY = (
    SqlAlchemyWorkItemRepository(SERVICE_PERSISTENCE.api_session_factory)
    if SERVICE_PERSISTENCE.api_session_factory is not None
    else InMemoryWorkItemRepository()
)
WORK_ITEMS = WorkItemService(WORK_ITEM_REPOSITORY)
app.state.wc_work_items = WORK_ITEMS

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
register_work_item_routes(app, service=WORK_ITEMS)
