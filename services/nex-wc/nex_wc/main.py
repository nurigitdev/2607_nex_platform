import os

from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    build_service_token_admission_runtime,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)

from nex_wc.work_item_api import register_work_item_routes
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.coordination_api import register_coordination_routes
from nex_wc.coordination_clients import HttpAgentCandidateSource, HttpAuthorizationSource
from nex_wc.handoff_delivery import HttpClaimHandoffClient
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
COORDINATION_REPOSITORY = (
    SqlAlchemyCoordinationRepository(SERVICE_PERSISTENCE.api_session_factory)
    if SERVICE_PERSISTENCE.api_session_factory is not None
    else InMemoryCoordinationRepository(WORK_ITEM_REPOSITORY)
)
COORDINATION = WorkCoordinationService(
    COORDINATION_REPOSITORY,
    candidate_source=HttpAgentCandidateSource(
        base_url=os.getenv("NEX_WC_AE_BASE_URL", "http://127.0.0.1:8103"),
        service_token=os.getenv("NEX_WC_TO_AE_SERVICE_TOKEN", ""),
    ),
    authorization_source=HttpAuthorizationSource(
        base_url=os.getenv("NEX_WC_OA_BASE_URL", "http://127.0.0.1:8101"),
        service_token=os.getenv("NEX_WC_TO_OA_SERVICE_TOKEN", ""),
    ),
)
app.state.wc_coordination = COORDINATION
HANDOFF_CLIENT = HttpClaimHandoffClient(
    base_url=os.getenv("NEX_WC_AE_BASE_URL", "http://127.0.0.1:8103"),
    service_token=os.getenv("NEX_WC_TO_AE_SERVICE_TOKEN", ""),
)
app.state.wc_handoff_outbox_store = COORDINATION_REPOSITORY
app.state.wc_handoff_delivery_client = HANDOFF_CLIENT

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
register_coordination_routes(app, service=COORDINATION)
