from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_oa.auth_boundary import register_identity_auth_boundary_routes
from nex_oa.bootstrap_login_boundary import register_user_bootstrap_login_boundary_routes
from nex_oa.credential_delivery import (
    register_session_credential_delivery_boundary_routes,
)
from nex_oa.credentials import (
    build_credential_registry_for_runtime,
    register_local_credential_routes,
)
from nex_oa.memberships import (
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import (
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)


SERVICE_SPEC = SERVICE_SPECS["nex-oa"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
SUBJECT_REGISTRY = build_subject_registry_for_runtime(SERVICE_PERSISTENCE)
TENANT_MEMBERSHIP_REGISTRY = build_tenant_membership_registry_for_runtime(
    SERVICE_PERSISTENCE,
    subject_registry=SUBJECT_REGISTRY,
)
LOCAL_CREDENTIAL_REGISTRY = build_credential_registry_for_runtime(
    SERVICE_PERSISTENCE,
    subject_registry=SUBJECT_REGISTRY,
)
USER_SESSION_REGISTRY = build_oa_session_registry_for_runtime(
    SERVICE_PERSISTENCE,
    membership_registry=TENANT_MEMBERSHIP_REGISTRY,
)
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
register_subject_registry_routes(app, registry=SUBJECT_REGISTRY)
register_identity_auth_boundary_routes(app)
register_local_credential_routes(app, registry=LOCAL_CREDENTIAL_REGISTRY)
register_identity_membership_routes(app, registry=TENANT_MEMBERSHIP_REGISTRY)
register_user_session_routes(app, registry=USER_SESSION_REGISTRY)
register_session_credential_delivery_boundary_routes(app)
register_user_bootstrap_login_boundary_routes(app)
