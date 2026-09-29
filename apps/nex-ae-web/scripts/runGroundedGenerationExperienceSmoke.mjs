#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const AE_WEB_GROUNDED_GENERATION_EXPERIENCE_SMOKE_SCHEMA_VERSION =
  "ae_web_grounded_generation_experience_smoke.v1";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const APP_DIR = resolve(SCRIPT_DIR, "..");
const ROOT_DIR = resolve(APP_DIR, "../..");
const CONTROL_IDS = [
  "generation-cancel-button",
  "generation-recovery-button",
  "generation-retry-button"
];
const FORBIDDEN_FRAGMENTS = [
  "raw_" + "prompt",
  "source_" + "text",
  "service_" + "token",
  "provider_" + "url",
  "database_" + "url",
  "storage_" + "ref",
  "/data/" + "nex-platform",
  ["ed6", "@", "c496em"].join(""),
  ["nuri", "1004"].join("")
];

export function runGroundedGenerationExperienceSmoke({
  indexSource = readFileSync(resolve(APP_DIR, "index.html"), "utf-8"),
  mainSource = readFileSync(resolve(APP_DIR, "src/main.js"), "utf-8"),
  stylesSource = readFileSync(resolve(APP_DIR, "src/styles.css"), "utf-8"),
  packageSource = readFileSync(resolve(APP_DIR, "package.json"), "utf-8"),
  qualityGateSource = readFileSync(
    resolve(ROOT_DIR, "scripts/quality/run_quality_gate.sh"),
    "utf-8"
  )
} = {}) {
  const disabledControlCount = CONTROL_IDS.filter(id =>
    new RegExp(`<button[^>]*id="${id}"[^>]*disabled`).test(indexSource)
  ).length;
  const checks = {
    command_region_labelled: indexSource.includes(
      'aria-label="생성 작업 제어"'
    ),
    controls_keyboard_reachable: CONTROL_IDS.every(id =>
      new RegExp(`<button[^>]*id="${id}"[^>]*type="button"`).test(indexSource)
    ),
    controls_fail_closed_initially: disabledControlCount === CONTROL_IDS.length,
    status_announced: /id="generation-action-feedback"[^>]*role="status"[^>]*aria-live="polite"/.test(
      indexSource
    ),
    lifecycle_actions_wired: [
      "cancelActiveGeneration()",
      "inspectGenerationRecovery()",
      "retryLastGeneration()"
    ].every(token => mainSource.includes(token)),
    stale_polling_guarded:
      mainSource.includes("generationAbortController") &&
      mainSource.includes("generationRunSequence"),
    verified_presentation_required:
      mainSource.includes("buildGroundedGenerationPresentation({") &&
      mainSource.includes("generationPresentation.artifactHandoffAllowed"),
    diagnostics_metadata_only:
      mainSource.includes("summary.generation_display_mode") &&
      mainSource.includes("summary.generation_next_action"),
    focus_visible_style_present: stylesSource.includes(":focus-visible"),
    responsive_control_layout:
      stylesSource.includes(".generation-action-row") &&
      stylesSource.includes("flex-wrap: wrap"),
    package_smoke_registered: packageSource.includes(
      '"smoke:grounded-generation-experience"'
    ),
    full_gate_runs_node_regression: qualityGateSource.includes(
      "npm test --prefix apps/nex-ae-web"
    ),
    full_gate_runs_experience_smoke: qualityGateSource.includes(
      "runGroundedGenerationExperienceSmoke.mjs --summary"
    )
  };
  const evidence = {
    smoke_schema_version:
      AE_WEB_GROUNDED_GENERATION_EXPERIENCE_SMOKE_SCHEMA_VERSION,
    status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
    runner: {
      mode: "deterministic_static_contract",
      live_network_used: false,
      postgresql_used: false,
      browser_process_used: false
    },
    observations: {
      control_count: CONTROL_IDS.length,
      disabled_control_count: disabledControlCount,
      check_count: Object.keys(checks).length
    },
    checks,
    redaction: {
      generated_content_included: false,
      prompt_content_included: false,
      server_material_included: false
    }
  };
  assertGroundedGenerationExperienceSmokeRedacted(evidence);
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_grounded_generation_experience_smoke=pass " +
      `controls=${evidence.observations.control_count} ` +
      `disabled=${evidence.observations.disabled_control_count} ` +
      `checks=${evidence.observations.check_count}`
    );
  }
  return "ae_web_grounded_generation_experience_smoke=fail reason=checks_failed";
}

export function assertGroundedGenerationExperienceSmokeRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("Grounded generation experience smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = runGroundedGenerationExperienceSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_grounded_generation_experience_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exitCode = await main();
}
