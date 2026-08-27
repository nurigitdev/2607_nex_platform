import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
  buildRepairedResponseReviewSurfaceFromProjection
} from "../src/repairedResponseReviewClient.js";
import {
  AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION,
  RepairedResponseReviewReadModelError,
  buildRepairedResponseReviewReadModel,
  buildRepairedResponseReviewReadModelSummary,
  filterRepairedResponseReviewReadModel,
  findSensitiveRepairedResponseReviewReadModelKeys,
  validateRepairedResponseReviewReadModel
} from "../src/repairedResponseReviewReadModel.js";
import {
  createRepairedResponseDecisionState
} from "../src/repairedResponseDecisionState.js";

function projection(overrides = {}) {
  const handoffId = overrides.repaired_response_handoff_id || "handoff-001";
  const interactionId = overrides.interaction_id || "interaction-001";
  return {
    projection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: handoffId,
    handoff_request_id: `request-${handoffId}`,
    owner_scope: {
      tenant_id: "tenant-local",
      workspace_id: "workspace-local",
      owner_user_id: "owner-local"
    },
    conversation_scope: {
      chat_document_id: "chat-doc-local",
      interaction_id: interactionId
    },
    review_card: {
      title: "수정 응답 검토",
      presentation_mode: "side_by_side_review",
      default_action: "review_repair"
    },
    original_response_ref: {
      cx_generation_id: `cx-gen-parent-${handoffId}`,
      link: `/api/v1/generations/cx-gen-parent-${handoffId}`,
      parent_generation_mutated: false
    },
    repaired_response_summary: {
      cx_generation_id: `cx-gen-repair-${handoffId}`,
      status: "SUCCEEDED",
      output_hash: "a".repeat(64),
      output_preview: "근거 누락 지점을 보강했습니다.",
      usage: { input_tokens: 10, output_tokens: 12, total_tokens: 22 },
      quality_summary: {
        grounding_required: true,
        retrieval_package_id: "cx-ret-001",
        grounded_response_quality_status: "PASS"
      }
    },
    lineage_summary: {
      remediation_action_id: `remediation-${handoffId}`,
      lineage_status: "REPAIRED",
      action_type: "regenerate_answer",
      lineage_type: "repair",
      attempt_no: 2,
      result_ref: { kind: "cx_generation", id: `cx-gen-repair-${handoffId}` }
    },
    decision_controls: {
      available_actions: [
        "view_original",
        "view_repaired",
        "accept_repair",
        "keep_original",
        "view_lineage"
      ],
      primary_actions: ["accept_repair", "keep_original"],
      secondary_actions: ["view_original", "view_repaired", "view_lineage"],
      decision_submit_path:
        `/api/v1/chat/interactions/${interactionId}/repaired-response-handoffs/${handoffId}/decisions`
    },
    links: {
      handoff:
        `/api/v1/chat/interactions/${interactionId}/repaired-response-handoffs/${handoffId}`,
      original_generation: `/api/v1/generations/cx-gen-parent-${handoffId}`,
      repaired_generation: `/api/v1/generations/cx-gen-repair-${handoffId}`,
      remediation_execution:
        `/api/v1/generations/cx-gen-parent-${handoffId}/remediation-executions/remediation-${handoffId}`
    },
    redaction_summary: {
      raw_output_included: false,
      raw_prompt_included: false,
      raw_source_text_included: false,
      evidence_text_included: false,
      provider_detail_included: false,
      storage_path_included: false
    },
    checked_at: "2026-08-28T00:01:00Z",
    ...overrides
  };
}

function surface({ handoffId, decisionState } = {}) {
  return {
    ...buildRepairedResponseReviewSurfaceFromProjection(
      projection({ repaired_response_handoff_id: handoffId || "handoff-001" })
    ),
    decisionState
  };
}

describe("AE Web repaired response review read model", () => {
  it("builds a safe read model with decision status counters", () => {
    const model = buildRepairedResponseReviewReadModel(
      [
        surface({ handoffId: "handoff-ready" }),
        surface({
          handoffId: "handoff-recorded",
          decisionState: createRepairedResponseDecisionState({
            status: "RECORDED",
            action: "accept_repair",
            decisionId: "decision-001"
          })
        }),
        surface({
          handoffId: "handoff-failed",
          decisionState: createRepairedResponseDecisionState({
            status: "FAILED",
            action: "keep_original",
            errorStatus: "NETWORK_ERROR"
          })
        })
      ],
      { selectedHandoffId: "handoff-failed" }
    );
    const summary = buildRepairedResponseReviewReadModelSummary(model);

    assert.equal(
      model.read_model_schema_version,
      AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION
    );
    assert.equal(model.total_count, 3);
    assert.equal(model.actionable_count, 2);
    assert.equal(model.terminal_count, 1);
    assert.equal(model.failed_count, 1);
    assert.equal(model.selected_index, 2);
    assert.deepEqual(model.decision_status_counts, {
      FAILED: 1,
      READY_FOR_DECISION: 1,
      RECORDED: 1
    });
    assert.equal(summary.metadata.rawPromptRendered, false);
    assert.doesNotMatch(
      JSON.stringify(summary),
      /raw_prompt|raw_generation_output|source_text|service_token|database_url/
    );
  });

  it("filters actionable, ready, recorded, submitting, failed, and unknown modes", () => {
    const model = buildRepairedResponseReviewReadModel([
      surface({ handoffId: "handoff-ready" }),
      surface({
        handoffId: "handoff-submitting",
        decisionState: createRepairedResponseDecisionState({
          status: "SUBMITTING",
          action: "accept_repair"
        })
      }),
      surface({
        handoffId: "handoff-recorded",
        decisionState: createRepairedResponseDecisionState({
          status: "RECORDED",
          action: "accept_repair",
          decisionId: "decision-001"
        })
      }),
      surface({
        handoffId: "handoff-failed",
        decisionState: createRepairedResponseDecisionState({
          status: "FAILED",
          action: "keep_original"
        })
      })
    ]);

    assert.deepEqual(
      filterRepairedResponseReviewReadModel(model, "actionable").items.map(
        item => item.repaired_response_handoff_id
      ),
      ["handoff-ready", "handoff-failed"]
    );
    assert.equal(filterRepairedResponseReviewReadModel(model, "ready").filtered_count, 1);
    assert.equal(
      filterRepairedResponseReviewReadModel(model, "submitting").items[0]
        .repaired_response_handoff_id,
      "handoff-submitting"
    );
    assert.equal(filterRepairedResponseReviewReadModel(model, "recorded").filtered_count, 1);
    assert.equal(filterRepairedResponseReviewReadModel(model, "failed").filtered_count, 1);
    assert.equal(filterRepairedResponseReviewReadModel(model, "unknown").filter, "all");
  });

  it("accepts collection-like input and validates read models", () => {
    const model = buildRepairedResponseReviewReadModel({
      items: [surface({ handoffId: "handoff-collection" })]
    });

    assert.equal(validateRepairedResponseReviewReadModel(model), model);
    assert.equal(model.items[0].client_mode, "mock");
  });

  it("rejects invalid shapes and sensitive read model keys", () => {
    assert.throws(
      () => buildRepairedResponseReviewReadModel({ items: "bad" }),
      error =>
        error instanceof RepairedResponseReviewReadModelError &&
        error.status === "READ_MODEL_ITEMS_INVALID"
    );
    assert.throws(
      () => validateRepairedResponseReviewReadModel({}),
      error =>
        error instanceof RepairedResponseReviewReadModelError &&
        error.status === "READ_MODEL_INVALID"
    );
    assert.deepEqual(
      findSensitiveRepairedResponseReviewReadModelKeys({
        metadata: { rawPromptRendered: false },
        nested: { database_url: "postgresql://hidden" }
      }),
      ["nested.database_url"]
    );
    assert.throws(
      () =>
        validateRepairedResponseReviewReadModel({
          read_model_schema_version:
            AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION,
          items: [],
          database_url: "postgresql://hidden"
        }),
      error =>
        error instanceof RepairedResponseReviewReadModelError &&
        error.status === "READ_MODEL_SENSITIVE_KEY"
    );
  });
});
