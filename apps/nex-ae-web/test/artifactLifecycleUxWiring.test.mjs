import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const APP_DIR = join(TEST_DIR, "..");
const MAIN_SOURCE = readFileSync(join(APP_DIR, "src", "main.js"), "utf8");
const STYLES_SOURCE = readFileSync(join(APP_DIR, "src", "styles.css"), "utf8");

describe("AE Web artifact lifecycle UX wiring", () => {
  it("wires selected artifact lifecycle controls through the artifact client", () => {
    for (const expected of [
      "from \"./artifactLifecycleActionState.js\"",
      "artifactLifecycleActionRoute",
      "artifactLifecycleActionState: null",
      "resetArtifactLifecycleActionState();",
      "workspaceState.operations.artifactLifecycle",
      "data-artifact-lifecycle-action",
      "data-artifact-lifecycle-route",
      "data-artifact-lifecycle-artifact-id",
      "data-artifact-lifecycle-artifact-status",
      "data-artifact-lifecycle-target-status",
      "data-artifact-lifecycle-restore-status",
      "submitArtifactLifecycleAction(lifecycleTarget)",
      "workspaceState.artifactClient.submitArtifactLifecycleAction",
      "buildArtifactLifecycleIdempotencyKey(context)",
      "artifactRefFromLifecycleSurface"
    ]) {
      assert.match(MAIN_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });

  it("keeps lifecycle state transitions visible without raw payload details", () => {
    for (const expected of [
      "buildArtifactLifecycleActionSet(",
      "buildArtifactLifecycleActionSetSummary(",
      "buildArtifactLifecycleActionStateSummary(",
      "buildArtifactLifecycleActionRunningState(",
      "buildArtifactLifecycleActionSuccessState(",
      "buildArtifactLifecycleActionFailureState(",
      "createArtifactLifecycleActionContext(",
      "class=\"inline-meta slim artifact-lifecycle-summary\"",
      "data-artifact-lifecycle-state",
      "data-artifact-lifecycle-action-count"
    ]) {
      assert.match(MAIN_SOURCE, new RegExp(escapeRegExp(expected)));
    }

    for (const forbidden of [
      "raw_comment",
      "comment_body",
      "comment_text",
      "source_text",
      "service_token",
      "api_key",
      "database_url",
      "provider_url",
      "storage_ref",
      "storage_path",
      "/data/nex-platform",
      "nuri1004"
    ]) {
      assert.doesNotMatch(MAIN_SOURCE, new RegExp(escapeRegExp(forbidden)));
    }
  });

  it("adds compact lifecycle action styling beside existing artifact controls", () => {
    for (const expected of [
      ".artifact-lifecycle-summary",
      ".artifact-lifecycle-actions",
      ".artifact-lifecycle-actions button",
      ".artifact-lifecycle-actions button:not(:disabled):hover",
      ".artifact-lifecycle-actions button:disabled"
    ]) {
      assert.match(STYLES_SOURCE, new RegExp(escapeRegExp(expected)));
    }
  });
});

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
