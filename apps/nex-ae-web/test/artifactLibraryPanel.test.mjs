import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION,
  AE_ARTIFACT_COLLECTION_SCHEMA_VERSION,
  buildArtifactCollectionSurface
} from "../src/artifactClient.js";
import {
  AE_WEB_ARTIFACT_LIBRARY_PANEL_RENDERER_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION,
  ArtifactLibraryPanelError,
  assertArtifactLibraryPanelSafe,
  buildArtifactLibraryPanelState,
  buildArtifactLibraryPanelStateFromError,
  buildArtifactLibraryPanelSummary,
  createArtifactLibraryPanelState,
  createRunningArtifactLibraryPanelState,
  filterArtifactLibraryPanelState,
  findSensitiveArtifactLibraryPanelKeys,
  renderArtifactLibraryPanel
} from "../src/artifactLibraryPanel.js";

function collectionItem(overrides = {}) {
  return {
    artifact_collection_item_schema_version:
      AE_ARTIFACT_COLLECTION_ITEM_SCHEMA_VERSION,
    artifact_id: "artifact-001",
    artifact_type: "generated_document",
    artifact_status: "READY",
    display_title: "Generated <Report>",
    language: "ko",
    artifact_intent: "create_and_export",
    target_formats: ["MD", "HTML_PREVIEW"],
    available_formats: ["MD", "HTML_PREVIEW"],
    downloadable_formats: ["MD"],
    previewable_formats: ["HTML_PREVIEW"],
    current_version_id: "artifact-version-001",
    current_version_no: 1,
    version_count: 1,
    file_count: 2,
    link_count: 4,
    render_job_count: 1,
    latest_render_job: {
      render_job_id: "render-job-001",
      job_status: "COMPLETED",
      current_stage: "FINALIZING",
      progress_percent: 100,
      retryable: false
    },
    source_summary: {
      cx_generation_id: "cx-gen-001",
      structured_draft_id: "structured-draft-001",
      retrieval_package_id: "retrieval-package-001",
      retrieval_package_hash: "r".repeat(64),
      evidence_ref_count: 2,
      source_anchor_count: 2
    },
    quality_summary: {
      citation_status: "VALIDATED",
      citation_count: 2,
      warning_count: 0,
      grounding_required: true,
      evidence_ref_count: 2
    },
    routes: {
      detail: "/api/v1/artifacts/artifact-001",
      versions: "/api/v1/artifacts/artifact-001/versions"
    },
    tenant_id: "tenant-001",
    workspace_id: "workspace-001",
    owner_user_id: "user-001",
    chat_document_id: "chat-doc-001",
    interaction_id: "interaction-001",
    created_at: "2026-08-30T08:00:00Z",
    updated_at: "2026-08-30T09:00:00Z",
    ...overrides
  };
}

function collectionSurface(items = [collectionItem()], overrides = {}) {
  return buildArtifactCollectionSurface(
    {
      artifact_collection_schema_version: AE_ARTIFACT_COLLECTION_SCHEMA_VERSION,
      filter: {
        tenant_id: "tenant-001",
        workspace_id: "workspace-001",
        owner_user_id: "user-001",
        status: null,
        limit: 20
      },
      count: items.length,
      limit: 20,
      next_cursor: null,
      items,
      ...overrides
    },
    {
      clientMode: "fetch",
      route: "/api/v1/artifacts?tenant_id=tenant-001&workspace_id=workspace-001&owner_user_id=user-001&limit=20"
    }
  );
}

describe("AE Web artifact library panel", () => {
  it("creates ready and running states with safe summaries", () => {
    const ready = createArtifactLibraryPanelState({
      items: [
        {
          artifactId: "artifact-001",
          displayTitle: "Generated report",
          artifactStatus: "READY",
          availableFormats: ["MD"],
          downloadableFormats: ["MD"],
          previewableFormats: [],
          routes: {
            detail: "/api/v1/artifacts/artifact-001",
            versions: "/api/v1/artifacts/artifact-001/versions"
          }
        }
      ],
      query: {
        tenant_id: "tenant-001",
        workspace_id: "workspace-001",
        owner_user_id: "user-001",
        limit: 20
      }
    });
    const running = createRunningArtifactLibraryPanelState({
      route: "/api/v1/artifacts?tenant_id=tenant-001&workspace_id=workspace-001&owner_user_id=user-001&limit=20",
      clientMode: "fetch"
    });

    assert.equal(
      ready.artifact_library_panel_schema_version,
      AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION
    );
    assert.equal(buildArtifactLibraryPanelSummary(ready).ready_count, 1);
    assert.equal(running.status, "RUNNING");
    assert.equal(renderArtifactLibraryPanel(running).severity, "running");
    assert.doesNotMatch(
      JSON.stringify(buildArtifactLibraryPanelSummary(ready)),
      /service_token|database_url|provider_url|storage_ref|\/data\/nex-platform/
    );
  });

  it("builds a library read-model from collection surfaces without private fields", () => {
    const state = buildArtifactLibraryPanelState(collectionSurface());
    const summary = buildArtifactLibraryPanelSummary(state);
    const view = renderArtifactLibraryPanel(state);
    const serialized = JSON.stringify({ state, summary, view });

    assert.equal(state.status, "READY");
    assert.equal(state.clientMode, "fetch");
    assert.equal(state.itemCount, 1);
    assert.equal(state.items[0].artifactId, "artifact-001");
    assert.equal(state.items[0].displayTitle, "Generated <Report>");
    assert.equal(state.items[0].primaryFormat, "MD");
    assert.equal(state.items[0].downloadReady, true);
    assert.equal(state.items[0].previewReady, true);
    assert.equal(state.items[0].citationStatus, "VALIDATED");
    assert.equal(state.items[0].evidenceRefCount, 2);
    assert.equal(summary.item_count, 1);
    assert.equal(summary.downloadable_count, 1);
    assert.equal(summary.previewable_count, 1);
    assert.deepEqual(summary.formats, ["HTML_PREVIEW", "MD"]);
    assert.equal(
      view.artifact_library_panel_renderer_schema_version,
      AE_WEB_ARTIFACT_LIBRARY_PANEL_RENDERER_SCHEMA_VERSION
    );
    assert.match(view.summaryHtml, /artifacts|ready|actions|formats/);
    assert.match(view.listHtml, /Generated &lt;Report&gt;/);
    assert.doesNotMatch(view.listHtml, /Generated <Report>/);
    assert.doesNotMatch(
      serialized,
      /storage_ref|storage_path|content_base64|rendered_markdown|\/data\/nex-platform/
    );
  });

  it("handles empty collections and retryable failures", () => {
    const empty = buildArtifactLibraryPanelState(collectionSurface([]));
    const error = new Error("offline");
    error.status = "NETWORK_ERROR";
    error.retryable = true;
    const failed = buildArtifactLibraryPanelStateFromError(error, {
      route: "/api/v1/artifacts?tenant_id=tenant-001&workspace_id=workspace-001&owner_user_id=user-001&limit=20",
      clientMode: "fetch"
    });

    assert.equal(empty.status, "EMPTY");
    assert.equal(renderArtifactLibraryPanel(empty).severity, "pending");
    assert.match(renderArtifactLibraryPanel(empty).listHtml, /No artifacts/);
    assert.equal(failed.status, "UNAVAILABLE");
    assert.equal(failed.retryable, true);
    assert.equal(buildArtifactLibraryPanelSummary(failed).error_status, "NETWORK_ERROR");
    assert.equal(renderArtifactLibraryPanel(failed).severity, "danger");
  });

  it("filters ready, failed, downloadable, and previewable library items", () => {
    const state = buildArtifactLibraryPanelState(
      collectionSurface([
        collectionItem(),
        collectionItem({
          artifact_id: "artifact-002",
          artifact_status: "FAILED",
          display_title: "Failed report",
          downloadable_formats: [],
          previewable_formats: [],
          routes: {
            detail: "/api/v1/artifacts/artifact-002",
            versions: "/api/v1/artifacts/artifact-002/versions"
          }
        }),
        collectionItem({
          artifact_id: "artifact-003",
          artifact_status: "DRAFT",
          display_title: "Preview report",
          downloadable_formats: [],
          previewable_formats: ["HTML_PREVIEW"],
          routes: {
            detail: "/api/v1/artifacts/artifact-003",
            versions: "/api/v1/artifacts/artifact-003/versions"
          }
        })
      ])
    );

    assert.equal(filterArtifactLibraryPanelState(state, "ready").itemCount, 1);
    assert.equal(filterArtifactLibraryPanelState(state, "failed").items[0].artifactId, "artifact-002");
    assert.equal(filterArtifactLibraryPanelState(state, "downloadable").items[0].artifactId, "artifact-001");
    assert.deepEqual(
      filterArtifactLibraryPanelState(state, "previewable").items.map(item => item.artifactId),
      ["artifact-001", "artifact-003"]
    );
    assert.equal(filterArtifactLibraryPanelState(state, "all").itemCount, 3);
  });

  it("rejects invalid states, routes, numbers, filters, and unsafe payloads", () => {
    assert.throws(
      () => buildArtifactLibraryPanelState({}),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_COLLECTION_SURFACE_INVALID"
    );
    assert.throws(
      () => createArtifactLibraryPanelState({ status: "DONE" }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_STATUS_UNSUPPORTED"
    );
    assert.throws(
      () => createArtifactLibraryPanelState({ filterMode: "mine" }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_FILTER_UNSUPPORTED"
    );
    assert.throws(
      () => createArtifactLibraryPanelState({ route: "https://example.test" }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_ROUTE_INVALID"
    );
    assert.throws(
      () => createArtifactLibraryPanelState({ items: "bad" }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_ITEMS_INVALID"
    );
    assert.throws(
      () =>
        createArtifactLibraryPanelState({
          items: [
            {
              artifactId: "artifact-001",
              versionCount: -1,
              routes: {
                detail: "/api/v1/artifacts/artifact-001",
                versions: "/api/v1/artifacts/artifact-001/versions"
              }
            }
          ]
        }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_NUMBER_INVALID"
    );
    assert.throws(
      () => buildArtifactLibraryPanelSummary({}),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_PANEL_SCHEMA_INVALID"
    );
    assert.deepEqual(
      findSensitiveArtifactLibraryPanelKeys({
        nested: { storage_ref: "hidden" },
        metadata: { rawPromptRendered: false }
      }),
      ["nested.storage_ref"]
    );
    assert.throws(
      () =>
        assertArtifactLibraryPanelSafe({
          displayTitle: "/data/nex-platform/ae/artifacts"
        }),
      error =>
        error instanceof ArtifactLibraryPanelError &&
        error.status === "ARTIFACT_LIBRARY_PANEL_SENSITIVE_VALUE"
    );
  });
});
