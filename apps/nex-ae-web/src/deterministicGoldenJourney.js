import {
  AE_ARTIFACT_RECORD_SCHEMA_VERSION,
  createMockArtifactClient
} from "./artifactClient.js";
import { runGoldenJourneyArtifact } from "./goldenJourneyArtifact.js";
import { runGoldenJourneyGrounding } from "./goldenJourneyGrounding.js";
import { runGoldenJourneyIngestion } from "./goldenJourneyIngestion.js";
import { createGoldenJourneyState } from "./goldenJourneyState.js";
import { createMockGroundedGenerationClient } from "./groundedGenerationClient.js";
import { buildGroundedGenerationRequest } from "./groundedGenerationWorkflow.js";
import { createMockSessionClient } from "./sessionClient.js";
import { createMockUploadClient } from "./uploadClient.js";
import { createMockUploadProgressClient } from "./uploadProgressClient.js";

export const DETERMINISTIC_GOLDEN_JOURNEY_SCHEMA_VERSION =
  "ae_web_deterministic_golden_journey.v1";

export async function runDeterministicGoldenJourney({
  journeyId,
  startedAt = "2026-10-06T00:00:00.000Z"
}) {
  const clock = sequenceClock(startedAt);
  const ingestion = await runGoldenJourneyIngestion({
    journeyState: createGoldenJourneyState({ journeyId, startedAt }),
    sessionClient: deterministicSessionClient(),
    loginRequest: {
      tenant_id: "tenant-local",
      employee_id: "1001",
      password: "transient-browser-value"
    },
    uploadClient: deterministicUploadClient(),
    uploadInput: {
      workspaceId: "workspace-local",
      filename: "golden-reference.md",
      contentType: "text/markdown",
      sizeBytes: 128,
      sourceSha256: "a".repeat(64)
    },
    uploadProgressClient: createMockUploadProgressClient(),
    clock
  });
  if (ingestion.status !== "INDEX_READY") {
    return failedResult(ingestion);
  }

  const grounding = await runGoldenJourneyGrounding({
    journeyState: ingestion.journeyState,
    generationClient: createMockGroundedGenerationClient(),
    generationRequest: buildGroundedGenerationRequest({
      interactionId: "interaction-golden-local",
      workspaceId: "workspace-local",
      chatDocumentId: "chat-golden-local",
      userMessage: "Produce a grounded response.",
      documentScope: { document_scope: { document_ids: ["doc-golden-local"] } },
      grounded: true
    }),
    clock
  });
  if (grounding.status !== "GROUNDING_ACCEPTED") {
    return failedResult(grounding);
  }

  const artifact = await runGoldenJourneyArtifact({
    journeyState: grounding.journeyState,
    artifactClient: createMockArtifactClient({
      artifacts: [deterministicArtifactRecord()]
    }),
    artifactId: "artifact-golden-local",
    targetFormats: ["MD", "HTML_PREVIEW"],
    renderRequestId: "render-golden-local",
    clock
  });
  if (artifact.status !== "DOWNLOAD_READY") {
    return failedResult(artifact);
  }

  return Object.freeze({
    deterministic_journey_schema_version:
      DETERMINISTIC_GOLDEN_JOURNEY_SCHEMA_VERSION,
    status: "PASS",
    evidence: artifact.evidence,
    summary: Object.freeze({
      journeyId: artifact.evidence.journey_id,
      locale: artifact.evidence.locale,
      completedStageCount: artifact.evidence.completed_stage_count,
      expectedStageCount: artifact.evidence.expected_stage_count,
      groundingQualityStatus: grounding.grounding.qualityStatus,
      renderedFormatCount: artifact.artifact.renderedFormatCount,
      previewContentPresent: artifact.preview.contentLength > 0,
      downloadContentPresent: artifact.download.contentLength > 0
    }),
    failure: null
  });
}

function failedResult(result) {
  return Object.freeze({
    deterministic_journey_schema_version:
      DETERMINISTIC_GOLDEN_JOURNEY_SCHEMA_VERSION,
    status: "FAIL",
    evidence: result.evidence,
    summary: null,
    failure: result.failure
  });
}

function deterministicSessionClient() {
  return createMockSessionClient({
    sessionSnapshot: {
      browser_session_schema_version: "oa_browser_session.v1",
      session_id: "session-golden-local",
      status: "ACTIVE",
      issuer: "nex-oa",
      audience: "nex-ae-api",
      token_use: "user",
      tenant_ref: { type: "oa.tenant", id: "tenant-local" },
      subject_ref: { type: "oa.user", id: "owner-local" },
      scopes: ["workspace:use", "documents:upload"],
      roles: ["employee"],
      issued_at: "2026-10-06T00:00:00Z",
      expires_at: "2026-10-06T01:00:00Z",
      metadata: {
        raw_token_included: false,
        service_token_included: false,
        password_included: false,
        browser_payload_owner_authoritative: false,
        claim_owner_authoritative: true
      }
    }
  });
}

function deterministicUploadClient() {
  return createMockUploadClient({
    responseFactory: payload => ({
      upload_handoff_schema_version: "ae_upload_handoff.v1",
      upload_handoff_id: "handoff-golden-local",
      workspace_id: payload.workspace_id,
      tenant_id: payload.tenant_id,
      owner_user_id: payload.owner_user_id,
      ownership_ref: payload.ownership_ref,
      status: "QUEUED",
      dedupe: { status: "CREATED" },
      source: {
        filename: payload.filename,
        content_type: payload.content_type,
        size_bytes: payload.size_bytes,
        source_sha256: payload.source_sha256
      },
      cx_document_ref: { document_id: "doc-golden-local" },
      links: {}
    })
  });
}

function deterministicArtifactRecord() {
  return {
    artifact_schema_version: AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifact_id: "artifact-golden-local",
    artifact_status: "READY",
    current_version_id: "artifact-version-golden-initial",
    target_formats: ["MD"],
    source_refs: [],
    versions: [],
    files: [],
    links: [],
    render_jobs: []
  };
}

function sequenceClock(startedAt) {
  let epoch = Date.parse(startedAt) + 1000;
  return () => {
    const value = new Date(epoch).toISOString();
    epoch += 1000;
    return value;
  };
}
