import {
  createAeWebClients
} from "./clientRegistry.js";
import {
  buildRuntimeConfigSummary,
  normalizeRuntimeConfig
} from "./runtimeConfig.js";

export const AE_WEB_FETCH_MODE_HARNESS_SCHEMA_VERSION =
  "ae_web_fetch_mode_harness.v1";

export class FetchModeHarnessError extends Error {
  constructor(message, { status = "FETCH_MODE_HARNESS_INVALID" } = {}) {
    super(message);
    this.name = "FetchModeHarnessError";
    this.status = status;
  }
}

export async function runFetchModeHarness({
  baseUrl = "/ae-api",
  fetchImpl,
  documents,
  uploadDraft,
  retrievalRequest
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new FetchModeHarnessError("Fetch mode harness requires an injected fetch.", {
      status: "HARNESS_FETCH_REQUIRED"
    });
  }
  const documentId = firstDocumentId(documents);
  const runtimeConfig = normalizeRuntimeConfig({
    client_mode: "fetch",
    ae_base_url: baseUrl,
    features: {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    }
  });
  const registry = createAeWebClients({
    mode: runtimeConfig.clientMode,
    baseUrl: runtimeConfig.aeBaseUrl,
    fetchImpl,
    documents
  });

  const [documentDetail, uploadResult, retrievalResult] = await Promise.all([
    registry.documentDetailClient.getDocumentDetail(documentId),
    registry.uploadClient.submitUploadDraft(uploadDraft),
    registry.retrievalClient.submitRetrievalRequest(retrievalRequest)
  ]);

  return {
    fetch_mode_harness_schema_version: AE_WEB_FETCH_MODE_HARNESS_SCHEMA_VERSION,
    runtime_config: buildRuntimeConfigSummary(runtimeConfig),
    client_mode: registry.clientMode,
    base_url: registry.baseUrl,
    document_detail: {
      document_id: documentDetail.documentId,
      route: documentDetail.detailRoute,
      status: documentDetail.processingStatus,
      client_mode: documentDetail.clientMode
    },
    upload: {
      status: uploadResult.status,
      dedupe_status: uploadResult.dedupeStatus,
      upload_handoff_id: uploadResult.uploadHandoffId,
      document_id: uploadResult.documentId,
      client_mode: uploadResult.clientMode
    },
    retrieval: {
      status: retrievalResult.status,
      cx_status: retrievalResult.cxStatus,
      retrieval_interaction_id: retrievalResult.retrievalInteractionId,
      cx_retrieval_package_id: retrievalResult.cxRetrievalPackageId,
      evidence_count: retrievalResult.evidenceCount,
      client_mode: retrievalResult.clientMode
    },
    metadata: {
      liveNetworkUsed: false,
      browserCredentialIncluded: false,
      rawPromptRendered: false,
      rawSourceIncluded: false,
      sourcePreviewIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

function firstDocumentId(documents) {
  if (!Array.isArray(documents) || documents.length < 1 || !documents[0].documentId) {
    throw new FetchModeHarnessError("Fetch mode harness requires a document item.", {
      status: "HARNESS_DOCUMENT_REQUIRED"
    });
  }
  return documents[0].documentId;
}
