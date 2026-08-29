import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_RECORD_SCHEMA_VERSION,
  buildArtifactSurfaceFromRecord
} from "../src/artifactClient.js";
import {
  AE_WEB_ARTIFACT_CARD_COLLECTION_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION,
  ArtifactCardReadModelError,
  buildArtifactCardCollectionReadModel,
  buildArtifactCardCollectionSummary,
  buildArtifactCardReadModelSummary,
  buildArtifactCardViewModel,
  findSensitiveArtifactCardReadModelKeys
} from "../src/artifactCardReadModel.js";

function chatArtifactRef(overrides = {}) {
  return {
    artifact_id: "artifact-001",
    artifact_version_id: "artifact-version-001",
    display_title: "Generated report",
    artifact_type: "generated_document",
    artifact_status: "READY",
    primary_format: "MD",
    available_formats: ["MD"],
    preview_route: "/api/v1/artifact-files/artifact-file-001/preview",
    download_routes: {
      MD: "/api/v1/artifact-files/artifact-file-001/download"
    },
    source_generation_id: "cx-gen-001",
    source_content_hash: "c".repeat(64),
    quality_summary: {
      citation_status: "VALIDATED",
      citation_count: 2,
      evidence_ref_count: 2,
      grounding_required: true,
      retrieval_package_id: "cx-ret-001"
    },
    actions: ["preview", "view_sources", "view_lineage", "download_md"],
    ...overrides
  };
}

function artifactRecord(overrides = {}) {
  return {
    artifact_schema_version: AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifact_id: "artifact-001",
    artifact_type: "generated_document",
    artifact_status: "READY",
    current_version_id: "artifact-version-001",
    display_title: "Generated report from detail",
    target_formats: ["MD"],
    source_refs: [
      {
        cx_generation_id: "cx-gen-detail-001",
        structured_draft_content_hash: "d".repeat(64),
        quality_summary: {
          citation_status: "VALIDATED",
          citation_count: 3,
          evidence_ref_count: 3,
          grounding_required: true,
          retrieval_package_id: "cx-ret-detail-001"
        }
      }
    ],
    versions: [
      {
        artifact_version_id: "artifact-version-001",
        source_content_hash: "d".repeat(64),
        rendered_formats: ["MD"]
      }
    ],
    files: [
      {
        artifact_file_id: "artifact-file-001",
        artifact_version_id: "artifact-version-001",
        format: "MD",
        mime_type: "text/markdown",
        file_name: "generated-report.md",
        storage_ref: "ae://artifacts/artifact-001/versions/artifact-version-001/generated-report.md"
      }
    ],
    links: [
      {
        artifact_file_id: "artifact-file-001",
        link_type: "preview",
        link_route: "/api/v1/artifact-files/artifact-file-001/preview"
      },
      {
        artifact_file_id: "artifact-file-001",
        link_type: "download",
        link_route: "/api/v1/artifact-files/artifact-file-001/download"
      }
    ],
    ...overrides
  };
}

describe("AE Web artifact card read model", () => {
  it("builds a ready card view model from chat artifact refs", () => {
    const viewModel = buildArtifactCardViewModel(chatArtifactRef());
    const summary = buildArtifactCardReadModelSummary(viewModel);

    assert.equal(
      viewModel.artifact_card_schema_version,
      AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION
    );
    assert.equal(viewModel.artifactId, "artifact-001");
    assert.equal(viewModel.artifactVersionId, "artifact-version-001");
    assert.equal(viewModel.displayTitle, "Generated report");
    assert.equal(viewModel.previewAction.enabled, true);
    assert.equal(viewModel.downloadActions.length, 1);
    assert.equal(viewModel.downloadActions[0].enabled, true);
    assert.equal(viewModel.secondaryActions.length, 2);
    assert.equal(viewModel.warningStatus, "CLEAR");
    assert.equal(summary.enabled_download_action_count, 1);
    assert.equal(summary.metadata.contentRendered, false);
    assert.doesNotMatch(
      JSON.stringify(viewModel),
      /storage_ref|storage_path|service_token|database_url|provider_url|raw_prompt|source_text/
    );
  });

  it("merges persisted artifact client surfaces over sparse chat refs", () => {
    const artifactSurface = buildArtifactSurfaceFromRecord(artifactRecord());
    const viewModel = buildArtifactCardViewModel(
      {
        artifact_id: "artifact-001",
        artifact_status: "DRAFT",
        display_title: "Sparse chat ref"
      },
      { artifactSurface }
    );

    assert.equal(viewModel.displayTitle, "Generated report from detail");
    assert.equal(viewModel.artifactStatus, "READY");
    assert.equal(viewModel.sourceGenerationId, "cx-gen-detail-001");
    assert.equal(viewModel.qualitySummary.citationCount, 3);
    assert.equal(viewModel.previewAction.route.endsWith("/preview"), true);
    assert.equal(viewModel.downloadActions[0].route.endsWith("/download"), true);
  });

  it("summarizes artifact card collections with warning and action counts", () => {
    const collection = buildArtifactCardCollectionReadModel([
      chatArtifactRef(),
      chatArtifactRef({
        artifact_id: "artifact-002",
        artifact_version_id: null,
        artifact_status: "FAILED",
        preview_route: null,
        download_routes: {},
        source_generation_id: null,
        actions: ["retry_render"]
      })
    ]);
    const summary = buildArtifactCardCollectionSummary(collection);

    assert.equal(
      collection.artifact_card_collection_schema_version,
      AE_WEB_ARTIFACT_CARD_COLLECTION_SCHEMA_VERSION
    );
    assert.equal(collection.itemCount, 2);
    assert.equal(collection.readyCount, 1);
    assert.equal(collection.failedCount, 1);
    assert.equal(collection.actionableCount, 2);
    assert.equal(summary.warning_count, 4);
    assert.equal(summary.metadata.storageLocationRendered, false);
  });

  it("normalizes draft and missing-link states without enabling unsafe actions", () => {
    const viewModel = buildArtifactCardViewModel(
      chatArtifactRef({
        artifact_version_id: "",
        artifact_status: "DRAFT",
        available_formats: [],
        preview_route: "",
        download_routes: {},
        source_generation_id: "",
        quality_summary: {}
      })
    );

    assert.equal(viewModel.artifactVersionId, null);
    assert.equal(viewModel.artifactStatus, "DRAFT");
    assert.equal(viewModel.previewAction.enabled, false);
    assert.equal(viewModel.previewAction.reason, "missing_preview_route");
    assert.deepEqual(viewModel.downloadActions, []);
    assert.equal(viewModel.secondaryActions.length, 2);
    assert.equal(viewModel.secondaryActions.every(action => action.enabled), false);
    assert.deepEqual(
      viewModel.warnings.map(warning => warning.kind),
      ["missing_version", "missing_preview_route", "missing_download_route"]
    );
  });

  it("rejects invalid refs, routes, summaries, and sensitive values", () => {
    assert.throws(
      () => buildArtifactCardViewModel(null),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_REF_INVALID"
    );
    assert.throws(
      () => buildArtifactCardViewModel({ artifact_id: "" }),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_CARD_FIELD_REQUIRED"
    );
    assert.throws(
      () =>
        buildArtifactCardViewModel(
          chatArtifactRef({ preview_route: "https://outside.example/preview" })
        ),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_CARD_ROUTE_UNSAFE"
    );
    assert.throws(
      () =>
        buildArtifactCardViewModel(
          chatArtifactRef({ display_title: "/data/nex-platform/private" })
        ),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_CARD_SENSITIVE_VALUE"
    );
    assert.throws(
      () => buildArtifactCardCollectionReadModel({}),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_REFS_INVALID"
    );
    assert.throws(
      () => buildArtifactCardCollectionSummary({}),
      error =>
        error instanceof ArtifactCardReadModelError &&
        error.status === "ARTIFACT_CARD_COLLECTION_INVALID"
    );
    assert.deepEqual(
      findSensitiveArtifactCardReadModelKeys({ nested: { raw_prompt: "hidden" } }),
      ["nested.raw_prompt"]
    );
  });
});
