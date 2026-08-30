import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const MAIN_SOURCE = readFileSync(
  new URL("../src/main.js", import.meta.url),
  "utf-8"
);

describe("AE Web artifact download action wiring", () => {
  it("routes successful download actions through the browser save adapter", () => {
    const downloadFetchIndex = MAIN_SOURCE.indexOf("downloadArtifactFile(");
    const panelStateIndex = MAIN_SOURCE.indexOf(
      "buildArtifactPreviewPanelStateFromDownload(download, context)"
    );
    const saveIndex = MAIN_SOURCE.indexOf("saveArtifactDownload(download)");
    const summaryIndex = MAIN_SOURCE.indexOf("buildArtifactDownloadSaveSummary");

    assert.match(MAIN_SOURCE, /from "\.\/artifactDownloadSaveAdapter\.js"/);
    assert.ok(downloadFetchIndex > 0);
    assert.ok(panelStateIndex > downloadFetchIndex);
    assert.ok(saveIndex > panelStateIndex);
    assert.ok(summaryIndex > 0);
    assert.match(MAIN_SOURCE, /artifactDownloadSaveResult: null/);
    assert.match(MAIN_SOURCE, /resultStatus: downloadSaveSummary\?\.status \|\| "READY"/);
  });

  it("keeps main download wiring free of raw payload literals and server-only fields", () => {
    assert.doesNotMatch(
      MAIN_SOURCE,
      /contentBase64|content_base64|storage_ref|database_url|provider_url|service_token|\/data\/nex-platform/
    );
    assert.match(MAIN_SOURCE, /artifactDownloadSaveResult = null/);
  });
});
