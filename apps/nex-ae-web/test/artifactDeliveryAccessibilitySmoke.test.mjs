import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_DELIVERY_ACCESSIBILITY_SMOKE_SCHEMA_VERSION,
  assertArtifactDeliveryAccessibilitySmokeRedacted,
  formatSummary,
  main,
  runArtifactDeliveryAccessibilitySmoke
} from "../scripts/runArtifactDeliveryAccessibilitySmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);
const QUALITY_GATE = readFileSync(
  new URL("../../../scripts/quality/run_quality_gate.sh", import.meta.url),
  "utf-8"
);

describe("AE Web artifact delivery accessibility smoke", () => {
  it("passes with keyboard-reachable delivery controls and safe evidence", () => {
    const evidence = runArtifactDeliveryAccessibilitySmoke();
    const serialized = JSON.stringify(evidence);

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_ARTIFACT_DELIVERY_ACCESSIBILITY_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.live_network_used, false);
    assert.equal(evidence.runner.postgresql_used, false);
    assert.equal(evidence.checks.preview_anchor_keyboard_reachable, true);
    assert.equal(evidence.checks.download_anchor_keyboard_reachable, true);
    assert.equal(evidence.checks.selector_selected_state_visible, true);
    assert.equal(evidence.checks.selector_disabled_state_visible, true);
    assert.equal(evidence.observations.download_route_count, 4);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_delivery_accessibility_smoke=pass " +
        "routes=4 selected=1 disabled=1"
    );
    assert.doesNotMatch(
      serialized,
      /contentBase64|storage_ref|database_url|provider_url|service_token|\/data\/nex-platform/
    );
  });

  it("reports failed checks without requiring network or PostgreSQL", () => {
    const evidence = runArtifactDeliveryAccessibilitySmoke({
      stylesSource: "",
      qualityGateSource: ""
    });

    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.checks.focus_visible_style_present, false);
    assert.equal(evidence.checks.browser_click_path_shared, false);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_delivery_accessibility_smoke=fail reason=checks_failed"
    );
  });

  it("guards redaction, package script, quality gate, and CLI modes", async () => {
    const jsonLines = [];
    const summaryLines = [];

    assert.throws(
      () =>
        assertArtifactDeliveryAccessibilitySmokeRedacted({
          leak: "/data/nex-platform"
        }),
      /server material/
    );
    assert.equal(
      PACKAGE.scripts["smoke:artifact-delivery-accessibility"],
      "node scripts/runArtifactDeliveryAccessibilitySmoke.mjs --summary"
    );
    assert.match(QUALITY_GATE, /runArtifactDeliveryAccessibilitySmoke\.mjs --summary/);
    assert.equal(await main([], line => jsonLines.push(line)), 0);
    assert.equal(await main(["--summary"], line => summaryLines.push(line)), 0);
    assert.equal(
      JSON.parse(jsonLines.at(0)).smoke_schema_version,
      AE_WEB_ARTIFACT_DELIVERY_ACCESSIBILITY_SMOKE_SCHEMA_VERSION
    );
    assert.match(summaryLines.at(0), /ae_web_artifact_delivery_accessibility_smoke=pass/);
  });

  it("returns a safe failure summary when execution raises", async () => {
    const originalStringify = JSON.stringify;
    const lines = [];
    JSON.stringify = () => {
      throw new TypeError("forced stringify failure");
    };
    try {
      assert.equal(await main([], line => lines.push(line)), 1);
    } finally {
      JSON.stringify = originalStringify;
    }
    assert.equal(
      lines.at(0),
      "ae_web_artifact_delivery_accessibility_smoke=fail error=TypeError"
    );
  });
});
