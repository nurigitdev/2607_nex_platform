export const AE_WEB_FETCH_WORKSPACE_PRESENTATION_SCHEMA_VERSION =
  "ae_web_fetch_workspace_presentation.v1";

export class FetchWorkspacePresentationError extends Error {
  constructor(message, { status = "FETCH_WORKSPACE_PRESENTATION_INVALID" } = {}) {
    super(message);
    this.name = "FetchWorkspacePresentationError";
    this.status = status;
  }
}

export function buildFetchWorkspacePresentation({ documents = [] } = {}) {
  if (!Array.isArray(documents)) {
    throw new FetchWorkspacePresentationError("documents must be an array.");
  }
  const normalizedDocuments = [...documents];
  return {
    presentationSchemaVersion:
      AE_WEB_FETCH_WORKSPACE_PRESENTATION_SCHEMA_VERSION,
    documents: normalizedDocuments,
    selectedDocumentId: normalizedDocuments[0]?.documentId || null,
    messages: [],
    progressEvents: [["workspace.ready", "READY_FOR_PROMPT", "READY"]],
    artifact: {
      handoffStatus: "NOT_REQUIRED",
      title: "",
      targetFormats: [],
      citationStatus: "NOT_REQUIRED",
      evidenceRefCount: 0,
      currentVersionId: null,
      previewRoute: null,
      downloadRoutes: {}
    },
    audit: {
      resultStatus: "NOT_STARTED",
      sourceService: "nex-ae-api",
      compatibilityRuleId: "none",
      providerAlias: "none"
    }
  };
}
