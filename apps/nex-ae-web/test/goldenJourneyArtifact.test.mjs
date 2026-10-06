import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_RECORD_SCHEMA_VERSION,
  createMockArtifactClient
} from "../src/artifactClient.js";
import { runGoldenJourneyArtifact } from "../src/goldenJourneyArtifact.js";
import {
  advanceGoldenJourney,
  createGoldenJourneyState
} from "../src/goldenJourneyState.js";

describe("AE Web artifact golden journey", () => {
  it("completes render, preview, and download without retaining content", async () => {
    const result = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-001"),
      artifactClient: createMockArtifactClient({ artifacts: [artifactRecord()] }),
      artifactId: "artifact-001",
      renderRequestId: "golden-render-001",
      clock: sequenceClock(7)
    });

    assert.equal(result.status, "DOWNLOAD_READY");
    assert.equal(result.journeyState.status, "COMPLETED");
    assert.equal(result.journeyState.completed_stages.length, 9);
    assert.equal(result.artifact.renderedFormatCount, 2);
    assert.equal(result.preview.format, "HTML_PREVIEW");
    assert.ok(result.preview.contentLength > 0);
    assert.equal(result.download.format, "MD");
    assert.ok(result.download.contentLength > 0);
    assert.equal(result.download.contentHashPresent, true);
    const serialized = JSON.stringify(result);
    assert.doesNotMatch(serialized, /Generated artifact|Preview is available|Download is available/);
    assert.doesNotMatch(serialized, /storage_ref|textPreview|contentBase64/);
  });

  it("fails closed when export completion or requested formats are incomplete", async () => {
    const incomplete = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-002"),
      artifactClient: {
        async submitArtifactExportRequest() {
          return {
            jobStatus: "RUNNING",
            progressPercent: 50,
            renderedFormats: ["MD"],
            artifactSurface: { artifactStatus: "RENDERING" }
          };
        }
      },
      artifactId: "artifact-002",
      clock: sequenceClock(7)
    });
    assert.equal(incomplete.failure.failureCode, "ARTIFACT_FAILED");
    assert.equal(incomplete.evidence.failure.failed_stage, "ARTIFACT_READY");

    const base = createMockArtifactClient({ artifacts: [artifactRecord()] });
    const formats = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-003"),
      artifactClient: {
        ...base,
        async submitArtifactExportRequest(request) {
          const surface = await base.submitArtifactExportRequest(request);
          return { ...surface, renderedFormats: ["MD"] };
        }
      },
      artifactId: "artifact-001",
      renderRequestId: "golden-render-incomplete",
      clock: sequenceClock(7)
    });
    assert.equal(formats.failure.failureCode, "ARTIFACT_FAILED");
  });

  it("maps preview and download failures to their exact terminal stage", async () => {
    const previewBase = createMockArtifactClient({ artifacts: [artifactRecord()] });
    const previewFailure = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-004"),
      artifactClient: {
        ...previewBase,
        async previewArtifactFile() {
          throw Object.assign(new Error("private preview"), { retryable: true });
        }
      },
      artifactId: "artifact-001",
      renderRequestId: "golden-render-preview-failure",
      clock: sequenceClock(7)
    });
    assert.equal(previewFailure.failure.failureCode, "PREVIEW_FAILED");
    assert.equal(previewFailure.failure.retryable, true);
    assert.equal(previewFailure.evidence.failure.failed_stage, "PREVIEW_READY");
    assert.doesNotMatch(JSON.stringify(previewFailure), /private preview/);

    const downloadBase = createMockArtifactClient({ artifacts: [artifactRecord()] });
    const downloadFailure = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-005"),
      artifactClient: {
        ...downloadBase,
        async downloadArtifactFile() {
          throw new Error("private download");
        }
      },
      artifactId: "artifact-001",
      renderRequestId: "golden-render-download-failure",
      clock: sequenceClock(7)
    });
    assert.equal(downloadFailure.failure.failureCode, "DOWNLOAD_FAILED");
    assert.equal(downloadFailure.evidence.failure.failed_stage, "DOWNLOAD_READY");
    assert.doesNotMatch(JSON.stringify(downloadFailure), /private download/);
  });

  it("rejects mismatched artifact-file lineage", async () => {
    const base = createMockArtifactClient({ artifacts: [artifactRecord()] });
    const mismatch = await runGoldenJourneyArtifact({
      journeyState: groundedState("journey-artifact-006"),
      artifactClient: {
        ...base,
        async previewArtifactFile() {
          return {
            artifactFile: {
              artifactFileId: "artifact-file-other",
              artifactId: "artifact-other"
            },
            textPreview: "hidden",
            route: "/api/v1/artifact-files/artifact-file-other/preview"
          };
        }
      },
      artifactId: "artifact-001",
      renderRequestId: "golden-render-mismatch",
      clock: sequenceClock(7)
    });
    assert.equal(mismatch.failure.failureCode, "PREVIEW_FAILED");
  });
});

function groundedState(journeyId) {
  let state = createGoldenJourneyState({
    journeyId,
    startedAt: "2026-10-06T00:00:00.000Z"
  });
  const stages = [
    ["SESSION_AUTHENTICATED", { subject_ref: "owner-local" }],
    ["UPLOAD_ACCEPTED", { upload_handoff_id: "handoff-local" }],
    ["INGESTION_INDEXED", { processing_run_id: "run-local" }],
    ["RETRIEVAL_READY", { retrieval_id: "retrieval-local" }],
    ["GENERATION_COMPLETED", { generation_id: "generation-local" }],
    ["GROUNDING_ACCEPTED", { response_id: "response-local" }]
  ];
  stages.forEach(([stage, refs], index) => {
    state = advanceGoldenJourney(state, {
      stage,
      occurredAt: `2026-10-06T00:00:0${index + 1}.000Z`,
      refs
    });
  });
  return state;
}

function artifactRecord() {
  return {
    artifact_schema_version: AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifact_id: "artifact-001",
    artifact_status: "READY",
    current_version_id: "artifact-version-initial",
    target_formats: ["MD"],
    source_refs: [],
    versions: [],
    files: [],
    links: [],
    render_jobs: []
  };
}

function sequenceClock(start) {
  let second = start;
  return () => `2026-10-06T00:00:${String(second++).padStart(2, "0")}.000Z`;
}
