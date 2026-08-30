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
    const deliveryStateIndex = MAIN_SOURCE.indexOf(
      "buildArtifactDeliveryDownloadSuccess("
    );
    const summaryIndex = MAIN_SOURCE.indexOf("buildArtifactDownloadSaveSummary");

    assert.match(MAIN_SOURCE, /from "\.\/artifactDownloadSaveAdapter\.js"/);
    assert.match(MAIN_SOURCE, /from "\.\/artifactDeliveryActionState\.js"/);
    assert.ok(downloadFetchIndex > 0);
    assert.ok(deliveryStateIndex > downloadFetchIndex);
    assert.ok(summaryIndex > 0);
    assert.match(MAIN_SOURCE, /artifactDownloadSaveResult: null/);
    assert.match(MAIN_SOURCE, /applyArtifactDeliveryActionState/);
  });

  it("keeps main download wiring free of raw payload literals and server-only fields", () => {
    assert.doesNotMatch(
      MAIN_SOURCE,
      /contentBase64|content_base64|storage_ref|database_url|provider_url|service_token|\/data\/nex-platform/
    );
    assert.match(MAIN_SOURCE, /artifactDownloadSaveResult = null/);
  });
});
