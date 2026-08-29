import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_CARD_RENDERER_SCHEMA_VERSION,
  assertRenderedArtifactCardSafe,
  buildArtifactCardRendererSummary,
  renderArtifactCard
} from "../src/artifactCard.js";
import {
  buildArtifactCardViewModel
} from "../src/artifactCardReadModel.js";

function artifactRef(overrides = {}) {
  return {
    artifact_id: "artifact-001",
    artifact_version_id: "artifact-version-001",
    display_title: "Generated <report>",
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
      evidence_ref_count: 2,
      grounding_required: true
    },
    actions: ["preview", "view_sources", "view_lineage", "download_md"],
    ...overrides
  };
}

describe("AE Web artifact card renderer", () => {
  it("renders a safe escaped card with preview and download anchors", () => {
    const html = renderArtifactCard(artifactRef());
    const summary = buildArtifactCardRendererSummary(artifactRef());

    assert.match(html, /data-artifact-card="artifact-001"/);
    assert.match(html, /Generated &lt;report&gt;/);
    assert.match(html, /data-artifact-preview-route="\/api\/v1\/artifact-files\/artifact-file-001\/preview"/);
    assert.match(html, /data-artifact-download-format="MD"/);
    assert.match(html, /data-artifact-secondary-action="view_lineage"/);
    assert.equal(
      summary.artifact_card_renderer_schema_version,
      AE_WEB_ARTIFACT_CARD_RENDERER_SCHEMA_VERSION
    );
    assert.equal(summary.rendered_action_count, 4);
    assert.equal(summary.enabled_action_count, 2);
    assert.equal(summary.metadata.contentRendered, false);
    assert.doesNotMatch(
      html,
      /storage_ref|storage_path|service_token|database_url|provider_url|raw_prompt|source_text|\/data\/nex-platform/i
    );
  });

  it("accepts prebuilt read models and renders disabled missing-link states", () => {
    const viewModel = buildArtifactCardViewModel(
      artifactRef({
        artifact_version_id: null,
        artifact_status: "DRAFT",
        preview_route: null,
        download_routes: {},
        source_generation_id: null,
        actions: ["view_sources", "retry_render"]
      })
    );
    const html = renderArtifactCard(viewModel);
    const summary = buildArtifactCardRendererSummary(viewModel);

    assert.match(html, /data-artifact-status="DRAFT"/);
    assert.match(html, /data-artifact-action="preview"[\s\S]*disabled/);
    assert.match(html, /Artifact version is not ready/);
    assert.match(html, /Artifact download action is not available/);
    assert.equal(summary.warning_count, 3);
    assert.equal(summary.enabled_action_count, 0);
  });

  it("renders failed artifact retry actions as enabled secondary controls", () => {
    const html = renderArtifactCard(
      artifactRef({
        artifact_status: "FAILED",
        preview_route: null,
        download_routes: {},
        actions: ["retry_render"]
      })
    );

    assert.match(html, /data-artifact-status="FAILED"/);
    assert.match(html, /data-artifact-secondary-action="retry_render"/);
    assert.doesNotMatch(
      html.match(/data-artifact-secondary-action="retry_render"[\s\S]*?>/)?.[0] || "",
      /\sdisabled(\s|>)/
    );
  });

  it("rejects unsafe rendered card payloads", () => {
    assert.throws(
      () => assertRenderedArtifactCardSafe("storage_ref=/data/nex-platform/file"),
      /unsafe fields/
    );
    assert.throws(
      () => renderArtifactCard({ artifact_id: "" }),
      /artifact_id is required/
    );
  });
});
