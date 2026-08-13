import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTHENTICATED_UPLOAD_FETCH_SMOKE_SCHEMA_VERSION,
  assertAuthenticatedUploadFetchSmokeEvidenceRedacted,
  formatSummary,
  main,
  runAuthenticatedUploadFetchSmoke
} from "../scripts/runAuthenticatedUploadFetchSmoke.mjs";

describe("AE Web authenticated upload fetch smoke script", () => {
  it("emits deterministic same-origin upload evidence without live network", async () => {
    const evidence = await runAuthenticatedUploadFetchSmoke();
    const serialized = JSON.stringify(evidence);

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_AUTHENTICATED_UPLOAD_FETCH_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.mode, "deterministic_fake_fetch");
    assert.equal(evidence.runner.browser_api_path, "/ae-api");
    assert.equal(evidence.workflow.summary.checks_passed, true);
    assert.equal(evidence.request_observations.upload_body_summary.owner_user_id, "user-slice-0273");
    assert.equal(evidence.checks.same_origin_sequence_matches, true);
    assert.equal(evidence.checks.upload_body_metadata_only, true);
    assert.equal(
      formatSummary(evidence),
      "ae_web_authenticated_upload_fetch_smoke=pass " +
        "mode=deterministic_fake_fetch route=/api/v1/uploads status=QUEUED fetch_calls=4"
    );
    assert.doesNotMatch(
      serialized,
      /slice-0273-upload-secret|content_text|content_base64|service_token|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("rejects raw secret and server-only material in evidence", () => {
    assert.throws(
      () =>
        assertAuthenticatedUploadFetchSmokeEvidenceRedacted(
          { raw: "slice-0273-upload-secret" },
          { rawPassword: "slice-0273-upload-secret" }
        ),
      /raw password/
    );
    assert.throws(
      () =>
        assertAuthenticatedUploadFetchSmokeEvidenceRedacted({
          raw: "content_base64"
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
      AE_WEB_AUTHENTICATED_UPLOAD_FETCH_SMOKE_SCHEMA_VERSION
    );
    assert.equal(
      summaryLines.at(0),
      "ae_web_authenticated_upload_fetch_smoke=pass " +
        "mode=deterministic_fake_fetch route=/api/v1/uploads status=QUEUED fetch_calls=4"
    );
  });
});
