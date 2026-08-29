import {
  createFetchArtifactClient,
  createMockArtifactClient
} from "./artifactClient.js";
import {
  createFetchDocumentDetailClient,
  createMockDocumentDetailClient
} from "./documentDetailClient.js";
import {
  createFetchRetrievalClient,
  createMockRetrievalClient
} from "./retrievalClient.js";
import {
  createFetchGenerationFeedbackClient,
  createMockGenerationFeedbackClient
} from "./generationFeedback.js";
import {
  createFetchRepairedResponseReviewClient,
  createMockRepairedResponseReviewClient
} from "./repairedResponseReviewClient.js";
import {
  createFetchRepairedResponseDecisionClient,
  createMockRepairedResponseDecisionClient
} from "./repairedResponseDecisionClient.js";
import {
  createFetchUploadClient,
  createMockUploadClient
} from "./uploadClient.js";

export const AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION = "ae_web_client_registry.v1";
export const AE_WEB_CLIENT_MODES = ["mock", "fetch"];

export class ClientRegistryError extends Error {
  constructor(message, { status = "CLIENT_REGISTRY_INVALID" } = {}) {
    super(message);
    this.name = "ClientRegistryError";
    this.status = status;
  }
}

export function createAeWebClients({
  mode = "mock",
  baseUrl = "",
  fetchImpl,
  documents = [],
  artifacts = [],
  responseFactories = {}
} = {}) {
  const clientMode = normalizeClientMode(mode);
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  const commonFetchOptions = { baseUrl: normalizedBaseUrl, fetchImpl };
  const clients =
    clientMode === "mock"
      ? {
          artifactClient: createMockArtifactClient({
            artifacts,
            previews: responseFactories.artifactPreviews || {},
            downloads: responseFactories.artifactDownloads || {}
          }),
          documentDetailClient: createMockDocumentDetailClient({ documents }),
          uploadClient: createMockUploadClient({
            responseFactory: responseFactories.upload
          }),
          retrievalClient: createMockRetrievalClient({
            responseFactory: responseFactories.retrieval
          }),
          generationFeedbackClient: createMockGenerationFeedbackClient({
            responseFactory: responseFactories.generationFeedback
          }),
          repairedResponseReviewClient: createMockRepairedResponseReviewClient({
            projections: responseFactories.repairedResponseReviewProjections || [],
            responseFactory: responseFactories.repairedResponseReview
          }),
          repairedResponseDecisionClient: createMockRepairedResponseDecisionClient({
            responseFactory: responseFactories.repairedResponseDecision
          })
        }
      : {
          artifactClient: createFetchArtifactClient(commonFetchOptions),
          documentDetailClient: createFetchDocumentDetailClient(commonFetchOptions),
          uploadClient: createFetchUploadClient(commonFetchOptions),
          retrievalClient: createFetchRetrievalClient(commonFetchOptions),
          generationFeedbackClient:
            createFetchGenerationFeedbackClient(commonFetchOptions),
          repairedResponseReviewClient:
            createFetchRepairedResponseReviewClient(commonFetchOptions),
          repairedResponseDecisionClient:
            createFetchRepairedResponseDecisionClient(commonFetchOptions)
        };

  return {
    client_registry_schema_version: AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION,
    clientMode,
    baseUrl: clientMode === "fetch" ? normalizedBaseUrl : "",
    ...clients,
    metadata: {
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      rawSourceIncluded: false
    }
  };
}

export function buildClientRegistrySummary(registry) {
  if (!isRegistry(registry)) {
    throw new ClientRegistryError("Client registry is invalid.", {
      status: "CLIENT_REGISTRY_SUMMARY_INVALID"
    });
  }

  return {
    client_registry_schema_version: registry.client_registry_schema_version,
    client_mode: registry.clientMode,
    base_url: registry.clientMode === "fetch" ? registry.baseUrl : "",
    clients: {
      artifact: registry.artifactClient.clientMode,
      document_detail: registry.documentDetailClient.clientMode,
      upload: registry.uploadClient.clientMode,
      retrieval: registry.retrievalClient.clientMode,
      generation_feedback: registry.generationFeedbackClient.clientMode,
      repaired_response_review: registry.repairedResponseReviewClient.clientMode,
      repaired_response_decision: registry.repairedResponseDecisionClient.clientMode
    },
    metadata: registry.metadata
  };
}

function normalizeClientMode(mode) {
  if (!AE_WEB_CLIENT_MODES.includes(mode)) {
    throw new ClientRegistryError("Unsupported AE Web client mode.", {
      status: "CLIENT_MODE_UNSUPPORTED"
    });
  }
  return mode;
}

function normalizeBaseUrl(baseUrl) {
  if (baseUrl == null || baseUrl === "") return "";
  if (typeof baseUrl !== "string") {
    throw new ClientRegistryError("baseUrl must be a string.", {
      status: "BASE_URL_INVALID"
    });
  }
  return baseUrl.replace(/\/+$/, "");
}

function isRegistry(value) {
  return (
    Boolean(value) &&
    value.client_registry_schema_version === AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION &&
    value.artifactClient &&
    value.documentDetailClient &&
    value.uploadClient &&
    value.retrievalClient &&
    value.generationFeedbackClient &&
    value.repairedResponseReviewClient &&
    value.repairedResponseDecisionClient
  );
}
