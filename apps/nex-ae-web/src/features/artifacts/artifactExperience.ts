import { buildArtifactLibraryPanelState } from "../../artifactLibraryPanel.js";
import { buildArtifactPreviewPanelStateFromPreview } from "../../artifactPreviewPanel.js";
import { buildArtifactVersionPanelState } from "../../artifactVersionPanel.js";
import { saveArtifactDownload } from "../../artifactDownloadSaveAdapter.js";

export interface ArtifactListItemProjection {
  readonly artifactId: string;
  readonly displayTitle: string;
  readonly artifactStatus: string;
  readonly primaryFormat: string;
  readonly availableFormats: readonly string[];
  readonly previewReady: boolean;
  readonly downloadReady: boolean;
  readonly versionCount: number;
  readonly citationStatus: string;
  readonly evidenceRefCount: number;
}

export interface ArtifactFileProjection {
  readonly artifactFileId: string;
  readonly fileName: string;
  readonly format: string;
  readonly previewAvailable: boolean;
  readonly downloadAvailable: boolean;
}

export interface ArtifactDetailProjection {
  readonly artifactId: string;
  readonly displayTitle: string;
  readonly artifactStatus: string;
  readonly currentVersionId: string | null;
  readonly versions: readonly { readonly id: string; readonly number: number | null; readonly current: boolean; readonly formats: readonly string[] }[];
  readonly files: readonly ArtifactFileProjection[];
}

export async function loadArtifactLibrary({ client, query }: { readonly client: any; readonly query: Record<string, unknown> }) {
  const collection = await client.listArtifacts(query);
  const state = buildArtifactLibraryPanelState(collection) as any;
  return Object.freeze((state.items as any[]).map(item => Object.freeze({
    artifactId: String(item.artifactId),
    displayTitle: String(item.displayTitle),
    artifactStatus: String(item.artifactStatus),
    primaryFormat: String(item.primaryFormat),
    availableFormats: Object.freeze([...item.availableFormats].map(String)),
    previewReady: item.previewReady === true,
    downloadReady: item.downloadReady === true,
    versionCount: Number(item.versionCount || 0),
    citationStatus: String(item.citationStatus || "UNKNOWN"),
    evidenceRefCount: Number(item.evidenceRefCount || 0),
  })) as readonly ArtifactListItemProjection[]);
}

export async function loadArtifactDetail({ client, artifactId }: { readonly client: any; readonly artifactId: string }): Promise<ArtifactDetailProjection> {
  const [artifact, versions] = await Promise.all([
    client.getArtifact(artifactId),
    client.listArtifactVersions(artifactId),
  ]);
  const panel = buildArtifactVersionPanelState({ artifactSurface: artifact, versionsSurface: versions }) as any;
  return Object.freeze({
    artifactId: String(panel.artifactId),
    displayTitle: String(panel.displayTitle || artifact.displayTitle),
    artifactStatus: String(artifact.artifactStatus),
    currentVersionId: panel.currentVersionId ? String(panel.currentVersionId) : null,
    versions: Object.freeze((panel.versions as any[]).map(version => Object.freeze({
      id: String(version.artifactVersionId),
      number: Number.isInteger(version.versionNo) ? Number(version.versionNo) : null,
      current: version.current === true,
      formats: Object.freeze([...version.renderedFormats].map(String)),
    }))),
    files: Object.freeze((panel.files as any[]).map(file => Object.freeze({
      artifactFileId: String(file.artifactFileId),
      fileName: String(file.fileName),
      format: String(file.format),
      previewAvailable: Boolean(file.previewRoute),
      downloadAvailable: Boolean(file.downloadRoute),
    }))),
  });
}

export async function loadArtifactPreview({ client, artifactId, fileId }: { readonly client: any; readonly artifactId: string; readonly fileId: string }) {
  const surface = await client.previewArtifactFile(fileId);
  const panel = (buildArtifactPreviewPanelStateFromPreview as any)(surface, { artifactId }) as any;
  return Object.freeze({
    fileName: String(panel.preview.fileName),
    format: String(panel.preview.format),
    text: String(panel.preview.textPreview),
    truncated: panel.preview.truncated === true,
  });
}

export async function saveArtifactFile({ client, fileId }: { readonly client: any; readonly fileId: string }) {
  const surface = await client.downloadArtifactFile(fileId);
  const saved = saveArtifactDownload(surface) as any;
  return Object.freeze({ status: String(saved.status), fileName: String(saved.fileName) });
}

export async function changeArtifactLifecycle({
  client,
  artifactId,
  action,
}: {
  readonly client: any;
  readonly artifactId: string;
  readonly action: "ARCHIVE" | "RESTORE" | "MARK_DELETED";
}) {
  const result = await client.submitArtifactLifecycleAction({
    artifactId,
    action,
    idempotencyKey: `${action.toLowerCase()}:${artifactId}:${crypto.randomUUID()}`,
  });
  return Object.freeze({ status: String(result.artifactStatus), action: String(result.action) });
}

export async function exportArtifact({
  client,
  artifactId,
  formats,
}: {
  readonly client: any;
  readonly artifactId: string;
  readonly formats: readonly string[];
}) {
  const result = await client.submitArtifactExportRequest({
    artifactId,
    renderRequestId: `render:${artifactId}:${crypto.randomUUID()}`,
    targetFormats: formats,
  });
  return Object.freeze({ status: String(result.jobStatus), formats: Object.freeze([...result.renderedFormats].map(String)) });
}
