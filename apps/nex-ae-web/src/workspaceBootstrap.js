export const AE_WEB_WORKSPACE_BOOTSTRAP_SCHEMA_VERSION =
  "ae_web_workspace_bootstrap.v1";

export class WorkspaceBootstrapError extends Error {
  constructor(message, { status = "WORKSPACE_BOOTSTRAP_INVALID" } = {}) {
    super(message);
    this.name = "WorkspaceBootstrapError";
    this.status = status;
  }
}

export function loadWorkspaceBootstrap({ windowRef = globalThis } = {}) {
  const source = windowRef?.__NEX_AE_WEB_WORKSPACE_BOOTSTRAP__;
  if (source == null) return null;
  if (!isObject(source)) {
    throw new WorkspaceBootstrapError("Workspace bootstrap must be an object.");
  }
  const allowed = new Set(["schema_version", "workspace_id", "chat_document_id"]);
  if (Object.keys(source).some(key => !allowed.has(key))) {
    throw new WorkspaceBootstrapError(
      "Workspace bootstrap contains an unsupported field.",
      { status: "WORKSPACE_BOOTSTRAP_FIELD_UNSUPPORTED" }
    );
  }
  if (source.schema_version !== AE_WEB_WORKSPACE_BOOTSTRAP_SCHEMA_VERSION) {
    throw new WorkspaceBootstrapError("Workspace bootstrap schema is unsupported.", {
      status: "WORKSPACE_BOOTSTRAP_SCHEMA_UNSUPPORTED"
    });
  }
  return {
    schemaVersion: AE_WEB_WORKSPACE_BOOTSTRAP_SCHEMA_VERSION,
    workspaceId: requiredText(source.workspace_id, "workspace_id"),
    chatDocumentId: requiredText(source.chat_document_id, "chat_document_id"),
    metadata: {
      ownerIdentityIncluded: false,
      browserServiceTokenIncluded: false,
      databaseUrlIncluded: false
    }
  };
}

function requiredText(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new WorkspaceBootstrapError(`${fieldName} is required.`, {
      status: "WORKSPACE_BOOTSTRAP_TEXT_REQUIRED"
    });
  }
  return value.trim();
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
