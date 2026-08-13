import {
  createFetchSessionClient
} from "./sessionClient.js";
import {
  ownerScopeFromSessionState
} from "./sessionRouteGuard.js";
import {
  createFetchUploadClient
} from "./uploadClient.js";
import {
  buildUploadSurfaceDraftFromFileMetadata
} from "./uploadSurface.js";

export const AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION =
  "ae_web_authenticated_upload_workflow.v1";

export class AuthenticatedUploadWorkflowError extends Error {
  constructor(message, { status = "AUTHENTICATED_UPLOAD_WORKFLOW_INVALID" } = {}) {
    super(message);
    this.name = "AuthenticatedUploadWorkflowError";
    this.status = status;
  }
}

export async function runAuthenticatedUploadWorkflow({
  baseUrl = "/ae-api",
  fetchImpl,
  sessionClient,
  uploadClient,
  loginRequest,
  workspaceId,
  fileMetadata
} = {}) {
  if (!loginRequest || typeof loginRequest !== "object") {
    throw new AuthenticatedUploadWorkflowError("Login request is required.", {
      status: "LOGIN_REQUEST_REQUIRED"
    });
  }
  if (!workspaceId) {
    throw new AuthenticatedUploadWorkflowError("Workspace id is required.", {
      status: "WORKSPACE_ID_REQUIRED"
    });
  }

  const resolvedSessionClient =
    sessionClient || createFetchSessionClient({ baseUrl, fetchImpl });
  const resolvedUploadClient =
    uploadClient || createFetchUploadClient({ baseUrl, fetchImpl });

  const currentSession = await resolvedSessionClient.getCurrentSession();
  const authenticatedSession = await resolvedSessionClient.login(loginRequest);
  const ownerScope = ownerScopeFromSessionState(authenticatedSession);
  if (!ownerScope) {
    throw new AuthenticatedUploadWorkflowError(
      "Authenticated upload requires OA owner scope.",
      { status: "OWNER_SCOPE_REQUIRED" }
    );
  }

  const uploadDraft = buildUploadSurfaceDraftFromFileMetadata({
    workspaceId,
    fileMetadata,
    ownerScope
  });
  const uploadResult = await resolvedUploadClient.submitUploadDraft(uploadDraft);
  const logoutSession = await resolvedSessionClient.logout();

  return {
    authenticated_upload_workflow_schema_version:
      AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION,
    client_mode: {
      session: resolvedSessionClient.clientMode,
      upload: resolvedUploadClient.clientMode
    },
    base_url: baseUrl,
    current_session: {
      status: currentSession.status,
      reason: currentSession.reason
    },
    authenticated_session: {
      status: authenticatedSession.status,
      tenant_id: ownerScope.tenantId,
      owner_user_id: ownerScope.ownerUserId,
      uploaded_by_user_id: ownerScope.uploadedByUserId,
      scope_count: authenticatedSession.scopes.length
    },
    upload_file_metadata: {
      schema: fileMetadata.upload_file_metadata_schema_version,
      filename: fileMetadata.filename,
      content_type: fileMetadata.contentType,
      size_bytes: fileMetadata.sizeBytes,
      source_sha256_present: Boolean(fileMetadata.sourceSha256),
      file_selected: fileMetadata.fileSelected,
      metadata: fileMetadata.metadata
    },
    upload_draft: {
      workspace_id: uploadDraft.workspaceId,
      route: uploadDraft.uploadRoute,
      status: uploadDraft.status,
      owner_scope_source: "oa_session_claims",
      source_content_included: uploadDraft.metadata.sourceContentIncluded,
      browser_credential_included: uploadDraft.metadata.browserServiceTokenIncluded,
      cx_storage_included: uploadDraft.metadata.cxStorageIncluded
    },
    upload_result: {
      status: uploadResult.status,
      dedupe_status: uploadResult.dedupeStatus,
      upload_handoff_id: uploadResult.uploadHandoffId,
      document_id: uploadResult.documentId,
      route: uploadResult.uploadRoute,
      client_mode: uploadResult.clientMode,
      retryable: uploadResult.retryable,
      metadata: uploadResult.metadata
    },
    logout_session: {
      status: logoutSession.status,
      reason: logoutSession.reason
    },
    checks: {
      current_session_anonymous: currentSession.status === "anonymous",
      authenticated_session_active: authenticatedSession.status === "authenticated",
      owner_scope_from_session_claims: ownerScope.source === "session-claims",
      upload_route_same_origin: uploadResult.uploadRoute === "/api/v1/uploads",
      upload_accepted: ["QUEUED", "ALREADY_EXISTS"].includes(uploadResult.status),
      logout_returns_anonymous: logoutSession.status === "anonymous",
      raw_source_not_included: uploadDraft.metadata.sourceContentIncluded === false,
      browser_credential_not_included:
        uploadDraft.metadata.browserServiceTokenIncluded === false
    }
  };
}

export function buildAuthenticatedUploadWorkflowSummary(workflow) {
  if (
    !workflow ||
    workflow.authenticated_upload_workflow_schema_version !==
      AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION
  ) {
    throw new AuthenticatedUploadWorkflowError("Workflow summary input is invalid.", {
      status: "WORKFLOW_SUMMARY_INVALID"
    });
  }
  return {
    authenticated_upload_workflow_schema_version:
      workflow.authenticated_upload_workflow_schema_version,
    session_client_mode: workflow.client_mode.session,
    upload_client_mode: workflow.client_mode.upload,
    route: workflow.upload_result.route,
    upload_status: workflow.upload_result.status,
    dedupe_status: workflow.upload_result.dedupe_status,
    document_id_present: Boolean(workflow.upload_result.document_id),
    owner_scope_source: workflow.upload_draft.owner_scope_source,
    checks_passed: Object.values(workflow.checks).every(Boolean),
    metadata: {
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false
    }
  };
}
