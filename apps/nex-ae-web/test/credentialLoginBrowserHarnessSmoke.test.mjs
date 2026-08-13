import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION,
  assertBrowserHarnessSmokeEvidenceRedacted,
  formatSummary,
  main,
  runCredentialLoginBrowserHarnessSmoke
} from "../scripts/runCredentialLoginBrowserHarnessSmoke.mjs";

describe("AE Web credential login browser harness smoke script", () => {
  it("emits deterministic fake-fetch smoke evidence without live network", async () => {
    const evidence = await runCredentialLoginBrowserHarnessSmoke();

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.mode, "deterministic_fake_fetch");
    assert.equal(evidence.runner.live_network_used, false);
    assert.equal(evidence.runner.postgresql_used, false);
    assert.equal(evidence.harness.summary.route_guard_status, "allowed");
    assert.equal(evidence.harness.summary.fetch_call_count, 3);
    assert.deepEqual(evidence.checks, {
      current_session_anonymous: true,
      authenticated_session_active: true,
      runtime_fetch_ready: true,
      route_guard_allowed: true,
      logout_returns_anonymous: true,
      fetch_call_sequence_matches_auth_routes: true,
      login_body_redacted: true,
      live_network_not_used: true
    });
    assert.equal(
      formatSummary(evidence),
      "ae_web_credential_login_browser_harness_smoke=pass " +
        "mode=deterministic_fake_fetch route_guard=allowed fetch_calls=3"
    );
    assert.doesNotMatch(
      JSON.stringify(evidence),
      /slice-0263-login-secret|password_hash|access_token|service_token|provider_url|\/data\/nex-platform/
    );
  });

  it("rejects smoke evidence with raw credential or server-only material", () => {
    assert.throws(
      () =>
        assertBrowserHarnessSmokeEvidenceRedacted(
          {
            smoke_schema_version:
              AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION,
            raw: "slice-0263-login-secret"
          },
          { rawPassword: "slice-0263-login-secret" }
        ),
      /raw password/
    );
    assert.throws(
      () =>
        assertBrowserHarnessSmokeEvidenceRedacted({
          smoke_schema_version:
            AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION,
          raw: "service_token"
        }),
      /server material/
    );
  });

  it("supports JSON and summary CLI modes", async () => {
    const jsonLines = [];
    const summaryLines = [];

    assert.equal(await main([], line => jsonLines.push(line)), 0);
    assert.equal(await main(["--summary"], line => summaryLines.push(line)), 0);

    assert.equal(
      JSON.parse(jsonLines.at(0)).smoke_schema_version,
      AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION
    );
    assert.equal(
      summaryLines.at(0),
      "ae_web_credential_login_browser_harness_smoke=pass " +
        "mode=deterministic_fake_fetch route_guard=allowed fetch_calls=3"
    );
  });
});
