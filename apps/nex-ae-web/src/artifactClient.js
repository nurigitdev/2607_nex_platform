export const AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION =
  "ae_web_artifact_client.v1";
export const AE_ARTIFACT_RECORD_SCHEMA_VERSION = "ae_artifact_record.v1";
export const AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION =
  "ae_artifact_file_preview.v1";
export const AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION =
  "ae_artifact_file_download.v1";
export const AE_WEB_ARTIFACT_EXPORT_REQUEST_SCHEMA_VERSION =
  "ae_web_artifact_export_request.v1";
export const AE_WEB_ARTIFACT_EXPORT_SURFACE_SCHEMA_VERSION =
  "ae_web_artifact_export_surface.v1";
export const AE_ARTIFACT_COLLECTION_SCHEMA_VERSION = "ae_artifact_collection.v1";
export const AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION =
  "ae_artifact_collection_item.v1";
export const AE_WEB_ARTIFACT_COLLECTION_SURFACE_SCHEMA_VERSION =
  "ae_web_artifact_collection_surface.v1";
export const AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION =
  "ae_artifact_lifecycle_action.v1";
export const AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION =
  "ae_artifact_lifecycle_action_result.v1";
export const AE_WEB_ARTIFACT_LIFECYCLE_ACTION_REQUEST_SCHEMA_VERSION =
  "ae_web_artifact_lifecycle_action_request.v1";
export const AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SURFACE_SCHEMA_VERSION =
  "ae_web_artifact_lifecycle_action_surface.v1";

const SUPPORTED_ARTIFACT_EXPORT_FORMATS = ["MD", "HTML_PREVIEW", "DOCX", "PDF"];
const SUPPORTED_ARTIFACT_LIFECYCLE_ACTIONS = [
  "ARCHIVE",
  "RESTORE",
  "MARK_DELETED"
];
const ARTIFACT_RESTORABLE_STATUSES = ["DRAFT", "READY", "FAILED"];
const ARTIFACT_ARCHIVABLE_STATUSES = ["DRAFT", "READY", "FAILED"];
const ARTIFACT_DELETABLE_STATUSES = ["DRAFT", "READY", "FAILED", "ARCHIVED"];
const ARTIFACT_RESTORE_SOURCE_STATUSES = ["ARCHIVED", "DELETED"];
const DEFAULT_ARTIFACT_RESTORE_STATUS = "READY";
const DEFAULT_ARTIFACT_LIFECYCLE_REASON_CODE = "user_requested";
const SUPPORTED_ARTIFACT_COLLECTION_STATUSES = [
  "DRAFT",
  "RENDERING",
  "READY",
  "FAILED",
  "ARCHIVED",
  "DELETED"
];
const DEFAULT_ARTIFACT_COLLECTION_LIMIT = 20;
const MAX_ARTIFACT_COLLECTION_LIMIT = 100;
const TEXT_DOWNLOAD_CONTENT_ENCODING = "utf-8";
const BASE64_DOWNLOAD_CONTENT_ENCODING = "base64";

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "credential",
  "database_url",
  "model_path",
  "password",
  "passwd",
  "provider_endpoint",
  "provider_url",
  "raw_prompt",
  "raw_source",
  "raw_text",
  "secret",
  "service_token",
  "source_text",
  "storage_path",
  "storage_ref",
  "token"
];

const ALLOWED_FALSE_SENSITIVE_FLAGS = [
  "browserServiceTokenIncluded",
  "databaseEndpointIncluded",
  "providerEndpointIncluded",
  "rawPromptIncluded",
  "rawSourceIncluded",
  "storageLocationIncluded"
];

const SENSITIVE_VALUE_PATTERNS = [
  /postgresql\+?[^"'\s]+/i,
  /\/data\/nex-platform/i,
  /ed6@c496em/i,
  /nuri1004/i
];

export class ArtifactClientError extends Error {
  constructor(message, { status = "ARTIFACT_CLIENT_ERROR", retryable = false } = {}) {
    super(message);
    this.name = "ArtifactClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function artifactDetailRoute(artifactId) {
  return `/api/v1/artifacts/${encodeURIComponent(requiredText(artifactId, "artifact_id"))}`;
}

export function artifactVersionsRoute(artifactId) {
  return `${artifactDetailRoute(artifactId)}/versions`;
}

export function artifactRenderJobRoute(artifactId) {
  return `${artifactDetailRoute(artifactId)}/render-jobs`;
}

export function artifactLifecycleActionRoute(artifactId) {
  return `${artifactDetailRoute(artifactId)}/lifecycle-actions`;
}

export function artifactFileMetadataRoute(artifactFileId) {
  return `/api/v1/artifact-files/${encodeURIComponent(requiredText(artifactFileId, "artifact_file_id"))}`;
}

export function artifactFilePreviewRoute(artifactFileId) {
  return `${artifactFileMetadataRoute(artifactFileId)}/preview`;
}

export function artifactFileDownloadRoute(artifactFileId) {
  return `${artifactFileMetadataRoute(artifactFileId)}/download`;
}

export function artifactCollectionRoute(query = {}) {
  const collectionQuery = buildArtifactCollectionQuery(query);
  const params = new URLSearchParams();
  params.set("tenant_id", collectionQuery.tenant_id);
  params.set("workspace_id", collectionQuery.workspace_id);
  params.set("owner_user_id", collectionQuery.owner_user_id);
  if (collectionQuery.status) params.set("status", collectionQuery.status);
  params.set("limit", String(collectionQuery.limit));
  return `/api/v1/artifacts?${params.toString()}`;
}

export function createMockArtifactClient({
  artifacts = [],
  previews = {},
  downloads = {}
} = {}) {
  const records = new Map(
    artifacts.map(record => [
      requiredText(record?.artifact_id, "artifact_id"),
      clone(record)
    ])
  );

  return {
    clientMode: "mock",
    async listArtifacts(query = {}) {
      const collectionQuery = buildArtifactCollectionQuery(query);
      const route = artifactCollectionRoute(collectionQuery);
      const payload = buildMockArtifactCollectionPayload(
        [...records.values()],
        collectionQuery
      );
      return buildArtifactCollectionSurface(payload, {
        clientMode: "mock",
        route
      });
    },
    async getArtifact(artifactId) {
      const route = artifactDetailRoute(artifactId);
      const record = records.get(String(artifactId));
      if (!record) {
        throw new ArtifactClientError("Artifact was not found.", {
          status: "NOT_FOUND"
        });
      }
      return buildArtifactSurfaceFromRecord(record, { clientMode: "mock", route });
    },
    async listArtifactVersions(artifactId) {
      const route = artifactVersionsRoute(artifactId);
      const record = records.get(String(artifactId));
      if (!record) {
        throw new ArtifactClientError("Artifact was not found.", {
          status: "NOT_FOUND"
        });
      }
      return buildArtifactVersionsSurface(
        {
          artifact_id: record.artifact_id,
          current_version_id: record.current_version_id || null,
          versions: Array.isArray(record.versions) ? record.versions : []
        },
        { clientMode: "mock", route }
      );
    },
    async getArtifactFile(artifactFileId) {
      const route = artifactFileMetadataRoute(artifactFileId);
      const artifactFile = findArtifactFile(records, artifactFileId);
      if (!artifactFile) {
        throw new ArtifactClientError("Artifact file was not found.", {
          status: "NOT_FOUND"
        });
      }
      return buildArtifactFileSurface(artifactFile, { clientMode: "mock", route });
    },
    async previewArtifactFile(artifactFileId) {
      const route = artifactFilePreviewRoute(artifactFileId);
      const artifactFile = findArtifactFile(records, artifactFileId);
      if (!artifactFile) {
        throw new ArtifactClientError("Artifact file was not found.", {
          status: "NOT_FOUND"
        });
      }
      const payload =
        previews[String(artifactFileId)] ||
        buildMockPreviewPayload(artifactFile, findArtifactLink(records, artifactFileId, "preview"));
      return buildArtifactPreviewSurface(payload, { clientMode: "mock", route });
    },
    async downloadArtifactFile(artifactFileId) {
      const route = artifactFileDownloadRoute(artifactFileId);
      const artifactFile = findArtifactFile(records, artifactFileId);
      if (!artifactFile) {
        throw new ArtifactClientError("Artifact file was not found.", {
          status: "NOT_FOUND"
        });
      }
      const payload =
        downloads[String(artifactFileId)] ||
        buildMockDownloadPayload(
          artifactFile,
          findArtifactLink(records, artifactFileId, "download")
        );
      return buildArtifactDownloadSurface(payload, { clientMode: "mock", route });
    },
    async submitArtifactExportRequest(requestPayload) {
      const exportRequest = buildArtifactExportRequest(requestPayload);
      const record = records.get(exportRequest.artifact_id);
      if (!record) {
        throw new ArtifactClientError("Artifact was not found.", {
          status: "NOT_FOUND"
        });
      }
      const payload = materializeMockArtifactExport(record, exportRequest);
      records.set(exportRequest.artifact_id, payload.artifact);
      return buildArtifactExportSurface(payload, {
        clientMode: "mock",
        route: exportRequest.route,
        requestedFormats: exportRequest.target_formats
      });
    },
    async submitArtifactLifecycleAction(requestPayload) {
      const lifecycleRequest = buildArtifactLifecycleActionRequest(requestPayload);
      const record = records.get(lifecycleRequest.artifact_id);
      if (!record) {
        throw new ArtifactClientError("Artifact was not found.", {
          status: "NOT_FOUND"
        });
      }
      const payload = materializeMockArtifactLifecycleAction(record, lifecycleRequest);
      records.set(lifecycleRequest.artifact_id, payload.artifact);
      return buildArtifactLifecycleActionSurface(payload.result, {
        clientMode: "mock",
        route: lifecycleRequest.route
      });
    }
  };
}

export function createFetchArtifactClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new ArtifactClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async listArtifacts(query = {}) {
      const route = artifactCollectionRoute(query);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactCollectionSurface(payload, {
        clientMode: "fetch",
        route
      });
    },
    async getArtifact(artifactId) {
      const route = artifactDetailRoute(artifactId);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactSurfaceFromRecord(payload, { clientMode: "fetch", route });
    },
    async listArtifactVersions(artifactId) {
      const route = artifactVersionsRoute(artifactId);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactVersionsSurface(payload, { clientMode: "fetch", route });
    },
    async getArtifactFile(artifactFileId) {
      const route = artifactFileMetadataRoute(artifactFileId);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactFileSurface(payload, { clientMode: "fetch", route });
    },
    async previewArtifactFile(artifactFileId) {
      const route = artifactFilePreviewRoute(artifactFileId);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactPreviewSurface(payload, { clientMode: "fetch", route });
    },
    async downloadArtifactFile(artifactFileId) {
      const route = artifactFileDownloadRoute(artifactFileId);
      const payload = await fetchArtifactJson(request, `${baseUrl}${route}`);
      return buildArtifactDownloadSurface(payload, { clientMode: "fetch", route });
    },
    async submitArtifactExportRequest(requestPayload) {
      const exportRequest = buildArtifactExportRequest(requestPayload);
      const payload = await fetchArtifactJson(
        request,
        `${baseUrl}${exportRequest.route}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": exportRequest.idempotency_key
          },
          body: JSON.stringify({
            render_request_id: exportRequest.render_request_id,
            target_formats: exportRequest.target_formats
          })
        }
      );
      return buildArtifactExportSurface(payload, {
        clientMode: "fetch",
        route: exportRequest.route,
        requestedFormats: exportRequest.target_formats
      });
    },
    async submitArtifactLifecycleAction(requestPayload) {
      const lifecycleRequest = buildArtifactLifecycleActionRequest(requestPayload);
      const payload = await fetchArtifactJson(
        request,
        `${baseUrl}${lifecycleRequest.route}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": lifecycleRequest.idempotency_key
          },
          body: JSON.stringify(lifecycleRequest.body)
        }
      );
      return buildArtifactLifecycleActionSurface(payload, {
        clientMode: "fetch",
        route: lifecycleRequest.route
      });
    }
  };
}

export function buildArtifactCollectionQuery({
  tenantId,
  tenant_id,
  workspaceId,
  workspace_id,
  ownerUserId,
  owner_user_id,
  status = null,
  limit = null
} = {}) {
  return {
    tenant_id: requiredText(tenantId ?? tenant_id, "tenant_id"),
    workspace_id: requiredText(workspaceId ?? workspace_id, "workspace_id"),
    owner_user_id: requiredText(ownerUserId ?? owner_user_id, "owner_user_id"),
    status: normalizeArtifactCollectionStatus(status),
    limit: normalizeArtifactCollectionLimit(limit)
  };
}

export function buildArtifactExportRequest({
  artifactId,
  artifact_id,
  targetFormats,
  target_formats,
  renderRequestId,
  render_request_id
} = {}) {
  const normalizedArtifactId = requiredText(
    artifactId || artifact_id,
    "artifact_id"
  );
  const normalizedTargetFormats = normalizeExportFormats(
    targetFormats || target_formats || ["MD"]
  );
  const normalizedRenderRequestId =
    optionalText(renderRequestId || render_request_id) ||
    deterministicExportRequestId(normalizedArtifactId, normalizedTargetFormats);
  return {
    artifact_export_request_schema_version:
      AE_WEB_ARTIFACT_EXPORT_REQUEST_SCHEMA_VERSION,
    artifact_id: normalizedArtifactId,
    render_request_id: normalizedRenderRequestId,
    idempotency_key: normalizedRenderRequestId,
    target_formats: normalizedTargetFormats,
    route: artifactRenderJobRoute(normalizedArtifactId),
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
}

export function buildArtifactLifecycleActionRequest({
  artifactId,
  artifact_id,
  action,
  lifecycle_action,
  restoreStatus,
  restore_status,
  reasonCode,
  reason_code,
  comment,
  idempotencyKey,
  idempotency_key,
  lifecycleActionRequestId,
  lifecycle_action_request_id
} = {}) {
  const normalizedArtifactId = requiredText(
    artifactId || artifact_id,
    "artifact_id"
  );
  const normalizedAction = normalizeArtifactLifecycleAction(
    action || lifecycle_action
  );
  const restoreStatusProvided =
    restoreStatus != null || restore_status != null;
  const normalizedRestoreStatus = normalizeArtifactRestoreStatus(
    restoreStatus ?? restore_status
  );
  if (normalizedAction !== "RESTORE" && restoreStatusProvided) {
    throw new ArtifactClientError(
      "restore_status is only supported for RESTORE lifecycle actions.",
      { status: "ARTIFACT_LIFECYCLE_RESTORE_STATUS_UNSUPPORTED" }
    );
  }
  const targetStatus = artifactLifecycleTargetStatus({
    action: normalizedAction,
    restoreStatus: normalizedRestoreStatus
  });
  const normalizedReasonCode = normalizeLifecycleReasonCode(
    reasonCode ?? reason_code
  );
  const commentText = optionalText(comment);
  const idempotencyKeyValue =
    optionalText(
      idempotencyKey || idempotency_key || lifecycleActionRequestId ||
        lifecycle_action_request_id
    ) ||
    deterministicLifecycleRequestId(
      normalizedArtifactId,
      normalizedAction,
      targetStatus
    );
  const body = {
    action: normalizedAction,
    reason_code: normalizedReasonCode
  };
  if (normalizedAction === "RESTORE") {
    body.restore_status = targetStatus;
  }
  if (commentText) {
    body.comment = commentText;
  }

  return {
    artifact_lifecycle_action_request_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_REQUEST_SCHEMA_VERSION,
    artifact_id: normalizedArtifactId,
    action: normalizedAction,
    target_status: targetStatus,
    restore_status: normalizedAction === "RESTORE" ? targetStatus : null,
    reason_code: normalizedReasonCode,
    comment_length: commentText ? commentText.length : 0,
    idempotency_key: idempotencyKeyValue,
    route: artifactLifecycleActionRoute(normalizedArtifactId),
    body,
    metadata: {
      contentIncluded: false,
      binaryContentIncluded: false,
      previewTextIncluded: false,
      commentBodyIncluded: Boolean(commentText),
      rawCommentSurfaceIncluded: false,
      physicalDeleteRequested: false,
      storageMutationRequested: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function buildArtifactCollectionSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(payload) ||
    payload.artifact_collection_schema_version !==
      AE_ARTIFACT_COLLECTION_SCHEMA_VERSION ||
    !Array.isArray(payload.items)
  ) {
    throw new ArtifactClientError("Artifact collection response is invalid.", {
      status: "ARTIFACT_COLLECTION_INVALID"
    });
  }
  const filter = buildArtifactCollectionQuery(payload.filter || {});
  const items = payload.items.map(buildArtifactCollectionItemSurface);
  const surface = {
    artifact_collection_surface_schema_version:
      AE_WEB_ARTIFACT_COLLECTION_SURFACE_SCHEMA_VERSION,
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    artifact_collection_schema_version: payload.artifact_collection_schema_version,
    filter,
    count: numberOrZero(payload.count),
    itemCount: items.length,
    limit: normalizeArtifactCollectionLimit(payload.limit ?? filter.limit),
    nextCursor: optionalText(payload.next_cursor) || null,
    items,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactCollectionItemSurface(item) {
  if (!isObject(item)) {
    throw new ArtifactClientError("Artifact collection item is invalid.", {
      status: "ARTIFACT_COLLECTION_ITEM_INVALID"
    });
  }
  const itemSchema =
    optionalText(item.artifact_collection_item_schema_version) ||
    AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION;
  if (itemSchema !== AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION) {
    throw new ArtifactClientError("Artifact collection item schema is invalid.", {
      status: "ARTIFACT_COLLECTION_ITEM_SCHEMA_INVALID"
    });
  }
  const artifactId = requiredText(item.artifact_id, "artifact_id");
  const surface = {
    artifact_collection_item_schema_version: itemSchema,
    artifactId,
    displayTitle: optionalText(item.display_title) || "Untitled artifact",
    artifactType: optionalText(item.artifact_type) || "generated_document",
    artifactStatus: optionalText(item.artifact_status) || "UNKNOWN",
    language: optionalText(item.language) || null,
    artifactIntent: optionalText(item.artifact_intent) || null,
    targetFormats: normalizeTextList(item.target_formats),
    availableFormats: normalizeTextList(item.available_formats),
    downloadableFormats: normalizeTextList(item.downloadable_formats),
    previewableFormats: normalizeTextList(item.previewable_formats),
    currentVersionId: optionalText(item.current_version_id) || null,
    currentVersionNo: numberOrNull(item.current_version_no),
    versionCount: numberOrZero(item.version_count),
    fileCount: numberOrZero(item.file_count),
    linkCount: numberOrZero(item.link_count),
    renderJobCount: numberOrZero(item.render_job_count),
    latestRenderJob: normalizeArtifactCollectionRenderJob(item.latest_render_job),
    sourceSummary: normalizeArtifactCollectionSourceSummary(item.source_summary),
    qualitySummary: normalizeArtifactCollectionQualitySummary(item.quality_summary),
    routes: normalizeArtifactCollectionRoutes(item.routes, artifactId),
    ownerScope: {
      tenantId: optionalText(item.tenant_id) || null,
      workspaceId: optionalText(item.workspace_id) || null,
      ownerUserId: optionalText(item.owner_user_id) || null
    },
    chatDocumentId: optionalText(item.chat_document_id) || null,
    interactionId: optionalText(item.interaction_id) || null,
    createdAt: optionalText(item.created_at) || null,
    updatedAt: optionalText(item.updated_at) || null,
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactSurfaceFromRecord(
  record,
  { clientMode = "mock", route = null } = {}
) {
  if (!isObject(record)) {
    throw new ArtifactClientError("Artifact record is invalid.", {
      status: "ARTIFACT_RECORD_INVALID"
    });
  }
  const files = normalizeArtifactFiles(record.files);
  const links = normalizeArtifactLinks(record.links);
  const currentVersionId = optionalText(record.current_version_id);
  const currentFile =
    files.find(file => file.artifactVersionId === currentVersionId) ||
    files[0] ||
    null;
  const sourceRef = Array.isArray(record.source_refs) ? record.source_refs[0] || {} : {};
  const qualitySummary = isObject(sourceRef.quality_summary)
    ? sourceRef.quality_summary
    : {};
  const surface = {
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    artifact_record_schema_version:
      optionalText(record.artifact_schema_version) || AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifactId: requiredText(record.artifact_id, "artifact_id"),
    artifactVersionId: currentVersionId || null,
    displayTitle: optionalText(record.display_title) || "Untitled artifact",
    artifactType: optionalText(record.artifact_type) || "generated_document",
    artifactStatus: optionalText(record.artifact_status) || "UNKNOWN",
    primaryFormat:
      optionalText(currentFile?.format) ||
      firstText(record.target_formats) ||
      "UNKNOWN",
    availableFormats: availableFormats(files, record.target_formats),
    chatDocumentId: optionalText(record.chat_document_id) || null,
    interactionId: optionalText(record.interaction_id) || null,
    sourceGenerationId: optionalText(sourceRef.cx_generation_id) || null,
    sourceContentHash:
      optionalText(currentVersion(record.versions, currentVersionId)?.source_content_hash) ||
      optionalText(sourceRef.structured_draft_content_hash) ||
      null,
    previewRoute: routeForLink(links, currentFile, "preview"),
    downloadRoutes: downloadRoutesForLinks(links, files),
    files,
    links,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    qualitySummary: {
      citationStatus: optionalText(qualitySummary.citation_status) || "UNKNOWN",
      citationCount: numberOrZero(qualitySummary.citation_count),
      evidenceRefCount: numberOrZero(
        qualitySummary.evidence_ref_count ?? sourceRef.evidence_ref_count
      ),
      groundingRequired: Boolean(qualitySummary.grounding_required),
      retrievalPackageId: optionalText(
        qualitySummary.retrieval_package_id ?? sourceRef.retrieval_package_id
      )
    },
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactVersionsSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (!isObject(payload) || !Array.isArray(payload.versions)) {
    throw new ArtifactClientError("Artifact versions response is invalid.", {
      status: "ARTIFACT_VERSIONS_INVALID"
    });
  }
  const surface = {
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    artifactId: requiredText(payload.artifact_id, "artifact_id"),
    currentVersionId: optionalText(payload.current_version_id) || null,
    versions: payload.versions.map(version => ({
      artifactVersionId: optionalText(version.artifact_version_id) || null,
      versionNo: version.version_no ?? null,
      sourceContentHash: optionalText(version.source_content_hash) || null,
      artifactContentHash: optionalText(version.artifact_content_hash) || null,
      renderedFormats: Array.isArray(version.rendered_formats)
        ? version.rendered_formats.map(String)
        : []
    })),
    versionCount: payload.versions.length,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactFileSurface(
  artifactFile,
  { clientMode = "mock", route = null } = {}
) {
  const normalized = normalizeArtifactFile(artifactFile);
  const surface = {
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    ...normalized,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactPreviewSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(payload) ||
    payload.preview_schema_version !== AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact preview response is invalid.", {
      status: "ARTIFACT_PREVIEW_INVALID"
    });
  }
  const surface = {
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    previewSchemaVersion: payload.preview_schema_version,
    artifactFile: buildArtifactFileSurface(payload.artifact_file, {
      clientMode,
      route: null
    }),
    artifactLink: normalizeArtifactLink(payload.artifact_link),
    contentType: optionalText(payload.content_type) || "text/plain",
    textPreview: optionalText(payload.text_preview) || "",
    truncated: Boolean(payload.truncated),
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: false, previewTextIncluded: true })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactDownloadSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(payload) ||
    payload.download_schema_version !== AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact download response is invalid.", {
      status: "ARTIFACT_DOWNLOAD_INVALID"
    });
  }
  const downloadContent = normalizeDownloadContent(payload);
  const surface = {
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    downloadSchemaVersion: payload.download_schema_version,
    artifactFile: buildArtifactFileSurface(payload.artifact_file, {
      clientMode,
      route: null
    }),
    artifactLink: normalizeArtifactLink(payload.artifact_link),
    downloadFileName: optionalText(payload.download_file_name) || "artifact.md",
    contentType: optionalText(payload.content_type) || "application/octet-stream",
    contentHash: optionalText(payload.content_hash) || null,
    content: downloadContent.content,
    contentBase64: downloadContent.contentBase64,
    contentEncoding: downloadContent.contentEncoding,
    downloadPayloadKind: downloadContent.downloadPayloadKind,
    contentLength: downloadContent.contentLength,
    encodedContentLength: downloadContent.encodedContentLength,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({
      contentIncluded: downloadContent.downloadPayloadKind === "text",
      binaryContentIncluded: downloadContent.downloadPayloadKind === "base64",
      previewTextIncluded: false
    })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactExportSurface(
  payload,
  { clientMode = "mock", route = null, requestedFormats = [] } = {}
) {
  if (
    !isObject(payload) ||
    payload.render_result_schema_version !== "ae_markdown_render_result.v1" ||
    !isObject(payload.render_job) ||
    !isObject(payload.artifact)
  ) {
    throw new ArtifactClientError("Artifact export response is invalid.", {
      status: "ARTIFACT_EXPORT_INVALID"
    });
  }
  const artifactSurface = buildArtifactSurfaceFromRecord(payload.artifact, {
    clientMode,
    route: artifactDetailRoute(payload.artifact.artifact_id)
  });
  const renderJob = payload.render_job;
  const renderedFormats =
    currentVersion(payload.artifact.versions, payload.artifact.current_version_id)
      ?.rendered_formats || artifactSurface.availableFormats;
  const surface = {
    artifact_export_schema_version:
      AE_WEB_ARTIFACT_EXPORT_SURFACE_SCHEMA_VERSION,
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    renderResultSchemaVersion: payload.render_result_schema_version,
    artifactId: artifactSurface.artifactId,
    artifactVersionId: artifactSurface.artifactVersionId,
    renderJobId: requiredText(renderJob.render_job_id, "render_job_id"),
    jobStatus: optionalText(renderJob.job_status) || "UNKNOWN",
    currentStage: optionalText(renderJob.current_stage) || "UNKNOWN",
    progressPercent: numberOrZero(renderJob.progress_percent),
    requestedFormats: normalizeExportFormats(
      requestedFormats.length > 0 ? requestedFormats : renderedFormats
    ),
    renderedFormats: normalizeExportFormats(renderedFormats),
    artifactSurface,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactExportSummary(surface) {
  if (
    !isObject(surface) ||
    surface.artifact_export_schema_version !==
      AE_WEB_ARTIFACT_EXPORT_SURFACE_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact export summary is invalid.", {
      status: "ARTIFACT_EXPORT_SUMMARY_INVALID"
    });
  }
  const summary = {
    artifact_export_schema_version: surface.artifact_export_schema_version,
    artifact_id: surface.artifactId,
    artifact_version_id: surface.artifactVersionId,
    render_job_id: surface.renderJobId,
    job_status: surface.jobStatus,
    current_stage: surface.currentStage,
    requested_format_count: surface.requestedFormats.length,
    rendered_format_count: surface.renderedFormats.length,
    route_present: Boolean(surface.route),
    client_mode: surface.clientMode,
    metadata: surface.metadata
  };
  assertArtifactClientSurfaceSafe(summary);
  return summary;
}

export function buildArtifactLifecycleActionSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(payload) ||
    payload.artifact_lifecycle_action_result_schema_version !==
      AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION ||
    !isObject(payload.lifecycle_action)
  ) {
    throw new ArtifactClientError("Artifact lifecycle action response is invalid.", {
      status: "ARTIFACT_LIFECYCLE_RESULT_INVALID"
    });
  }
  const lifecycleAction = normalizeLifecycleActionForSurface(
    payload.lifecycle_action
  );
  const routes = normalizeArtifactLifecycleRoutes(
    payload.routes,
    payload.artifact_id
  );
  const metadata = normalizeLifecycleResultMetadata(
    payload.metadata,
    lifecycleAction.metadata
  );
  const surface = {
    artifact_lifecycle_action_surface_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SURFACE_SCHEMA_VERSION,
    artifact_client_schema_version: AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
    artifact_lifecycle_action_result_schema_version:
      payload.artifact_lifecycle_action_result_schema_version,
    artifact_lifecycle_action_schema_version:
      lifecycleAction.artifact_lifecycle_action_schema_version,
    lifecycleActionId: lifecycleAction.lifecycle_action_id,
    artifactId: requiredText(payload.artifact_id, "artifact_id"),
    action: lifecycleAction.action,
    previousStatus: normalizeArtifactLifecycleStatus(payload.previous_status),
    targetStatus: normalizeArtifactLifecycleTerminalOrRestorableStatus(
      payload.target_status
    ),
    artifactStatus: normalizeArtifactLifecycleStatus(payload.artifact_status),
    restoreStatus: lifecycleAction.restore_status,
    reasonCode: lifecycleAction.reason_code,
    commentHashPresent: Boolean(lifecycleAction.comment_hash),
    commentLength: lifecycleAction.comment_length,
    actorScope: lifecycleAction.actor_ref,
    requestId: lifecycleAction.request_id,
    traceId: lifecycleAction.trace_id,
    idempotencyKey: lifecycleAction.idempotency_key,
    transitionApplied: Boolean(payload.transition_applied),
    routes,
    updatedAt: optionalText(payload.updated_at) || null,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata
  };
  assertLifecycleSurfaceMatchesAction(surface, lifecycleAction);
  assertArtifactClientSurfaceSafe(surface);
  return surface;
}

export function buildArtifactLifecycleActionSummary(surface) {
  if (
    !isObject(surface) ||
    surface.artifact_lifecycle_action_surface_schema_version !==
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SURFACE_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact lifecycle action summary is invalid.", {
      status: "ARTIFACT_LIFECYCLE_SUMMARY_INVALID"
    });
  }
  const summary = {
    artifact_lifecycle_action_surface_schema_version:
      surface.artifact_lifecycle_action_surface_schema_version,
    artifact_lifecycle_action_result_schema_version:
      surface.artifact_lifecycle_action_result_schema_version,
    artifact_id: surface.artifactId,
    action: surface.action,
    previous_status: surface.previousStatus,
    target_status: surface.targetStatus,
    artifact_status: surface.artifactStatus,
    restore_status: surface.restoreStatus,
    transition_applied: Boolean(surface.transitionApplied),
    comment_hash_present: Boolean(surface.commentHashPresent),
    comment_length: numberOrZero(surface.commentLength),
    route_present: Boolean(surface.route),
    artifact_route_present: Boolean(surface.routes?.artifact),
    collection_route_present: Boolean(surface.routes?.collection),
    client_mode: surface.clientMode,
    metadata: surface.metadata
  };
  assertArtifactClientSurfaceSafe(summary);
  return summary;
}

export function buildArtifactCollectionSummary(surface) {
  if (
    !isObject(surface) ||
    surface.artifact_collection_surface_schema_version !==
      AE_WEB_ARTIFACT_COLLECTION_SURFACE_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact collection summary is invalid.", {
      status: "ARTIFACT_COLLECTION_SUMMARY_INVALID"
    });
  }
  const statusCounts = {};
  const downloadableFormats = new Set();
  for (const item of Array.isArray(surface.items) ? surface.items : []) {
    statusCounts[item.artifactStatus] = (statusCounts[item.artifactStatus] || 0) + 1;
    for (const format of item.downloadableFormats || []) {
      downloadableFormats.add(format);
    }
  }
  const summary = {
    artifact_collection_surface_schema_version:
      surface.artifact_collection_surface_schema_version,
    artifact_collection_schema_version: surface.artifact_collection_schema_version,
    count: surface.count,
    item_count: surface.itemCount,
    ready_count: statusCounts.READY || 0,
    status_counts: statusCounts,
    downloadable_format_count: downloadableFormats.size,
    route_present: Boolean(surface.route),
    client_mode: surface.clientMode,
    filter: surface.filter,
    metadata: surface.metadata
  };
  assertArtifactClientSurfaceSafe(summary);
  return summary;
}

export function buildArtifactClientSummary(surface) {
  if (
    !isObject(surface) ||
    surface.artifact_client_schema_version !== AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact surface summary is invalid.", {
      status: "ARTIFACT_SURFACE_INVALID"
    });
  }
  const summary = {
    artifact_client_schema_version: surface.artifact_client_schema_version,
    artifact_id: surface.artifactId || surface.artifactFile?.artifactFileId || null,
    artifact_version_id:
      surface.artifactVersionId || surface.artifactFile?.artifactVersionId || null,
    status: surface.artifactStatus || "READY",
    primary_format: surface.primaryFormat || surface.artifactFile?.format || "UNKNOWN",
    available_format_count: Array.isArray(surface.availableFormats)
      ? surface.availableFormats.length
      : 0,
    preview_route_present: Boolean(surface.previewRoute || surface.route?.endsWith("/preview")),
    download_route_count: surface.downloadRoutes
      ? Object.keys(surface.downloadRoutes).length
      : surface.route?.endsWith("/download")
        ? 1
        : 0,
    client_mode: surface.clientMode,
    content_included: Boolean(surface.metadata?.contentIncluded),
    binary_content_included: Boolean(surface.metadata?.binaryContentIncluded),
    download_payload_kind: surface.downloadPayloadKind || null,
    content_encoding: surface.contentEncoding || null,
    content_length: surface.contentLength ?? null,
    encoded_content_length: surface.encodedContentLength ?? null,
    metadata: {
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      storageLocationIncluded: false
    }
  };
  assertArtifactClientSurfaceSafe(summary);
  return summary;
}

export function assertArtifactClientSurfaceSafe(surface) {
  const sensitiveKeys = findSensitiveArtifactClientKeys(surface);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactClientError("Artifact client surface contains sensitive keys.", {
      status: "ARTIFACT_SURFACE_SENSITIVE_KEY"
    });
  }
  const serialized = JSON.stringify(surface);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactClientError("Artifact client surface contains sensitive values.", {
      status: "ARTIFACT_SURFACE_SENSITIVE_VALUE"
    });
  }
}

export function findSensitiveArtifactClientKeys(payload) {
  const found = [];

  function visit(value, path) {
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    if (!isObject(value)) return;
    for (const [key, child] of Object.entries(value)) {
      const keyPath = path ? `${path}.${key}` : key;
      const normalized = key.toLowerCase();
      if (
        SENSITIVE_KEY_PARTS.some(part => normalized.includes(part)) &&
        !isAllowedFalseSensitiveFlag(key, child)
      ) {
        found.push(keyPath);
      }
      visit(child, keyPath);
    }
  }

  visit(payload, "");
  return found.sort();
}

function buildMockArtifactCollectionPayload(records, collectionQuery) {
  const matchingRecords = records
    .filter(record => artifactRecordMatchesCollectionQuery(record, collectionQuery))
    .sort(compareArtifactRecordsLatestFirst)
    .slice(0, collectionQuery.limit);
  return {
    artifact_collection_schema_version: AE_ARTIFACT_COLLECTION_SCHEMA_VERSION,
    filter: collectionQuery,
    count: matchingRecords.length,
    limit: collectionQuery.limit,
    next_cursor: null,
    items: matchingRecords.map(buildArtifactCollectionItemFromRecord)
  };
}

function buildArtifactCollectionItemFromRecord(record) {
  const files = normalizeArtifactFiles(record.files);
  const links = normalizeArtifactLinks(record.links);
  const versions = Array.isArray(record.versions)
    ? record.versions.filter(isObject)
    : [];
  const renderJobs = Array.isArray(record.render_jobs)
    ? record.render_jobs.filter(isObject)
    : [];
  const currentVersionId = optionalText(record.current_version_id);
  const sourceRef = Array.isArray(record.source_refs) && isObject(record.source_refs[0])
    ? record.source_refs[0]
    : {};
  const owner = isObject(record.owner_actor_ref) ? record.owner_actor_ref : {};
  const workspace = isObject(record.workspace_ref) ? record.workspace_ref : {};
  const artifactId = requiredText(record.artifact_id, "artifact_id");
  return {
    artifact_collection_item_schema_version:
      AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION,
    artifact_id: artifactId,
    artifact_type: optionalText(record.artifact_type) || "generated_document",
    artifact_status: optionalText(record.artifact_status) || "UNKNOWN",
    display_title: optionalText(record.display_title) || "Untitled artifact",
    language: optionalText(record.language) || null,
    artifact_intent: optionalText(record.artifact_intent) || null,
    target_formats: normalizeTextList(record.target_formats),
    available_formats: sortedUnique(files.map(file => file.format)),
    downloadable_formats: linkedCollectionFormats(files, links, "download"),
    previewable_formats: linkedCollectionFormats(files, links, "preview"),
    current_version_id: currentVersionId,
    current_version_no: currentVersionNo(versions, currentVersionId),
    version_count: versions.length,
    file_count: files.length,
    link_count: links.length,
    render_job_count: renderJobs.length,
    latest_render_job: latestCollectionRenderJob(renderJobs),
    source_summary: {
      cx_generation_id: optionalText(sourceRef.cx_generation_id) || null,
      structured_draft_id: optionalText(sourceRef.structured_draft_id) || null,
      retrieval_package_id: optionalText(sourceRef.retrieval_package_id) || null,
      retrieval_package_hash: optionalText(sourceRef.retrieval_package_hash) || null,
      evidence_ref_count: numberOrZero(sourceRef.evidence_ref_count),
      source_anchor_count: numberOrZero(sourceRef.source_anchor_count)
    },
    quality_summary: isObject(sourceRef.quality_summary) ? sourceRef.quality_summary : {},
    routes: {
      detail: artifactDetailRoute(artifactId),
      versions: artifactVersionsRoute(artifactId)
    },
    tenant_id: optionalText(owner.tenant_id) || null,
    workspace_id: optionalText(workspace.workspace_id) || null,
    owner_user_id: optionalText(owner.actor_id) || null,
    chat_document_id: optionalText(record.chat_document_id) || null,
    interaction_id: optionalText(record.interaction_id) || null,
    created_at: optionalText(record.created_at) || null,
    updated_at: optionalText(record.updated_at) || null
  };
}

function artifactRecordMatchesCollectionQuery(record, collectionQuery) {
  const owner = isObject(record?.owner_actor_ref) ? record.owner_actor_ref : {};
  const workspace = isObject(record?.workspace_ref) ? record.workspace_ref : {};
  return (
    owner.tenant_id === collectionQuery.tenant_id &&
    owner.actor_id === collectionQuery.owner_user_id &&
    workspace.workspace_id === collectionQuery.workspace_id &&
    (
      collectionQuery.status === null ||
      optionalText(record.artifact_status)?.toUpperCase() === collectionQuery.status
    )
  );
}

function compareArtifactRecordsLatestFirst(left, right) {
  const leftTime = optionalText(left.updated_at) || optionalText(left.created_at) || "";
  const rightTime = optionalText(right.updated_at) || optionalText(right.created_at) || "";
  return rightTime.localeCompare(leftTime);
}

async function fetchArtifactJson(request, url, options = {}) {
  let response;
  const headers = {
    Accept: "application/json",
    ...(options.headers || {})
  };
  try {
    response = await request(url, {
      method: options.method || "GET",
      credentials: "same-origin",
      headers,
      ...(options.body ? { body: options.body } : {})
    });
  } catch {
    throw new ArtifactClientError("Artifact request failed.", {
      status: "NETWORK_ERROR",
      retryable: true
    });
  }
  const payload = await safeJson(response);
  if (!response.ok) {
    throw new ArtifactClientError(
      payload.detail || `Artifact request failed with HTTP ${response.status}.`,
      {
        status: payload.error_code || `HTTP_${response.status}`,
        retryable: Boolean(payload.retryable)
      }
    );
  }
  return payload;
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function normalizeArtifactFiles(files) {
  return Array.isArray(files) ? files.map(normalizeArtifactFile) : [];
}

function normalizeArtifactFile(file) {
  if (!isObject(file)) {
    throw new ArtifactClientError("Artifact file metadata is invalid.", {
      status: "ARTIFACT_FILE_INVALID"
    });
  }
  return {
    artifactFileId: requiredText(file.artifact_file_id, "artifact_file_id"),
    artifactVersionId: optionalText(file.artifact_version_id) || null,
    artifactId: optionalText(file.artifact_id) || null,
    format: optionalText(file.format) || "UNKNOWN",
    mimeType: optionalText(file.mime_type) || "application/octet-stream",
    fileName: optionalText(file.file_name) || "artifact",
    fileSizeBytes: numberOrNull(file.file_size_bytes),
    fileHash: optionalText(file.file_hash) || null,
    sourceVersionHash: optionalText(file.source_version_hash) || null
  };
}

function normalizeArtifactLinks(links) {
  return Array.isArray(links) ? links.map(normalizeArtifactLink) : [];
}

function normalizeArtifactLink(link) {
  if (!isObject(link)) {
    throw new ArtifactClientError("Artifact link metadata is invalid.", {
      status: "ARTIFACT_LINK_INVALID"
    });
  }
  return {
    artifactLinkId: optionalText(link.artifact_link_id) || null,
    artifactFileId: requiredText(link.artifact_file_id, "artifact_file_id"),
    linkType: requiredText(link.link_type, "link_type"),
    linkRoute: safeRoute(link.link_route),
    accessPolicy: optionalText(link.access_policy) || "owner_only",
    expiresAt: optionalText(link.expires_at) || null,
    revokedAt: optionalText(link.revoked_at) || null
  };
}

function routeForLink(links, currentFile, linkType) {
  if (!currentFile) return null;
  const link = links.find(
    item => item.artifactFileId === currentFile.artifactFileId && item.linkType === linkType
  );
  return link?.linkRoute || null;
}

function downloadRoutesForLinks(links, files) {
  const routes = {};
  for (const link of links) {
    if (link.linkType !== "download" || !link.linkRoute) continue;
    const file = files.find(item => item.artifactFileId === link.artifactFileId);
    const format = file?.format || "UNKNOWN";
    routes[format] = link.linkRoute;
  }
  return routes;
}

function linkedCollectionFormats(files, links, linkType) {
  const linkedFileIds = new Set(
    links
      .filter(link => link.linkType === linkType && link.linkRoute)
      .map(link => link.artifactFileId)
  );
  return sortedUnique(
    files
      .filter(file => linkedFileIds.has(file.artifactFileId))
      .map(file => file.format)
  );
}

function availableFormats(files, targetFormats) {
  const formats = files.map(file => file.format).filter(Boolean);
  if (formats.length === 0 && Array.isArray(targetFormats)) {
    formats.push(...targetFormats.map(String).filter(Boolean));
  }
  return [...new Set(formats)];
}

function currentVersionNo(versions, currentVersionId) {
  if (!currentVersionId) return null;
  const version = versions.find(item => item.artifact_version_id === currentVersionId);
  return numberOrNull(version?.version_no);
}

function latestCollectionRenderJob(renderJobs) {
  const renderJob = renderJobs[renderJobs.length - 1];
  if (!isObject(renderJob)) return null;
  return {
    render_job_id: optionalText(renderJob.render_job_id) || null,
    job_status: optionalText(renderJob.job_status) || null,
    current_stage: optionalText(renderJob.current_stage) || null,
    progress_percent: numberOrZero(renderJob.progress_percent),
    retryable: Boolean(renderJob.retryable),
    failure_code: optionalText(renderJob.failure_code) || null
  };
}

function currentVersion(versions, currentVersionId) {
  if (!Array.isArray(versions) || !currentVersionId) return null;
  return (
    versions.find(version => version.artifact_version_id === currentVersionId) ||
    null
  );
}

function normalizeArtifactLifecycleAction(action) {
  const normalized = requiredText(action, "lifecycle_action").toUpperCase();
  if (!SUPPORTED_ARTIFACT_LIFECYCLE_ACTIONS.includes(normalized)) {
    throw new ArtifactClientError("Artifact lifecycle action is unsupported.", {
      status: "ARTIFACT_LIFECYCLE_ACTION_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeArtifactLifecycleStatus(status) {
  const normalized = requiredText(status, "artifact_status").toUpperCase();
  if (!SUPPORTED_ARTIFACT_COLLECTION_STATUSES.includes(normalized)) {
    throw new ArtifactClientError("Artifact lifecycle status is unsupported.", {
      status: "ARTIFACT_LIFECYCLE_STATUS_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeArtifactLifecycleTerminalOrRestorableStatus(status) {
  const normalized = normalizeArtifactLifecycleStatus(status);
  if (
    !ARTIFACT_RESTORABLE_STATUSES.includes(normalized) &&
    normalized !== "ARCHIVED" &&
    normalized !== "DELETED"
  ) {
    throw new ArtifactClientError("Artifact lifecycle target status is unsupported.", {
      status: "ARTIFACT_LIFECYCLE_TARGET_STATUS_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeArtifactRestoreStatus(status) {
  const normalized = optionalText(status);
  if (!normalized) return null;
  const upper = normalized.toUpperCase();
  if (!ARTIFACT_RESTORABLE_STATUSES.includes(upper)) {
    throw new ArtifactClientError("Artifact restore status is unsupported.", {
      status: "ARTIFACT_LIFECYCLE_RESTORE_STATUS_UNSUPPORTED"
    });
  }
  return upper;
}

function artifactLifecycleTargetStatus({ action, restoreStatus = null }) {
  const normalizedAction = normalizeArtifactLifecycleAction(action);
  const normalizedRestoreStatus = normalizeArtifactRestoreStatus(restoreStatus);
  if (normalizedAction === "ARCHIVE") return "ARCHIVED";
  if (normalizedAction === "MARK_DELETED") return "DELETED";
  return normalizedRestoreStatus || DEFAULT_ARTIFACT_RESTORE_STATUS;
}

function normalizeLifecycleReasonCode(reasonCode) {
  const normalized =
    optionalText(reasonCode)?.toLowerCase() ||
    DEFAULT_ARTIFACT_LIFECYCLE_REASON_CODE;
  if (normalized.length > 64 || !/^[a-z0-9_:-]+$/.test(normalized)) {
    throw new ArtifactClientError("Artifact lifecycle reason code is invalid.", {
      status: "ARTIFACT_LIFECYCLE_REASON_CODE_INVALID"
    });
  }
  return normalized;
}

function normalizeLifecycleCommentHash(value) {
  const normalized = optionalText(value);
  if (!normalized) return null;
  if (!/^[0-9a-f]{64}$/.test(normalized)) {
    throw new ArtifactClientError("Artifact lifecycle comment hash is invalid.", {
      status: "ARTIFACT_LIFECYCLE_COMMENT_HASH_INVALID"
    });
  }
  return normalized;
}

function normalizeLifecycleActorScope(actorRef) {
  const actor = isObject(actorRef) ? actorRef : {};
  return {
    actorType: optionalText(actor.actor_type) || "user",
    actorId: optionalText(actor.actor_id) || "unknown",
    tenantId: optionalText(actor.tenant_id) || null
  };
}

function deterministicLifecycleRequestId(artifactId, action, targetStatus) {
  return `artifact-lifecycle-${safeIdStem(artifactId)}-${action.toLowerCase()}-${safeIdStem(targetStatus)}`;
}

function deterministicLifecycleActionId(artifactId, idempotencyKey) {
  return `artifact-lifecycle-action-${safeIdStem(artifactId)}-${safeIdStem(idempotencyKey)}`;
}

function mockHexDigest(value) {
  let hash = 2166136261;
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  const seed = (hash >>> 0).toString(16).padStart(8, "0");
  return seed.repeat(8).slice(0, 64);
}

function normalizeArtifactCollectionStatus(status) {
  const normalized = optionalText(status);
  if (!normalized) return null;
  const upper = normalized.toUpperCase();
  if (!SUPPORTED_ARTIFACT_COLLECTION_STATUSES.includes(upper)) {
    throw new ArtifactClientError("Artifact collection status is unsupported.", {
      status: "ARTIFACT_COLLECTION_STATUS_INVALID"
    });
  }
  return upper;
}

function normalizeArtifactCollectionLimit(limit) {
  if (limit == null) return DEFAULT_ARTIFACT_COLLECTION_LIMIT;
  if (typeof limit === "boolean") {
    throw new ArtifactClientError("Artifact collection limit is invalid.", {
      status: "ARTIFACT_COLLECTION_LIMIT_INVALID"
    });
  }
  const normalized = Number(String(limit).trim());
  if (
    !Number.isInteger(normalized) ||
    normalized < 1 ||
    normalized > MAX_ARTIFACT_COLLECTION_LIMIT
  ) {
    throw new ArtifactClientError("Artifact collection limit is invalid.", {
      status: "ARTIFACT_COLLECTION_LIMIT_INVALID"
    });
  }
  return normalized;
}

function normalizeArtifactCollectionRenderJob(renderJob) {
  if (renderJob == null) return null;
  if (!isObject(renderJob)) {
    throw new ArtifactClientError("Artifact collection render job is invalid.", {
      status: "ARTIFACT_COLLECTION_RENDER_JOB_INVALID"
    });
  }
  return {
    renderJobId: optionalText(renderJob.render_job_id) || null,
    jobStatus: optionalText(renderJob.job_status) || null,
    currentStage: optionalText(renderJob.current_stage) || null,
    progressPercent: numberOrZero(renderJob.progress_percent),
    retryable: Boolean(renderJob.retryable),
    failureCode: optionalText(renderJob.failure_code) || null
  };
}

function normalizeArtifactCollectionSourceSummary(sourceSummary) {
  const source = isObject(sourceSummary) ? sourceSummary : {};
  return {
    cxGenerationId: optionalText(source.cx_generation_id) || null,
    structuredDraftId: optionalText(source.structured_draft_id) || null,
    retrievalPackageId: optionalText(source.retrieval_package_id) || null,
    retrievalPackageHash: optionalText(source.retrieval_package_hash) || null,
    evidenceRefCount: numberOrZero(source.evidence_ref_count),
    sourceAnchorCount: numberOrZero(source.source_anchor_count)
  };
}

function normalizeArtifactCollectionQualitySummary(qualitySummary) {
  const quality = isObject(qualitySummary) ? qualitySummary : {};
  return {
    citationStatus: optionalText(quality.citation_status) || "UNKNOWN",
    citationCount: numberOrZero(quality.citation_count),
    validationErrorCount: numberOrZero(quality.validation_error_count),
    warningCount: numberOrZero(quality.warning_count),
    groundingRequired: Boolean(quality.grounding_required),
    evidenceRefCount: numberOrZero(quality.evidence_ref_count)
  };
}

function normalizeArtifactCollectionRoutes(routes, artifactId) {
  const rawRoutes = isObject(routes) ? routes : {};
  return {
    detail: rawRoutes.detail ? safeRoute(rawRoutes.detail) : artifactDetailRoute(artifactId),
    versions: rawRoutes.versions
      ? safeRoute(rawRoutes.versions)
      : artifactVersionsRoute(artifactId)
  };
}

function normalizeTextList(values) {
  return Array.isArray(values) ? sortedUnique(values) : [];
}

function sortedUnique(values) {
  return [...new Set(values.map(optionalText).filter(Boolean))].sort();
}

function findArtifactFile(records, artifactFileId) {
  const normalized = requiredText(artifactFileId, "artifact_file_id");
  for (const record of records.values()) {
    const found = Array.isArray(record.files)
      ? record.files.find(file => file.artifact_file_id === normalized)
      : null;
    if (found) return found;
  }
  return null;
}

function findArtifactLink(records, artifactFileId, linkType) {
  const normalized = requiredText(artifactFileId, "artifact_file_id");
  for (const record of records.values()) {
    const found = Array.isArray(record.links)
      ? record.links.find(
          link => link.artifact_file_id === normalized && link.link_type === linkType
        )
      : null;
    if (found) return found;
  }
  return {
    artifact_file_id: normalized,
    link_type: linkType,
    link_route:
      linkType === "preview"
        ? artifactFilePreviewRoute(normalized)
        : artifactFileDownloadRoute(normalized),
    access_policy: "owner_only"
  };
}

function buildMockPreviewPayload(artifactFile, artifactLink) {
  return {
    preview_schema_version: AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION,
    artifact_file: artifactFile,
    artifact_link: artifactLink,
    content_type: artifactFile.mime_type || "text/markdown",
    text_preview: "# Generated artifact\n\nPreview is available.",
    truncated: false
  };
}

function buildMockDownloadPayload(artifactFile, artifactLink) {
  const format = optionalText(artifactFile.format)?.toUpperCase();
  const binaryContent = mockBinaryDownloadContentBase64(format);
  if (binaryContent) {
    return {
      download_schema_version: AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
      artifact_file: artifactFile,
      artifact_link: artifactLink,
      download_file_name: artifactFile.file_name || "artifact",
      content_type: artifactFile.mime_type || "application/octet-stream",
      content_hash: artifactFile.file_hash || null,
      content_encoding: BASE64_DOWNLOAD_CONTENT_ENCODING,
      content_base64: binaryContent
    };
  }
  return {
    download_schema_version: AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
    artifact_file: artifactFile,
    artifact_link: artifactLink,
    download_file_name: artifactFile.file_name || "artifact.md",
    content_type: artifactFile.mime_type || "text/markdown",
    content_hash: artifactFile.file_hash || null,
    content: "# Generated artifact\n\nDownload is available."
  };
}

function materializeMockArtifactExport(record, exportRequest) {
  const targetFormats = exportRequest.target_formats;
  const artifact = clone(record);
  const artifactId = exportRequest.artifact_id;
  const requestStem = safeIdStem(exportRequest.render_request_id);
  const artifactVersionId = `artifact-version-${requestStem}`;
  const renderJobId = `artifact-render-job-${requestStem}`;
  const contentHash = firstText(
    artifact.versions?.map(version => version.artifact_content_hash)
  ) || "f".repeat(64);
  const createdAt = new Date(0).toISOString();
  const files = targetFormats.map(format => {
    const artifactFileId = `artifact-file-${requestStem}-${format.toLowerCase()}`;
    return {
      artifact_file_id: artifactFileId,
      artifact_version_id: artifactVersionId,
      artifact_id: artifactId,
      format,
      mime_type: mimeTypeForExportFormat(format),
      file_name: fileNameForExportFormat(format),
      storage_ref: `ae://artifacts/${artifactId}/versions/${artifactVersionId}/${fileNameForExportFormat(format)}`,
      file_size_bytes: format === "MD" || format === "HTML_PREVIEW" ? 2048 : 4096,
      file_hash: contentHash,
      source_version_hash: contentHash,
      created_at: createdAt
    };
  });
  const links = files.flatMap(file => [
    {
      artifact_link_id: `${file.artifact_file_id}-preview-link`,
      artifact_file_id: file.artifact_file_id,
      link_type: "preview",
      access_policy: "owner_only",
      link_route: artifactFilePreviewRoute(file.artifact_file_id)
    },
    {
      artifact_link_id: `${file.artifact_file_id}-download-link`,
      artifact_file_id: file.artifact_file_id,
      link_type: "download",
      access_policy: "owner_only",
      link_route: artifactFileDownloadRoute(file.artifact_file_id)
    }
  ]);
  artifact.artifact_status = "READY";
  artifact.current_version_id = artifactVersionId;
  artifact.target_formats = targetFormats;
  artifact.versions = [
    ...(Array.isArray(artifact.versions) ? artifact.versions : []),
    {
      artifact_version_id: artifactVersionId,
      version_no: (artifact.versions?.length || 0) + 1,
      source_content_hash: contentHash,
      artifact_content_hash: contentHash,
      rendered_formats: targetFormats
    }
  ];
  artifact.files = [...(Array.isArray(artifact.files) ? artifact.files : []), ...files];
  artifact.links = [...(Array.isArray(artifact.links) ? artifact.links : []), ...links];
  return {
    render_result_schema_version: "ae_markdown_render_result.v1",
    render_job: {
      render_job_id: renderJobId,
      artifact_id: artifactId,
      artifact_version_id: artifactVersionId,
      job_status: "COMPLETED",
      current_stage: "FINALIZING",
      progress_percent: 100
    },
    artifact
  };
}

function materializeMockArtifactLifecycleAction(record, lifecycleRequest) {
  const artifact = clone(record);
  const previousStatus = normalizeArtifactLifecycleStatus(artifact.artifact_status);
  assertMockArtifactLifecycleTransitionAllowed({
    currentStatus: previousStatus,
    action: lifecycleRequest.action
  });
  const targetStatus = lifecycleRequest.target_status;
  const updatedAt = new Date(0).toISOString();
  artifact.artifact_status = targetStatus;
  artifact.updated_at = updatedAt;
  const lifecycleAction = {
    artifact_lifecycle_action_schema_version:
      AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION,
    lifecycle_action_id: deterministicLifecycleActionId(
      lifecycleRequest.artifact_id,
      lifecycleRequest.idempotency_key
    ),
    artifact_id: lifecycleRequest.artifact_id,
    action: lifecycleRequest.action,
    previous_status: previousStatus,
    target_status: targetStatus,
    restore_status:
      lifecycleRequest.action === "RESTORE" ? lifecycleRequest.restore_status : null,
    reason_code: lifecycleRequest.reason_code,
    comment_hash: lifecycleRequest.body.comment
      ? mockHexDigest(lifecycleRequest.body.comment)
      : null,
    comment_length: lifecycleRequest.comment_length,
    actor_ref: normalizeLifecycleActorScope(record.owner_actor_ref),
    request_id: lifecycleRequest.idempotency_key,
    trace_id: "0".repeat(32),
    idempotency_key: lifecycleRequest.idempotency_key,
    metadata: {
      physical_delete_requested: false,
      storage_mutation_requested: false,
      raw_comment_included: false
    }
  };
  return {
    artifact,
    result: {
      artifact_lifecycle_action_result_schema_version:
        AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION,
      lifecycle_action: lifecycleAction,
      artifact_id: lifecycleRequest.artifact_id,
      artifact_status: targetStatus,
      previous_status: previousStatus,
      target_status: targetStatus,
      transition_applied: artifact.artifact_status === targetStatus,
      routes: {
        artifact: artifactDetailRoute(lifecycleRequest.artifact_id),
        collection: "/api/v1/artifacts"
      },
      updated_at: updatedAt,
      metadata: {
        rendered_payload_included: false,
        storage_location_included: false,
        physical_delete_executed: false
      }
    }
  };
}

function normalizeLifecycleActionForSurface(action) {
  if (
    !isObject(action) ||
    action.artifact_lifecycle_action_schema_version !==
      AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION
  ) {
    throw new ArtifactClientError("Artifact lifecycle action is invalid.", {
      status: "ARTIFACT_LIFECYCLE_ACTION_INVALID"
    });
  }
  const normalized = {
    artifact_lifecycle_action_schema_version:
      action.artifact_lifecycle_action_schema_version,
    lifecycle_action_id: requiredText(
      action.lifecycle_action_id,
      "lifecycle_action_id"
    ),
    artifact_id: requiredText(action.artifact_id, "artifact_id"),
    action: normalizeArtifactLifecycleAction(action.action),
    previous_status: normalizeArtifactLifecycleStatus(action.previous_status),
    target_status: normalizeArtifactLifecycleTerminalOrRestorableStatus(
      action.target_status
    ),
    restore_status: normalizeArtifactRestoreStatus(action.restore_status),
    reason_code: normalizeLifecycleReasonCode(action.reason_code),
    comment_hash: normalizeLifecycleCommentHash(action.comment_hash),
    comment_length: numberOrZero(action.comment_length),
    actor_ref: normalizeLifecycleActorScope(action.actor_ref),
    request_id: requiredText(action.request_id, "request_id"),
    trace_id: requiredText(action.trace_id, "trace_id"),
    idempotency_key: requiredText(action.idempotency_key, "idempotency_key"),
    metadata: normalizeLifecycleActionMetadata(action.metadata)
  };
  if (
    normalized.target_status !==
    artifactLifecycleTargetStatus({
      action: normalized.action,
      restoreStatus: normalized.restore_status
    })
  ) {
    throw new ArtifactClientError("Artifact lifecycle target status is invalid.", {
      status: "ARTIFACT_LIFECYCLE_TARGET_STATUS_MISMATCH"
    });
  }
  return normalized;
}

function normalizeLifecycleActionMetadata(metadata) {
  const normalized = isObject(metadata) ? metadata : {};
  if (
    normalized.physical_delete_requested ||
    normalized.storage_mutation_requested ||
    normalized.raw_comment_included
  ) {
    throw new ArtifactClientError("Artifact lifecycle action metadata is unsafe.", {
      status: "ARTIFACT_LIFECYCLE_METADATA_UNSAFE"
    });
  }
  return {
    physicalDeleteRequested: false,
    storageMutationRequested: false,
    rawCommentIncluded: false
  };
}

function normalizeLifecycleResultMetadata(resultMetadata, actionMetadata) {
  const normalized = isObject(resultMetadata) ? resultMetadata : {};
  if (
    normalized.rendered_payload_included ||
    normalized.storage_location_included ||
    normalized.physical_delete_executed ||
    actionMetadata.physicalDeleteRequested ||
    actionMetadata.storageMutationRequested ||
    actionMetadata.rawCommentIncluded
  ) {
    throw new ArtifactClientError("Artifact lifecycle result metadata is unsafe.", {
      status: "ARTIFACT_LIFECYCLE_METADATA_UNSAFE"
    });
  }
  return {
    renderedPayloadIncluded: false,
    storageLocationIncluded: false,
    physicalDeleteExecuted: false,
    physicalDeleteRequested: false,
    storageMutationRequested: false,
    rawCommentIncluded: false,
    contentIncluded: false,
    binaryContentIncluded: false,
    previewTextIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    rawPromptIncluded: false,
    rawSourceIncluded: false
  };
}

function normalizeArtifactLifecycleRoutes(routes, artifactId) {
  const rawRoutes = isObject(routes) ? routes : {};
  return {
    artifact: rawRoutes.artifact
      ? safeRoute(rawRoutes.artifact)
      : artifactDetailRoute(artifactId),
    collection: rawRoutes.collection ? safeRoute(rawRoutes.collection) : "/api/v1/artifacts"
  };
}

function assertLifecycleSurfaceMatchesAction(surface, lifecycleAction) {
  if (surface.artifactId !== lifecycleAction.artifact_id) {
    throw new ArtifactClientError("Artifact lifecycle action artifact id mismatched.", {
      status: "ARTIFACT_LIFECYCLE_ARTIFACT_MISMATCH"
    });
  }
  if (surface.previousStatus !== lifecycleAction.previous_status) {
    throw new ArtifactClientError("Artifact lifecycle previous status mismatched.", {
      status: "ARTIFACT_LIFECYCLE_STATUS_MISMATCH"
    });
  }
  if (surface.targetStatus !== lifecycleAction.target_status) {
    throw new ArtifactClientError("Artifact lifecycle target status mismatched.", {
      status: "ARTIFACT_LIFECYCLE_STATUS_MISMATCH"
    });
  }
}

function assertMockArtifactLifecycleTransitionAllowed({ currentStatus, action }) {
  if (
    action === "ARCHIVE" &&
    !ARTIFACT_ARCHIVABLE_STATUSES.includes(currentStatus)
  ) {
    throw new ArtifactClientError("Artifact cannot be archived from current status.", {
      status: "ARTIFACT_LIFECYCLE_TRANSITION_INVALID"
    });
  }
  if (
    action === "MARK_DELETED" &&
    !ARTIFACT_DELETABLE_STATUSES.includes(currentStatus)
  ) {
    throw new ArtifactClientError("Artifact cannot be marked deleted from current status.", {
      status: "ARTIFACT_LIFECYCLE_TRANSITION_INVALID"
    });
  }
  if (
    action === "RESTORE" &&
    !ARTIFACT_RESTORE_SOURCE_STATUSES.includes(currentStatus)
  ) {
    throw new ArtifactClientError("Artifact cannot be restored from current status.", {
      status: "ARTIFACT_LIFECYCLE_TRANSITION_INVALID"
    });
  }
}

function safeArtifactMetadata({
  contentIncluded = false,
  binaryContentIncluded = false,
  previewTextIncluded = false
} = {}) {
  return {
    contentIncluded: Boolean(contentIncluded),
    binaryContentIncluded: Boolean(binaryContentIncluded),
    previewTextIncluded: Boolean(previewTextIncluded),
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    storageLocationIncluded: false
  };
}

function normalizeDownloadContent(payload) {
  const content = optionalText(payload.content) || "";
  const encodedContent = optionalText(payload.content_base64);
  const declaredEncoding = optionalText(payload.content_encoding)?.toLowerCase() || null;
  const wantsBase64 =
    declaredEncoding === BASE64_DOWNLOAD_CONTENT_ENCODING || Boolean(encodedContent);

  if (
    declaredEncoding &&
    ![TEXT_DOWNLOAD_CONTENT_ENCODING, "text", BASE64_DOWNLOAD_CONTENT_ENCODING].includes(
      declaredEncoding
    )
  ) {
    throw new ArtifactClientError("Artifact download content encoding is unsupported.", {
      status: "ARTIFACT_DOWNLOAD_ENCODING_UNSUPPORTED"
    });
  }

  if (content && encodedContent) {
    throw new ArtifactClientError("Artifact download content is ambiguous.", {
      status: "ARTIFACT_DOWNLOAD_CONTENT_AMBIGUOUS"
    });
  }

  if (wantsBase64) {
    const contentBase64 = normalizeBase64DownloadContent(encodedContent);
    return {
      content: "",
      contentBase64,
      contentEncoding: BASE64_DOWNLOAD_CONTENT_ENCODING,
      downloadPayloadKind: "base64",
      contentLength: decodedBase64Length(contentBase64),
      encodedContentLength: contentBase64.length
    };
  }

  return {
    content,
    contentBase64: null,
    contentEncoding: TEXT_DOWNLOAD_CONTENT_ENCODING,
    downloadPayloadKind: "text",
    contentLength: content.length,
    encodedContentLength: null
  };
}

function normalizeBase64DownloadContent(value) {
  const compact = optionalText(value)?.replace(/\s+/g, "") || null;
  if (
    !compact ||
    compact.length % 4 !== 0 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(compact)
  ) {
    throw new ArtifactClientError("Artifact download base64 content is invalid.", {
      status: "ARTIFACT_DOWNLOAD_BASE64_INVALID"
    });
  }
  return compact;
}

function decodedBase64Length(value) {
  const padding = value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0;
  return Math.trunc((value.length * 3) / 4) - padding;
}

function mockBinaryDownloadContentBase64(format) {
  if (format === "DOCX") return "UEsDBAoAAAAAAERPQ1g=";
  if (format === "PDF") return "JVBERi0xLjQKJQ==";
  return null;
}

function safeRoute(value) {
  const route = requiredText(value, "link_route");
  if (!route.startsWith("/api/v1/")) {
    throw new ArtifactClientError("Artifact link route is not browser safe.", {
      status: "ARTIFACT_LINK_ROUTE_UNSAFE"
    });
  }
  return route;
}

function requiredText(value, fieldName) {
  const text = optionalText(value);
  if (!text) {
    throw new ArtifactClientError(`${fieldName} is required.`, {
      status: "ARTIFACT_FIELD_REQUIRED"
    });
  }
  return text;
}

function firstText(values) {
  if (!Array.isArray(values)) return null;
  for (const value of values) {
    const text = optionalText(value);
    if (text) return text;
  }
  return null;
}

function optionalText(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : null;
}

function numberOrZero(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function numberOrNull(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeExportFormats(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new ArtifactClientError("target_formats must be a non-empty array.", {
      status: "ARTIFACT_EXPORT_FORMATS_INVALID"
    });
  }
  const normalized = [
    ...new Set(values.map(value => requiredText(value, "target_format").toUpperCase()))
  ];
  const unsupported = normalized.filter(
    format => !SUPPORTED_ARTIFACT_EXPORT_FORMATS.includes(format)
  );
  if (unsupported.length > 0) {
    throw new ArtifactClientError("Artifact export format is unsupported.", {
      status: "ARTIFACT_EXPORT_FORMAT_UNSUPPORTED"
    });
  }
  return normalized;
}

function deterministicExportRequestId(artifactId, targetFormats) {
  return `artifact-export-${safeIdStem(artifactId)}-${targetFormats
    .map(format => format.toLowerCase())
    .join("-")}`;
}

function mimeTypeForExportFormat(format) {
  if (format === "HTML_PREVIEW") return "text/html";
  if (format === "DOCX") {
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  }
  if (format === "PDF") return "application/pdf";
  return "text/markdown";
}

function fileNameForExportFormat(format) {
  if (format === "HTML_PREVIEW") return "generated-artifact.html";
  if (format === "DOCX") return "generated-artifact.docx";
  if (format === "PDF") return "generated-artifact.pdf";
  return "generated-artifact.md";
}

function safeIdStem(value) {
  return requiredText(value, "id")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 96);
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
