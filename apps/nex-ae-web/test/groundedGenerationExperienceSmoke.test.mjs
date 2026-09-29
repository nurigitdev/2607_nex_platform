import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_GROUNDED_GENERATION_EXPERIENCE_SMOKE_SCHEMA_VERSION,
  assertGroundedGenerationExperienceSmokeRedacted,
  formatSummary,
  main,
  runGroundedGenerationExperienceSmoke
} from "../scripts/runGroundedGenerationExperienceSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);
const QUALITY_GATE = readFileSync(
  new URL("../../../scripts/quality/run_quality_gate.sh", import.meta.url),
  "utf-8"
);

describe("AE Web grounded generation experience smoke", () => {
  it("passes accessible controls, race guards, diagnostics, and quality gates", () => {
    const evidence = runGroundedGenerationExperienceSmoke();

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_GROUNDED_GENERATION_EXPERIENCE_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.observations.control_count, 3);
    assert.equal(evidence.observations.disabled_control_count, 3);
    assert.equal(evidence.runner.live_network_used, false);
    assert.equal(evidence.runner.postgresql_used, false);
    assert.equal(
      formatSummary(evidence),
      "ae_web_grounded_generation_experience_smoke=pass controls=3 " +
        "disabled=3 checks=13"
    );
  });

  it("reports incomplete accessibility and gate wiring without live services", () => {
    const evidence = runGroundedGenerationExperienceSmoke({
      indexSource: "",
      mainSource: "",
      stylesSource: "",
      packageSource: "{}",
      qualityGateSource: ""
    });

    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.checks.controls_keyboard_reachable, false);
    assert.equal(evidence.checks.full_gate_runs_node_regression, false);
    assert.equal(
      formatSummary(evidence),
      "ae_web_grounded_generation_experience_smoke=fail reason=checks_failed"
    );
  });

  it("guards redaction, package registration, quality gate, and CLI output", async () => {
    const jsonLines = [];
    const summaryLines = [];

    assert.throws(
      () =>
        assertGroundedGenerationExperienceSmokeRedacted({
          leak: "/data/nex-platform"
        }),
      /server material/
    );
    assert.equal(
      PACKAGE.scripts["smoke:grounded-generation-experience"],
      "node scripts/runGroundedGenerationExperienceSmoke.mjs --summary"
    );
    assert.match(QUALITY_GATE, /npm test --prefix apps\/nex-ae-web/);
    assert.match(
      QUALITY_GATE,
      /runGroundedGenerationExperienceSmoke\.mjs --summary/
    );
    assert.equal(await main([], line => jsonLines.push(line)), 0);
    assert.equal(await main(["--summary"], line => summaryLines.push(line)), 0);
    assert.equal(
      JSON.parse(jsonLines.at(0)).smoke_schema_version,
      AE_WEB_GROUNDED_GENERATION_EXPERIENCE_SMOKE_SCHEMA_VERSION
    );
    assert.match(
      summaryLines.at(0),
      /ae_web_grounded_generation_experience_smoke=pass/
    );
  });

  it("returns a safe failure summary when evidence serialization fails", async () => {
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
      "ae_web_grounded_generation_experience_smoke=fail error=TypeError"
    );
  });
});
