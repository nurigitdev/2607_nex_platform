import {
  buildDocumentSurface,
  documentDetailRoute
} from "./documentDetailClient.js";

export const AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION =
  "ae_web_document_bootstrap.v1";

export class DocumentBootstrapError extends Error {
  constructor(message, { status = "DOCUMENT_BOOTSTRAP_INVALID" } = {}) {
    super(message);
    this.name = "DocumentBootstrapError";
    this.status = status;
  }
}

export function loadDocumentBootstrap({ windowRef = globalThis } = {}) {
  const source = windowRef?.__NEX_AE_WEB_DOCUMENT_BOOTSTRAP__;
  if (source == null) return null;
  return normalizeDocumentBootstrap(source);
}

export function normalizeDocumentBootstrap(source) {
  if (!isObject(source)) {
    throw new DocumentBootstrapError("Document bootstrap must be an object.");
  }
  rejectUnsupportedFields(source, new Set(["schema_version", "documents"]));
  if (source.schema_version !== AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION) {
    throw new DocumentBootstrapError("Document bootstrap schema is unsupported.", {
      status: "DOCUMENT_BOOTSTRAP_SCHEMA_UNSUPPORTED"
    });
  }
  if (!Array.isArray(source.documents) || source.documents.length < 1) {
    throw new DocumentBootstrapError("Document bootstrap requires documents.", {
      status: "DOCUMENT_BOOTSTRAP_DOCUMENTS_REQUIRED"
    });
  }
  const documents = source.documents.map(normalizeDocument);
  if (new Set(documents.map(item => item.documentId)).size !== documents.length) {
    throw new DocumentBootstrapError("Document bootstrap IDs must be unique.", {
      status: "DOCUMENT_BOOTSTRAP_DUPLICATE_ID"
    });
  }
  return {
    schemaVersion: AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION,
    documents,
    metadata: safeMetadata()
  };
}

export function buildDocumentBootstrapSummary(bootstrap) {
  if (
    !bootstrap ||
    bootstrap.schemaVersion !== AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION ||
    !Array.isArray(bootstrap.documents)
  ) {
    throw new DocumentBootstrapError("Document bootstrap summary is invalid.");
  }
  return {
    schema_version: bootstrap.schemaVersion,
    document_count: bootstrap.documents.length,
    document_ids_present: bootstrap.documents.every(item => Boolean(item.documentId)),
    metadata: bootstrap.metadata
  };
}

function normalizeDocument(source) {
  if (!isObject(source)) {
    throw new DocumentBootstrapError("Document bootstrap item is invalid.");
  }
  rejectUnsupportedFields(source, new Set([
    "document_id",
    "filename",
    "tenant_id",
    "owner_user_id",
    "processing_status",
    "extraction_status",
    "summary_status",
    "confidence_bucket",
    "best_score"
  ]));
  const documentId = requiredText(source.document_id, "document_id");
  const tenantId = requiredText(source.tenant_id, "tenant_id");
  const ownerUserId = requiredText(source.owner_user_id, "owner_user_id");
  const bestScore = source.best_score ?? null;
  if (
    bestScore !== null &&
    (typeof bestScore !== "number" || bestScore < 0 || bestScore > 1)
  ) {
    throw new DocumentBootstrapError("Document bootstrap score is invalid.", {
      status: "DOCUMENT_BOOTSTRAP_SCORE_INVALID"
    });
  }
  return buildDocumentSurface({
    documentId,
    filename: requiredText(source.filename, "filename"),
    detailRoute: documentDetailRoute(documentId),
    ownerScope: { tenantId, ownerUserId },
    sourceService: "nex-cx",
    sourceKind: "postgres-read",
    processingStatus: optionalStatus(source.processing_status, "COMPLETED"),
    extractionStatus: optionalStatus(source.extraction_status, "COMPLETED"),
    summaryStatus: optionalStatus(source.summary_status, "UNKNOWN"),
    confidenceBucket: optionalStatus(source.confidence_bucket, "UNKNOWN"),
    bestScore,
    clientMode: "fetch"
  });
}

function rejectUnsupportedFields(source, allowed) {
  const unsupported = Object.keys(source).find(key => !allowed.has(key));
  if (unsupported) {
    throw new DocumentBootstrapError("Document bootstrap contains an unsupported field.", {
      status: "DOCUMENT_BOOTSTRAP_FIELD_UNSUPPORTED"
    });
  }
}

function requiredText(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new DocumentBootstrapError(`${fieldName} is required.`, {
      status: "DOCUMENT_BOOTSTRAP_TEXT_REQUIRED"
    });
  }
  return value.trim();
}

function optionalStatus(value, fallback) {
  if (value == null || value === "") return fallback;
  return requiredText(value, "status");
}

function safeMetadata() {
  return {
    rawSourceIncluded: false,
    generatedContentIncluded: false,
    browserServiceTokenIncluded: false,
    providerUrlIncluded: false,
    databaseUrlIncluded: false,
    storageRefIncluded: false
  };
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
