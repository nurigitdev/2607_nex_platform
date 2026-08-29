import {
  artifactFileIdFromRoute
} from "./artifactPreviewPanel.js";

export function buildMockArtifactRecordFromRef(
  artifactRef,
  {
    chatDocumentId = "chat-doc-local",
    interactionId = "interaction-local",
    cxGenerationId = "cx-gen-local"
  } = {}
) {
  const artifactId = artifactRef.artifactId || artifactRef.artifact_id || "artifact-local";
  const artifactVersionId =
    artifactRef.artifactVersionId ||
    artifactRef.artifact_version_id ||
    "artifact-version-local-001";
  const primaryFormat =
    artifactRef.primaryFormat || artifactRef.primary_format || "MD";
  const availableFormats = uniqueTexts([
    primaryFormat,
    ...(artifactRef.availableFormats || artifactRef.available_formats || []),
    ...Object.keys(artifactRef.downloadRoutes || artifactRef.download_routes || {})
  ]);
  const previewRoute = artifactRef.previewRoute || artifactRef.preview_route || null;
  const downloadRoutes =
    artifactRef.downloadRoutes || artifactRef.download_routes || {};
  const files = [];
  const links = [];
  const firstDownloadRoute = Object.values(downloadRoutes)[0] || null;
  const previewFileId = safeArtifactFileIdFromRoute(previewRoute, "preview");
  const primaryFileId =
    previewFileId ||
    safeArtifactFileIdFromRoute(firstDownloadRoute, "download") ||
    "artifact-file-local-001";
  const contentHash = artifactRef.sourceContentHash || artifactRef.source_content_hash;

  addMockArtifactFile(files, {
    artifactId,
    artifactVersionId,
    artifactFileId: primaryFileId,
    format: primaryFormat,
    contentHash
  });

  if (previewRoute && previewFileId) {
    links.push({
      artifact_link_id: `${previewFileId}-preview-link`,
      artifact_file_id: previewFileId,
      link_type: "preview",
      access_policy: "owner_only",
      link_route: previewRoute
    });
  }

  for (const [format, route] of Object.entries(downloadRoutes)) {
    const artifactFileId = safeArtifactFileIdFromRoute(route, "download");
    if (!artifactFileId) continue;
    addMockArtifactFile(files, {
      artifactId,
      artifactVersionId,
      artifactFileId,
      format,
      contentHash
    });
    links.push({
      artifact_link_id: `${artifactFileId}-${String(format).toLowerCase()}-download-link`,
      artifact_file_id: artifactFileId,
      link_type: "download",
      access_policy: "owner_only",
      link_route: route
    });
  }

  return {
    artifact_schema_version: "ae_artifact_record.v1",
    artifact_id: artifactId,
    artifact_type:
      artifactRef.artifactType || artifactRef.artifact_type || "generated_document",
    artifact_status: artifactRef.artifactStatus || artifactRef.artifact_status || "READY",
    current_version_id: artifactVersionId,
    chat_document_id: chatDocumentId,
    interaction_id: interactionId,
    display_title:
      artifactRef.displayTitle || artifactRef.display_title || "Generated artifact",
    target_formats: availableFormats,
    source_refs: [
      {
        cx_generation_id:
          artifactRef.sourceGenerationId ||
          artifactRef.source_generation_id ||
          cxGenerationId,
        structured_draft_content_hash: contentHash || null,
        evidence_ref_count:
          artifactRef.qualitySummary?.evidenceRefCount ||
          artifactRef.quality_summary?.evidence_ref_count ||
          0,
        quality_summary: {
          citation_status:
            artifactRef.qualitySummary?.citationStatus ||
            artifactRef.quality_summary?.citation_status ||
            "UNKNOWN",
          citation_count:
            artifactRef.qualitySummary?.citationCount ||
            artifactRef.quality_summary?.citation_count ||
            0,
          evidence_ref_count:
            artifactRef.qualitySummary?.evidenceRefCount ||
            artifactRef.quality_summary?.evidence_ref_count ||
            0,
          grounding_required: Boolean(
            artifactRef.qualitySummary?.groundingRequired ||
              artifactRef.quality_summary?.grounding_required
          )
        }
      }
    ],
    versions: [
      {
        artifact_version_id: artifactVersionId,
        version_no: 1,
        source_content_hash: contentHash || null,
        artifact_content_hash: contentHash || null,
        rendered_formats: availableFormats
      }
    ],
    files,
    links
  };
}

export function safeArtifactFileIdFromRoute(route, action) {
  if (!route) return null;
  try {
    return artifactFileIdFromRoute(route, action);
  } catch {
    return null;
  }
}

export function mimeTypeForArtifactFormat(format) {
  const normalized = String(format || "").toLowerCase();
  if (normalized.includes("html")) return "text/html";
  if (normalized === "pdf") return "application/pdf";
  if (normalized === "json") return "application/json";
  return "text/markdown";
}

export function fileNameForArtifactFormat(format) {
  return `generated-artifact.${extensionForArtifactFormat(format)}`;
}

function addMockArtifactFile(
  files,
  { artifactId, artifactVersionId, artifactFileId, format, contentHash }
) {
  if (files.some(file => file.artifact_file_id === artifactFileId)) return;
  files.push({
    artifact_file_id: artifactFileId,
    artifact_id: artifactId,
    artifact_version_id: artifactVersionId,
    format,
    mime_type: mimeTypeForArtifactFormat(format),
    file_name: fileNameForArtifactFormat(format),
    file_size_bytes: 2048,
    file_hash: contentHash || null,
    source_version_hash: contentHash || null
  });
}

function extensionForArtifactFormat(format) {
  const normalized = String(format || "md").toLowerCase();
  if (normalized.includes("html")) return "html";
  if (normalized === "pdf") return "pdf";
  if (normalized === "json") return "json";
  return "md";
}

function uniqueTexts(values) {
  return [...new Set(values.map(value => String(value || "").trim()).filter(Boolean))];
}
