import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_RECORD_SCHEMA_VERSION,
  buildArtifactSurfaceFromRecord,
  buildArtifactVersionsSurface
} from "../src/artifactClient.js";
import {
  AE_WEB_ARTIFACT_VERSION_PANEL_SCHEMA_VERSION,
  ArtifactVersionPanelError,
  assertArtifactVersionPanelSafe,
  buildArtifactVersionPanelState,
  buildArtifactVersionPanelStateFromError,
  buildArtifactVersionPanelSummary,
  createArtifactVersionPanelState,
  createRunningArtifactVersionPanelState,
  findSensitiveArtifactVersionPanelKeys,
  renderArtifactVersionPanel
} from "../src/artifactVersionPanel.js";

function artifactRecord(overrides = {}) {
  return {
    artifact_schema_version: AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifact_id: "artifact-001",
    artifact_type: "generated_document",
    artifact_status: "READY",
    current_version_id: "artifact-version-002",
    chat_document_id: "chat-doc-001",
    interaction_id: "interaction-001",
    display_title: "Generated <Report>",
    target_formats: ["MD", "HTML_PREVIEW"],
    source_refs: [
      {
        cx_generation_id: "cx-gen-001",
        structured_draft_content_hash: "c".repeat(64),
        evidence_ref_count: 2,
        quality_summary: {
          citation_status: "VALIDATED",
          citation_count: 2,
          evidence_ref_count: 2,
          grounding_required: true
        }
      }
    ],
    versions: [
      {
        artifact_version_id: "artifact-version-001",
        version_no: 1,
        source_content_hash: "a".repeat(64),
        artifact_content_hash: "b".repeat(64),
        rendered_formats: ["MD"]
      },
      {
        artifact_version_id: "artifact-version-002",
        version_no: 2,
        source_content_hash: "c".repeat(64),
        artifact_content_hash: "d".repeat(64),
        rendered_formats: ["MD", "HTML_PREVIEW"]
      }
    ],
    files: [
      {
        artifact_file_id: "artifact-file-001",
        artifact_id: "artifact-001",
        artifact_version_id: "artifact-version-001",
        format: "MD",
        mime_type: "text/markdown",
        file_name: "report-v1.md",
        storage_ref: "ae://artifacts/artifact-001/versions/artifact-version-001/report-v1.md",
        file_size_bytes: 512,
        file_hash: "e".repeat(64),
        source_version_hash: "a".repeat(64)
      },
      {
        artifact_file_id: "artifact-file-002",
        artifact_id: "artifact-001",
        artifact_version_id: "artifact-version-002",
        format: "HTML_PREVIEW",
        mime_type: "text/html",
        file_name: "report-v2.html",
        storage_ref: "ae://artifacts/artifact-001/versions/artifact-version-002/report-v2.html",
        file_size_bytes: 2048,
        file_hash: "f".repeat(64),
        source_version_hash: "c".repeat(64)
      }
    ],
    links: [
      {
        artifact_file_id: "artifact-file-002",
        link_type: "preview",
        link_route: "/api/v1/artifact-files/artifact-file-002/preview",
        access_policy: "owner_only"
      },
      {
        artifact_file_id: "artifact-file-002",
        link_type: "download",
        link_route: "/api/v1/artifact-files/artifact-file-002/download",
        access_policy: "owner_only"
      }
    ],
    ...overrides
  };
}

function panelState(record = artifactRecord()) {
  return buildArtifactVersionPanelState({
    artifactSurface: buildArtifactSurfaceFromRecord(record, {
      clientMode: "fetch",
      route: "/api/v1/artifacts/artifact-001"
    }),
    versionsSurface: buildArtifactVersionsSurface(
      {
        artifact_id: record.artifact_id,
        current_version_id: record.current_version_id,
        versions: record.versions
      },
      {
        clientMode: "fetch",
        route: "/api/v1/artifacts/artifact-001/versions"
      }
    )
  });
}

describe("AE Web artifact version panel", () => {
  it("creates idle and running states with safe metadata", () => {
    const idle = createArtifactVersionPanelState({ clientMode: "mock" });
    const running = createRunningArtifactVersionPanelState({
      artifactId: "artifact-001",
      currentVersionId: "artifact-version-002",
      route: "/api/v1/artifacts/artifact-001/versions",
      clientMode: "fetch"
    });

    assert.equal(
      idle.artifact_version_panel_schema_version,
      AE_WEB_ARTIFACT_VERSION_PANEL_SCHEMA_VERSION
    );
    assert.equal(buildArtifactVersionPanelSummary(idle).status, "READY");
    assert.equal(running.status, "RUNNING");
    assert.equal(renderArtifactVersionPanel(running).severity, "running");
    assert.doesNotMatch(
      JSON.stringify(buildArtifactVersionPanelSummary(running)),
      /service_token|database_url|provider_url|storage_ref|\/data\/nex-platform/
    );
  });

  it("builds version and file read-models without rendering raw hashes or storage", () => {
    const state = panelState();
    const summary = buildArtifactVersionPanelSummary(state);
    const view = renderArtifactVersionPanel(state);
    const serialized = JSON.stringify({ state, summary, view });

    assert.equal(state.status, "VERSION_READY");
    assert.equal(state.artifactId, "artifact-001");
    assert.equal(state.currentVersionId, "artifact-version-002");
    assert.equal(state.versions.length, 2);
    assert.equal(state.versions[1].current, true);
    assert.equal(state.versions[1].files[0].fileName, "report-v2.html");
    assert.equal(summary.file_count, 2);
    assert.deepEqual(summary.formats, ["MD", "HTML_PREVIEW"]);
    assert.equal(summary.preview_route_count, 1);
    assert.equal(summary.download_route_count, 1);
    assert.equal(summary.hash_presence_count, 4);
    assert.match(view.listHtml, /report-v2.html/);
    assert.doesNotMatch(serialized, /storage_ref|ae:\/\/artifacts|eeee|ffff/);
    assert.doesNotMatch(view.summaryHtml, /<Report>/);
    assert.match(view.summaryHtml, /VERSION_READY|versions|files|formats/);
  });

  it("marks empty artifact version responses as an empty but safe state", () => {
    const record = artifactRecord({
      current_version_id: null,
      versions: [],
      files: [],
      links: []
    });
    const state = panelState(record);
    const view = renderArtifactVersionPanel(state);

    assert.equal(state.status, "EMPTY");
    assert.equal(buildArtifactVersionPanelSummary(state).version_count, 0);
    assert.match(view.listHtml, /No rendered versions/);
    assert.equal(view.severity, "pending");
  });

  it("normalizes failures as retryable unavailable states", () => {
    const error = new Error("offline");
    error.status = "NETWORK_ERROR";
    error.retryable = true;
    const state = buildArtifactVersionPanelStateFromError(error, {
      artifactId: "artifact-001",
      route: "/api/v1/artifacts/artifact-001/versions",
      clientMode: "fetch"
    });
    const summary = buildArtifactVersionPanelSummary(state);
    const view = renderArtifactVersionPanel(state);

    assert.equal(state.status, "UNAVAILABLE");
    assert.equal(state.retryable, true);
    assert.equal(summary.client_mode, "fetch");
    assert.equal(view.severity, "danger");
    assert.match(view.feedback, /NETWORK_ERROR/);
  });

  it("rejects invalid state and unsafe payloads", () => {
    assert.throws(
      () => createArtifactVersionPanelState({ status: "DONE" }),
      error =>
        error instanceof ArtifactVersionPanelError &&
        error.status === "ARTIFACT_VERSION_STATUS_UNSUPPORTED"
    );
    assert.throws(
      () => createArtifactVersionPanelState({ route: "https://example.test/api" }),
      error =>
        error instanceof ArtifactVersionPanelError &&
        error.status === "ARTIFACT_VERSION_ROUTE_INVALID"
    );
    assert.throws(
      () => createArtifactVersionPanelState({ files: [{ format: "MD" }] }),
      error =>
        error instanceof ArtifactVersionPanelError &&
        error.status === "ARTIFACT_FILE_ID_INVALID"
    );
    assert.throws(
      () => buildArtifactVersionPanelSummary({}),
      error =>
        error instanceof ArtifactVersionPanelError &&
        error.status === "ARTIFACT_VERSION_PANEL_SCHEMA_INVALID"
    );
    assert.deepEqual(
      findSensitiveArtifactVersionPanelKeys({
        nested: { storage_ref: "hidden" },
        metadata: { rawPromptRendered: false }
      }),
      ["nested.storage_ref"]
    );
    assert.throws(
      () => assertArtifactVersionPanelSafe({ safe: "/data/nex-platform/ae/artifacts" }),
      error =>
        error instanceof ArtifactVersionPanelError &&
        error.status === "ARTIFACT_VERSION_PANEL_SENSITIVE_VALUE"
    );
  });
});
