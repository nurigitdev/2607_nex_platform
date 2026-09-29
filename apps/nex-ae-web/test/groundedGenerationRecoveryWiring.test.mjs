import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const APP_DIR = join(TEST_DIR, "..");
const INDEX_SOURCE = readFileSync(join(APP_DIR, "index.html"), "utf8");
const MAIN_SOURCE = readFileSync(join(APP_DIR, "src", "main.js"), "utf8");
const STYLES_SOURCE = readFileSync(join(APP_DIR, "src", "styles.css"), "utf8");

describe("AE Web grounded generation recovery wiring", () => {
  it("exposes keyboard-reachable cancel, recovery, and retry controls", () => {
    for (const id of [
      "generation-cancel-button",
      "generation-recovery-button",
      "generation-retry-button",
      "generation-action-feedback"
    ]) {
      assert.match(INDEX_SOURCE, new RegExp(`id="${id}"`));
    }
    assert.match(INDEX_SOURCE, /aria-label="생성 작업 제어"/);
    assert.match(INDEX_SOURCE, /aria-live="polite"/);
  });

  it("wires server-backed lifecycle actions with polling cancellation guards", () => {
    for (const expected of [
      "from \"./groundedGenerationRecovery.js\"",
      "cancelGroundedGeneration({",
      "inspectGroundedGenerationRecovery({",
      "retryGroundedGeneration({",
      "generationAbortController",
      "generationRunSequence",
      "renderGenerationLifecycleControls()",
      "nextGenerationInteractionId()"
    ]) {
      assert.match(MAIN_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });

  it("keeps controls stable and responsive", () => {
    for (const expected of [
      ".generation-action-row",
      ".generation-action-row button",
      ".generation-action-row button:disabled",
      ".generation-action-row span"
    ]) {
      assert.match(STYLES_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });
});

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
