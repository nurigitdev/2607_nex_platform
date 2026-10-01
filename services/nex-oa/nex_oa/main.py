from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_oa.auth_boundary import register_identity_auth_boundary_routes
from nex_oa.auth_events import (
    build_auth_event_repository_for_runtime,
    register_auth_event_routes,
)
from nex_oa.bootstrap_login_boundary import register_user_bootstrap_login_boundary_routes
from nex_oa.credential_delivery import (
    register_session_credential_delivery_boundary_routes,
)
from nex_oa.identity_lifecycle_repository import (
    build_identity_lifecycle_repository_for_runtime,
)
from nex_oa.identity_lifecycle_service import (
    OaIdentityLifecycleService,
    register_identity_lifecycle_routes,
)
from nex_oa.credentials import (
    build_credential_registry_for_runtime,
    register_local_credential_routes,
)
from nex_oa.credential_security import (
    build_credential_security_repository_for_runtime,
    register_credential_security_routes,
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
from nex_oa.user_login import OaUserLoginService, register_user_login_routes


SERVICE_SPEC = SERVICE_SPECS["nex-oa"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
AUTH_EVENT_REPOSITORY = build_auth_event_repository_for_runtime(SERVICE_PERSISTENCE)
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
CREDENTIAL_SECURITY_REPOSITORY = build_credential_security_repository_for_runtime(
    SERVICE_PERSISTENCE,
    credential_registry=LOCAL_CREDENTIAL_REGISTRY,
    session_registry=USER_SESSION_REGISTRY,
)
USER_LOGIN_SERVICE = OaUserLoginService(
    credential_registry=LOCAL_CREDENTIAL_REGISTRY,
    session_registry=USER_SESSION_REGISTRY,
)
IDENTITY_LIFECYCLE_REPOSITORY = build_identity_lifecycle_repository_for_runtime(
    SERVICE_PERSISTENCE,
    subject_registry=SUBJECT_REGISTRY,
    membership_registry=TENANT_MEMBERSHIP_REGISTRY,
    session_registry=USER_SESSION_REGISTRY,
)
IDENTITY_LIFECYCLE_SERVICE = OaIdentityLifecycleService(
    subject_registry=SUBJECT_REGISTRY,
    membership_registry=TENANT_MEMBERSHIP_REGISTRY,
    repository=IDENTITY_LIFECYCLE_REPOSITORY,
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
register_credential_security_routes(
    app,
    repository=CREDENTIAL_SECURITY_REPOSITORY,
    auth_event_repository=AUTH_EVENT_REPOSITORY,
)
register_identity_membership_routes(app, registry=TENANT_MEMBERSHIP_REGISTRY)
register_identity_lifecycle_routes(app, service=IDENTITY_LIFECYCLE_SERVICE)
register_user_session_routes(
    app,
    registry=USER_SESSION_REGISTRY,
    auth_event_repository=AUTH_EVENT_REPOSITORY,
)
register_user_login_routes(
    app,
    service=USER_LOGIN_SERVICE,
    auth_event_repository=AUTH_EVENT_REPOSITORY,
)
register_auth_event_routes(app, repository=AUTH_EVENT_REPOSITORY)
register_session_credential_delivery_boundary_routes(app)
register_user_bootstrap_login_boundary_routes(app)
