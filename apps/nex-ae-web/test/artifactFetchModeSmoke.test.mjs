import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_FETCH_MODE_SMOKE_SCHEMA_VERSION,
  assertArtifactFetchModeSmokeEvidenceRedacted,
  formatSummary,
  main,
  runArtifactFetchModeSmoke
} from "../scripts/runArtifactFetchModeSmoke.mjs";

describe("AE Web artifact fetch-mode smoke script", () => {
  it("emits deterministic same-origin artifact evidence without live network", async () => {
    const evidence = await runArtifactFetchModeSmoke();
    const serialized = JSON.stringify(evidence);

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_ARTIFACT_FETCH_MODE_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.mode, "deterministic_fake_fetch");
    assert.equal(evidence.runner.browser_api_path, "/ae-api");
    assert.equal(evidence.runtime.fetch_mode_allowed, true);
    assert.equal(evidence.artifact.summary.artifact_id, "artifact-slice-0417");
    assert.equal(evidence.artifact.version_panel.version_count, 1);
    assert.equal(evidence.artifact.preview_panel.status, "PREVIEW_READY");
    assert.equal(evidence.artifact.download_panel.status, "DOWNLOAD_READY");
    assert.equal(evidence.artifact.binary_download_panel.status, "DOWNLOAD_READY");
    assert.equal(evidence.artifact.binary_download_panel.download_payload_kind, "base64");
    assert.equal(evidence.artifact.binary_download_panel.content_encoding, "base64");
    assert.equal(evidence.request_observations.fetch_call_count, 8);
    assert.equal(evidence.checks.same_origin_route_sequence_matches, true);
    assert.equal(evidence.checks.no_authorization_header_in_browser_fetch, true);
    assert.equal(evidence.checks.download_panel_metadata_only, true);
    assert.equal(evidence.checks.export_submit_route_same_origin, true);
    assert.equal(evidence.checks.binary_download_surface_base64, true);
    assert.equal(evidence.checks.binary_download_panel_metadata_only, true);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_fetch_mode_smoke=pass " +
        "mode=deterministic_fake_fetch artifact=artifact-slice-0417 " +
        "versions=1 export_formats=2 fetch_calls=8"
    );
    assert.doesNotMatch(
      serialized,
      /private artifact body|JVBERi0xLjQKJQ==|storage_ref|ae:\/\/artifacts|service_token|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("rejects raw download and server-only material in evidence", () => {
    assert.throws(
      () =>
        assertArtifactFetchModeSmokeEvidenceRedacted(
          { raw: "private-body" },
          { rawDownloadContent: "private-body" }
        ),
      /raw download content/
    );
    assert.throws(
      () =>
        assertArtifactFetchModeSmokeEvidenceRedacted({
          raw: "database_url"
        }),
      /server material/
    );
    assert.throws(
      () =>
        assertArtifactFetchModeSmokeEvidenceRedacted(
          { raw: "JVBERi0xLjQKJQ==" },
          { rawBinaryDownloadContentBase64: "JVBERi0xLjQKJQ==" }
        ),
      /raw binary download content/
    );
  });

  it("supports JSON and summary CLI modes", async () => {
    const jsonLines = [];
    const summaryLines = [];

    assert.equal(await main([], line => jsonLines.push(line)), 0);
    assert.equal(await main(["--summary"], line => summaryLines.push(line)), 0);

    assert.equal(
      JSON.parse(jsonLines.at(0)).smoke_schema_version,
      AE_WEB_ARTIFACT_FETCH_MODE_SMOKE_SCHEMA_VERSION
    );
    assert.equal(
      summaryLines.at(0),
      "ae_web_artifact_fetch_mode_smoke=pass " +
        "mode=deterministic_fake_fetch artifact=artifact-slice-0417 " +
        "versions=1 export_formats=2 fetch_calls=8"
    );
  });

  it("returns a failure summary when the runner throws", async () => {
    const originalStringify = JSON.stringify;
    JSON.stringify = () => {
      throw new TypeError("forced stringify failure");
    };
    const lines = [];
    try {
      assert.equal(await main([], line => lines.push(line)), 1);
    } finally {
      JSON.stringify = originalStringify;
    }
    assert.equal(lines.at(0), "ae_web_artifact_fetch_mode_smoke=fail error=TypeError");
  });
});
