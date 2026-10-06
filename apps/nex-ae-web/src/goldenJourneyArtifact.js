import {
  advanceGoldenJourney,
  buildGoldenJourneyEvidence,
  failGoldenJourney
} from "./goldenJourneyState.js";

export const GOLDEN_JOURNEY_ARTIFACT_SCHEMA_VERSION =
  "ae_web_golden_journey_artifact.v1";

export async function runGoldenJourneyArtifact({
  journeyState,
  artifactClient,
  artifactId,
  targetFormats = ["MD", "HTML_PREVIEW"],
  renderRequestId,
  clock = () => new Date().toISOString()
}) {
  let state = journeyState;
  let phase = "ARTIFACT";
  try {
    const exportSurface = await artifactClient.submitArtifactExportRequest({
      artifactId,
      targetFormats,
      renderRequestId
    });
    assertCompletedExport(exportSurface, targetFormats);
    const previewFile = selectFile(
      exportSurface.artifactSurface,
      "preview",
      ["HTML_PREVIEW", "MD"]
    );
    const downloadFile = selectFile(
      exportSurface.artifactSurface,
      "download",
      ["MD", "PDF", "HTML_PREVIEW"]
    );
    state = advanceGoldenJourney(state, {
      stage: "ARTIFACT_READY",
      occurredAt: clock(),
      refs: {
        artifact_id: exportSurface.artifactId,
        artifact_file_id: previewFile.artifactFileId
      }
    });

    phase = "PREVIEW";
    const preview = await artifactClient.previewArtifactFile(
      previewFile.artifactFileId
    );
    assertArtifactFileMatch(preview?.artifactFile, previewFile, "preview");
    const previewLength = String(preview.textPreview || "").length;
    if (previewLength === 0 || !preview.route) {
      throw boundedError("PREVIEW_NOT_READY", false);
    }
    state = advanceGoldenJourney(state, {
      stage: "PREVIEW_READY",
      occurredAt: clock(),
      refs: {
        artifact_id: exportSurface.artifactId,
        artifact_file_id: previewFile.artifactFileId
      }
    });

    phase = "DOWNLOAD";
    const download = await artifactClient.downloadArtifactFile(
      downloadFile.artifactFileId
    );
    assertArtifactFileMatch(download?.artifactFile, downloadFile, "download");
    if (download.contentLength <= 0 || !download.route) {
      throw boundedError("DOWNLOAD_NOT_READY", false);
    }
    state = advanceGoldenJourney(state, {
      stage: "DOWNLOAD_READY",
      occurredAt: clock(),
      refs: {
        artifact_id: exportSurface.artifactId,
        artifact_file_id: downloadFile.artifactFileId
      },
      details: { download_format: downloadFile.format }
    });

    return Object.freeze({
      journey_artifact_schema_version: GOLDEN_JOURNEY_ARTIFACT_SCHEMA_VERSION,
      status: "DOWNLOAD_READY",
      journeyState: state,
      evidence: buildGoldenJourneyEvidence(state),
      artifact: Object.freeze({
        artifactId: exportSurface.artifactId,
        artifactVersionId: exportSurface.artifactVersionId,
        renderJobId: exportSurface.renderJobId,
        renderedFormatCount: exportSurface.renderedFormats.length
      }),
      preview: Object.freeze({
        artifactFileId: previewFile.artifactFileId,
        format: previewFile.format,
        contentType: preview.contentType,
        contentLength: previewLength,
        truncated: preview.truncated
      }),
      download: Object.freeze({
        artifactFileId: downloadFile.artifactFileId,
        format: downloadFile.format,
        contentType: download.contentType,
        contentLength: download.contentLength,
        contentHashPresent: Boolean(download.contentHash)
      }),
      failure: null
    });
  } catch (error) {
    const failureCode = phaseFailureCode(phase);
    const failedState = failGoldenJourney(state, {
      failureCode,
      occurredAt: clock(),
      retryable: Boolean(error?.retryable)
    });
    return Object.freeze({
      journey_artifact_schema_version: GOLDEN_JOURNEY_ARTIFACT_SCHEMA_VERSION,
      status: "FAILED",
      journeyState: failedState,
      evidence: buildGoldenJourneyEvidence(failedState),
      artifact: null,
      preview: null,
      download: null,
      failure: Object.freeze({
        failureCode,
        failedPhase: phase,
        retryable: Boolean(error?.retryable)
      })
    });
  }
}

function assertCompletedExport(surface, targetFormats) {
  if (
    surface?.jobStatus !== "COMPLETED" ||
    surface?.artifactSurface?.artifactStatus !== "READY" ||
    surface?.progressPercent !== 100
  ) {
    throw boundedError("ARTIFACT_RENDER_INCOMPLETE", false);
  }
  const rendered = new Set(surface.renderedFormats || []);
  if (!targetFormats.every(format => rendered.has(format))) {
    throw boundedError("ARTIFACT_FORMAT_INCOMPLETE", false);
  }
}

function selectFile(surface, linkType, preferredFormats) {
  const linkedFileIds = new Set(
    (surface?.links || [])
      .filter(link => link.linkType === linkType && link.linkRoute)
      .map(link => link.artifactFileId)
  );
  const linkedFiles = (surface?.files || []).filter(file =>
    linkedFileIds.has(file.artifactFileId)
  );
  for (const format of preferredFormats) {
    const match = linkedFiles.find(file => file.format === format);
    if (match) return match;
  }
  if (linkedFiles[0]) return linkedFiles[0];
  throw boundedError(`${linkType.toUpperCase()}_FILE_UNAVAILABLE`, false);
}

function assertArtifactFileMatch(actual, expected, operation) {
  if (
    !actual ||
    actual.artifactFileId !== expected.artifactFileId ||
    actual.artifactId !== expected.artifactId
  ) {
    throw boundedError(`${operation.toUpperCase()}_FILE_MISMATCH`, false);
  }
}

function boundedError(status, retryable) {
  return Object.assign(new Error("Golden journey artifact operation failed."), {
    status,
    retryable: Boolean(retryable)
  });
}

function phaseFailureCode(phase) {
  return {
    ARTIFACT: "ARTIFACT_FAILED",
    PREVIEW: "PREVIEW_FAILED",
    DOWNLOAD: "DOWNLOAD_FAILED"
  }[phase] || "ARTIFACT_FAILED";
}
