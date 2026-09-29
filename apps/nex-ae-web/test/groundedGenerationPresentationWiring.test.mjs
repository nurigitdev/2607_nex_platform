import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const MAIN_SOURCE = readFileSync(
  join(TEST_DIR, "..", "src", "main.js"),
  "utf8"
);

describe("AE Web verified grounded response wiring", () => {
  it("uses the generation presentation coordinator for submit and retry", () => {
    for (const expected of [
      "from \"./groundedGenerationPresentation.js\"",
      "buildGroundedGenerationPresentation({",
      "buildGroundedGenerationPresentationFailure(",
      "generationPresentation.assistantText",
      "generationPresentation.artifactHandoffAllowed",
      "generationPresentation.repairedResponseReview",
      "presentation.repairedResponseReview"
    ]) {
      assert.match(MAIN_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });

  it("does not issue a duplicate standalone retrieval in prompt submission", () => {
    const start = MAIN_SOURCE.indexOf("async function appendPromptInteraction()");
    const end = MAIN_SOURCE.indexOf("async function cancelActiveGeneration()", start);
    const source = MAIN_SOURCE.slice(start, end);

    assert.ok(start >= 0 && end > start);
    assert.doesNotMatch(source, /await submitRetrievalRequest\(retrievalRequest\)/);
    assert.match(source, /generationPresentation\.retrievalResult/);
    assert.match(source, /GENERATION_RETRIEVAL_PROJECTION_REQUIRED/);
  });
});

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
