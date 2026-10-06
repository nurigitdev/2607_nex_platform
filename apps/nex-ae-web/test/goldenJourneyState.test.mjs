import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  GOLDEN_JOURNEY_STAGES,
  advanceGoldenJourney,
  assertBrowserSafeEvidence,
  buildGoldenJourneyEvidence,
  createGoldenJourneyState,
  failGoldenJourney
} from "../src/goldenJourneyState.js";

const START = "2026-10-06T00:00:00.000Z";

describe("AE Web correlated golden journey state", () => {
  it("advances all nine stages under one opaque journey id", () => {
    let state = createGoldenJourneyState({
      journeyId: "journey-001",
      startedAt: START
    });
    GOLDEN_JOURNEY_STAGES.forEach((stage, index) => {
      state = advanceGoldenJourney(state, {
        stage,
        occurredAt: `2026-10-06T00:00:${String(index + 1).padStart(2, "0")}.000Z`,
        refs: refsForStage(stage, index),
        details: detailsForStage(stage)
      });
    });

    assert.equal(state.status, "COMPLETED");
    assert.equal(state.current_stage, "DOWNLOAD_READY");
    assert.deepEqual(state.completed_stages, GOLDEN_JOURNEY_STAGES);
    assert.equal(state.events.length, 9);
    assert.ok(Object.isFrozen(state));

    const evidence = buildGoldenJourneyEvidence(state);
    assert.equal(evidence.status, "COMPLETED");
    assert.equal(evidence.completed_stage_count, 9);
    assert.equal(evidence.expected_stage_count, 9);
    assert.equal(evidence.redaction.private_payload_included, false);
    assert.equal(JSON.stringify(evidence).includes("private document"), false);
  });

  it("rejects skipped stages and terminal-state mutation", () => {
    const ready = createGoldenJourneyState({ journeyId: "journey-002", startedAt: START });
    assert.throws(
      () =>
        advanceGoldenJourney(ready, {
          stage: "UPLOAD_ACCEPTED",
          occurredAt: "2026-10-06T00:00:01Z"
        }),
      /expected SESSION_AUTHENTICATED/
    );

    const failed = failGoldenJourney(ready, {
      failureCode: "AUTH_DENIED",
      occurredAt: "2026-10-06T00:00:01Z",
      retryable: false
    });
    assert.equal(failed.status, "FAILED");
    assert.equal(failed.failure.failed_stage, "SESSION_AUTHENTICATED");
    assert.throws(
      () =>
        advanceGoldenJourney(failed, {
          stage: "SESSION_AUTHENTICATED",
          occurredAt: "2026-10-06T00:00:02Z"
        }),
      /terminal/
    );
    assert.throws(
      () =>
        failGoldenJourney(failed, {
          failureCode: "AUTH_DENIED",
          occurredAt: "2026-10-06T00:00:02Z"
        }),
      /terminal/
    );
  });

  it("fails closed for unsafe refs, details, codes, timestamps, and locale", () => {
    assert.throws(
      () => createGoldenJourneyState({ journeyId: "/private/path", startedAt: START }),
      /opaque identifier/
    );
    assert.throws(
      () => createGoldenJourneyState({ journeyId: "journey", startedAt: "bad" }),
      /started_at/
    );
    assert.throws(
      () => createGoldenJourneyState({ journeyId: "journey", startedAt: START, locale: "ja" }),
      /locale/
    );
    const state = createGoldenJourneyState({ journeyId: "journey-003", startedAt: START });
    for (const payload of [
      { refs: { raw_prompt: "private" }, details: {} },
      { refs: { subject_ref: "/data/private" }, details: {} },
      { refs: [], details: {} },
      { refs: {}, details: { raw_output: "private" } },
      { refs: {}, details: { warning_count: -1 } },
      { refs: {}, details: { quality_status: "UNKNOWN" } },
      { refs: {}, details: [] }
    ]) {
      assert.throws(() =>
        advanceGoldenJourney(state, {
          stage: "SESSION_AUTHENTICATED",
          occurredAt: "2026-10-06T00:00:01Z",
          ...payload
        })
      );
    }
    assert.throws(
      () =>
        advanceGoldenJourney(state, {
          stage: "SESSION_AUTHENTICATED",
          occurredAt: "2026-10-05T23:59:59Z"
        }),
      /backwards/
    );
    assert.throws(
      () => failGoldenJourney(state, { failureCode: "private error", occurredAt: START }),
      /failure code/
    );
    assert.throws(
      () => failGoldenJourney(state, { failureCode: "FAILED", occurredAt: START, retryable: "yes" }),
      /retryable/
    );
  });

  it("rejects malformed state and private browser evidence", () => {
    assert.throws(() => buildGoldenJourneyEvidence({}), /state schema/);
    assert.throws(
      () =>
        buildGoldenJourneyEvidence({
          journey_schema_version: "ae_web_golden_journey.v1",
          completed_stages: null,
          events: null
        }),
      /collections/
    );
    assert.throws(() => assertBrowserSafeEvidence({}), /evidence schema/);
    assert.throws(
      () =>
        assertBrowserSafeEvidence({
          evidence_schema_version: "ae_web_golden_journey_evidence.v1",
          raw_prompt: "private"
        }),
      /private material/
    );
  });
});

function refsForStage(stage, index) {
  const keys = [
    "subject_ref",
    "source_file_id",
    "processing_run_id",
    "retrieval_id",
    "generation_id",
    "response_id",
    "artifact_id",
    "artifact_file_id",
    "artifact_file_id"
  ];
  return { [keys[index]]: `${stage.toLowerCase()}-${index + 1}` };
}

function detailsForStage(stage) {
  if (stage === "RETRIEVAL_READY") return { warning_count: 0 };
  if (stage === "GROUNDING_ACCEPTED") {
    return { citation_count: 3, repair_attempt_count: 0, quality_status: "VALIDATED" };
  }
  if (stage === "DOWNLOAD_READY") return { download_format: "MD" };
  return {};
}
