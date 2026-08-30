import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION,
  assertArtifactDownloadFormatSelectorSafe,
  buildArtifactDownloadFormatSelector,
  buildArtifactDownloadFormatSelectorSummary,
  findSensitiveArtifactDownloadFormatSelectorKeys,
  renderArtifactDownloadFormatSelector
} from "../src/artifactDownloadFormatSelector.js";

const MAIN_SOURCE = readFileSync(
  new URL("../src/main.js", import.meta.url),
  "utf-8"
);

function artifactRef(overrides = {}) {
  return {
    artifactId: "artifact-0437",
    artifactVersionId: "version-0437",
    displayTitle: "Delivery report",
    primaryFormat: "PDF",
    availableFormats: ["MD", "DOCX", "PDF"],
    downloadRoutes: {
      MD: "/api/v1/artifact-files/file-md-0437/download",
      PDF: "/api/v1/artifact-files/file-pdf-0437/download"
    },
    clientMode: "fetch",
    ...overrides
  };
}

describe("AE Web artifact download format selector", () => {
  it("builds selected, enabled, and disabled format options", () => {
    const selector = buildArtifactDownloadFormatSelector({
      artifactRef: artifactRef(),
      selectedFormat: "PDF",
      clientMode: "fetch"
    });
    const summary = buildArtifactDownloadFormatSelectorSummary(selector);

    assert.equal(
      selector.artifact_download_format_selector_schema_version,
      AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION
    );
    assert.equal(selector.status, "READY");
    assert.equal(selector.selectedFormat, "PDF");
    assert.equal(selector.options.length, 3);
    assert.equal(selector.options.find(option => option.format === "PDF").selected, true);
    assert.equal(selector.options.find(option => option.format === "DOCX").enabled, false);
    assert.equal(summary.enabled_option_count, 2);
    assert.equal(summary.disabled_option_count, 1);
    assert.equal(summary.selected_route_present, true);
  });

  it("falls back to the first enabled route and renders safe action anchors", () => {
    const selector = buildArtifactDownloadFormatSelector({
      artifactRef: artifactRef({
        primaryFormat: "DOCX",
        downloadRoutes: {
          MD: "/api/v1/artifact-files/file-md-0437/download"
        }
      }),
      selectedFormat: "PDF"
    });
    const view = renderArtifactDownloadFormatSelector(selector);

    assert.equal(selector.selectedFormat, "MD");
    assert.match(view.html, /data-artifact-download-format="MD"/);
    assert.match(view.html, /aria-pressed="true"/);
    assert.match(
      view.html,
      /data-artifact-download-route="\/api\/v1\/artifact-files\/file-md-0437\/download"/
    );
    assert.doesNotMatch(view.html, /contentBase64|storage_ref|database_url/);
  });

  it("keeps unavailable selectors explicit when no download routes exist", () => {
    const selector = buildArtifactDownloadFormatSelector({
      artifactRef: artifactRef({ downloadRoutes: {}, availableFormats: ["PDF"] })
    });
    const summary = buildArtifactDownloadFormatSelectorSummary(selector);

    assert.equal(selector.status, "UNAVAILABLE");
    assert.equal(selector.selectedFormat, null);
    assert.equal(summary.enabled_option_count, 0);
    assert.equal(summary.selected_route_present, false);
  });

  it("rejects invalid routes, schema, sensitive keys, and sensitive values", () => {
    assert.throws(
      () =>
        buildArtifactDownloadFormatSelector({
          artifactRef: artifactRef({
            downloadRoutes: { PDF: "/api/v1/artifact-files/file-pdf-0437/preview" }
          })
        }),
      /does not match/
    );
    assert.throws(() => buildArtifactDownloadFormatSelectorSummary({}), /invalid/);
    assert.deepEqual(
      findSensitiveArtifactDownloadFormatSelectorKeys({
        nested: { storage_ref: "hidden" }
      }),
      ["nested.storage_ref"]
    );
    assert.throws(
      () =>
        assertArtifactDownloadFormatSelectorSafe({
          route: "/data/nex-platform/ae/artifacts/file"
        }),
      /sensitive values/
    );
  });

  it("is wired into the artifact summary download action path", () => {
    assert.match(MAIN_SOURCE, /from "\.\/artifactDownloadFormatSelector\.js"/);
    assert.match(MAIN_SOURCE, /selectedArtifactDownloadFormat: "MD"/);
    assert.match(MAIN_SOURCE, /artifactSummary\.addEventListener\("click"/);
    assert.match(MAIN_SOURCE, /renderArtifactDownloadFormatSelector/);
    assert.match(MAIN_SOURCE, /submitArtifactDownloadAction\(downloadTarget\)/);
  });
});
