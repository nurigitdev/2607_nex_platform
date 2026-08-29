export const AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION =
  "ae_web_artifact_client.v1";
export const AE_ARTIFACT_RECORD_SCHEMA_VERSION = "ae_artifact_record.v1";
export const AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION =
  "ae_artifact_file_preview.v1";
export const AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION =
  "ae_artifact_file_download.v1";

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

export function artifactFileMetadataRoute(artifactFileId) {
  return `/api/v1/artifact-files/${encodeURIComponent(requiredText(artifactFileId, "artifact_file_id"))}`;
}

export function artifactFilePreviewRoute(artifactFileId) {
  return `${artifactFileMetadataRoute(artifactFileId)}/preview`;
}

export function artifactFileDownloadRoute(artifactFileId) {
  return `${artifactFileMetadataRoute(artifactFileId)}/download`;
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
    }
  };
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
  const content = optionalText(payload.content) || "";
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
    content,
    contentLength: content.length,
    route,
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: safeArtifactMetadata({ contentIncluded: true, previewTextIncluded: false })
  };
  assertArtifactClientSurfaceSafe(surface);
  return surface;
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

async function fetchArtifactJson(request, url) {
  let response;
  try {
    response = await request(url, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json"
      }
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

function availableFormats(files, targetFormats) {
  const formats = files.map(file => file.format).filter(Boolean);
  if (formats.length === 0 && Array.isArray(targetFormats)) {
    formats.push(...targetFormats.map(String).filter(Boolean));
  }
  return [...new Set(formats)];
}

function currentVersion(versions, currentVersionId) {
  if (!Array.isArray(versions) || !currentVersionId) return null;
  return (
    versions.find(version => version.artifact_version_id === currentVersionId) ||
    null
  );
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

function safeArtifactMetadata({
  contentIncluded = false,
  previewTextIncluded = false
} = {}) {
  return {
    contentIncluded: Boolean(contentIncluded),
    previewTextIncluded: Boolean(previewTextIncluded),
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    storageLocationIncluded: false
  };
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

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
