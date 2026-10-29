import test from "node:test";
import assert from "node:assert/strict";

import {
  CANONICAL_PLATFORM_GOLDEN_JOURNEY_SCHEMA_VERSION,
  canonicalGoldenJourneyEnvironment
} from "../scripts/runCanonicalPlatformGoldenJourney.mjs";


test("canonical golden journey translates only at the legacy harness boundary", () => {
  const translated = canonicalGoldenJourneyEnvironment({
    NEX_CANONICAL_PLATFORM_GOLDEN_WEB_URL: "https://ae.example.test",
    NEX_CANONICAL_PLATFORM_GOLDEN_TENANT_ID: "VO00",
    NEX_CANONICAL_PLATFORM_GOLDEN_REQUESTER_PASSWORD: "private-requester",
    NEX_CANONICAL_PLATFORM_GOLDEN_SCREENSHOT_DIR: "/tmp/screens",
    NEX_P8_DEMO_S11_TENANT_ID: "legacy-wins"
  });

  assert.equal(
    CANONICAL_PLATFORM_GOLDEN_JOURNEY_SCHEMA_VERSION,
    "canonical_platform_golden_journey_playwright.v1"
  );
  assert.equal(translated.NEX_P8_DEMO_S11_WEB_URL, "https://ae.example.test");
  assert.equal(translated.NEX_P8_DEMO_S11_TENANT_ID, "legacy-wins");
  assert.equal(translated.NEX_P8_DEMO_S11_REQUESTER_PASSWORD, "private-requester");
  assert.equal(translated.NEX_P8_DEMO_S11_SCREENSHOT_DIR, "/tmp/screens");
});
