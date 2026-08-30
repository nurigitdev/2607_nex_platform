import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const APP_DIR = join(TEST_DIR, "..");
const INDEX_SOURCE = readFileSync(join(APP_DIR, "index.html"), "utf8");
const MAIN_SOURCE = readFileSync(join(APP_DIR, "src", "main.js"), "utf8");
const STYLES_SOURCE = readFileSync(join(APP_DIR, "src", "styles.css"), "utf8");

describe("AE Web artifact library shell wiring", () => {
  it("mounts the artifact library panel beside current artifact controls", () => {
    for (const expected of [
      "artifact-library-filter",
      "artifact-library-refresh-button",
      "artifact-library-status",
      "artifact-library-feedback",
      "artifact-library-summary",
      "artifact-library-list",
      "AE artifact library summary"
    ]) {
      assert.match(INDEX_SOURCE, new RegExp(expected));
    }

    for (const expected of [
      "from \"./artifactLibraryPanel.js\"",
      "artifactCollectionRoute",
      "artifactLibraryPanel: createArtifactLibraryPanelState",
      "artifactLibraryFilterMode: \"all\"",
      "refreshArtifactLibraryPanel",
      "renderArtifactLibraryPanelSurface",
      "selectArtifactFromLibrary",
      "buildCurrentArtifactLibraryQuery",
      "workspaceState.operations.artifactLibrary",
      "listArtifacts(query)",
      "buildArtifactLibraryPanelState(collectionSurface)",
      "filterArtifactLibraryPanelState("
    ]) {
      assert.match(MAIN_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });

  it("keeps library markup responsive and metadata-only", () => {
    for (const expected of [
      ".artifact-library-toolbar",
      ".artifact-library-list-surface",
      ".artifact-library-list",
      ".artifact-library-actions",
      ".artifact-library-empty"
    ]) {
      assert.match(STYLES_SOURCE, new RegExp(escapeRegExp(expected)));
    }

    for (const forbidden of [
      "raw_prompt",
      "raw_generation_output",
      "source_text",
      "service_token",
      "api_key",
      "database_url",
      "provider_url",
      "storage_ref",
      "storage_path",
      "/data/nex-platform"
    ]) {
      assert.doesNotMatch(MAIN_SOURCE, new RegExp(escapeRegExp(forbidden)));
    }
  });
});

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
