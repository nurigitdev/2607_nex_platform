import { describe, expect, it, vi } from "vitest";

import {
  changeArtifactLifecycle,
  exportArtifact,
  loadArtifactDetail,
  loadArtifactLibrary,
  loadArtifactPreview,
} from "./artifactExperience";

describe("artifact experience adapter", () => {
  it("projects the owner-safe library and version detail", async () => {
    const client = {
      listArtifacts: vi.fn().mockResolvedValue(collectionSurface()),
      getArtifact: vi.fn().mockResolvedValue(artifactSurface()),
      listArtifactVersions: vi.fn().mockResolvedValue(versionsSurface()),
    };
    const items = await loadArtifactLibrary({ client, query: { tenantId: "tenant-1", workspaceId: "workspace-1", ownerUserId: "user-1" } });
    const detail = await loadArtifactDetail({ client, artifactId: "artifact-1" });
    expect(items).toEqual([expect.objectContaining({ artifactId: "artifact-1", evidenceRefCount: 2, previewReady: true })]);
    expect(detail).toEqual(expect.objectContaining({ artifactId: "artifact-1", currentVersionId: "version-1" }));
    expect(detail.files[0]).toEqual(expect.objectContaining({ previewAvailable: true, downloadAvailable: true }));
  });

  it("projects preview text and forwards lifecycle/export commands with unique keys", async () => {
    const client = {
      previewArtifactFile: vi.fn().mockResolvedValue({
        artifactFile: { artifactFileId: "file-1", fileName: "report.md", format: "MD" },
        contentType: "text/markdown", textPreview: "# 결과", truncated: false, clientMode: "mock", route: "/preview",
      }),
      submitArtifactLifecycleAction: vi.fn().mockResolvedValue({ artifactStatus: "ARCHIVED", action: "ARCHIVE" }),
      submitArtifactExportRequest: vi.fn().mockResolvedValue({ jobStatus: "COMPLETED", renderedFormats: ["PDF"] }),
    };
    await expect(loadArtifactPreview({ client, artifactId: "artifact-1", fileId: "file-1" })).resolves.toEqual({ fileName: "report.md", format: "MD", text: "# 결과", truncated: false });
    await expect(changeArtifactLifecycle({ client, artifactId: "artifact-1", action: "ARCHIVE" })).resolves.toEqual({ status: "ARCHIVED", action: "ARCHIVE" });
    await expect(exportArtifact({ client, artifactId: "artifact-1", formats: ["PDF"] })).resolves.toEqual({ status: "COMPLETED", formats: ["PDF"] });
    expect(client.submitArtifactLifecycleAction).toHaveBeenCalledWith(expect.objectContaining({ artifactId: "artifact-1", idempotencyKey: expect.stringContaining("archive:artifact-1:") }));
    expect(client.submitArtifactExportRequest).toHaveBeenCalledWith(expect.objectContaining({ targetFormats: ["PDF"], renderRequestId: expect.stringContaining("render:artifact-1:") }));
  });
});

function collectionSurface() {
  return {
    artifact_collection_surface_schema_version: "ae_web_artifact_collection_surface.v1",
    filter: { tenant_id: "tenant-1", workspace_id: "workspace-1", owner_user_id: "user-1", status: null, limit: 20 },
    count: 1, itemCount: 1, limit: 20, nextCursor: null, route: "/api/v1/artifacts", clientMode: "mock", metadata: {},
    items: [{ artifactId: "artifact-1", displayTitle: "정산 보고서", artifactStatus: "READY", artifactType: "generated_document", primaryFormat: "MD", availableFormats: ["MD"], downloadableFormats: ["MD"], previewableFormats: ["MD"], versionCount: 1, fileCount: 1, linkCount: 2, renderJobCount: 1, citationStatus: "VALIDATED", evidenceRefCount: 2 }],
  };
}

function artifactSurface() {
  return {
    artifactId: "artifact-1", artifactVersionId: "version-1", displayTitle: "정산 보고서", artifactStatus: "READY", clientMode: "mock",
    files: [{ artifactFileId: "file-1", artifactVersionId: "version-1", fileName: "report.md", format: "MD", mimeType: "text/markdown", fileSizeBytes: 120, fileHash: "f".repeat(64) }],
    links: [
      { artifactFileId: "file-1", linkType: "preview", linkRoute: "/api/v1/artifact-files/file-1/preview", accessPolicy: "owner_only" },
      { artifactFileId: "file-1", linkType: "download", linkRoute: "/api/v1/artifact-files/file-1/download", accessPolicy: "owner_only" },
    ],
  };
}

function versionsSurface() {
  return { artifactId: "artifact-1", currentVersionId: "version-1", route: "/api/v1/artifacts/artifact-1/versions", clientMode: "mock", versions: [{ artifactVersionId: "version-1", versionNo: 1, sourceContentHash: "s".repeat(64), artifactContentHash: "a".repeat(64), renderedFormats: ["MD"] }] };
}
