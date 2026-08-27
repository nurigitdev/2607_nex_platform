import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
  buildRepairedResponseReviewSurfaceFromProjection
} from "../src/repairedResponseReviewClient.js";
import {
  AE_WEB_REPAIRED_RESPONSE_REVIEW_CARD_SCHEMA_VERSION,
  buildRepairedResponseReviewCardSummary,
  buildRepairedResponseReviewCardViewModel,
  renderRepairedResponseReviewCard
} from "../src/repairedResponseReviewCard.js";

function projection(overrides = {}) {
  return {
    projection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: "handoff-001",
    handoff_request_id: "request-001",
    owner_scope: {
      tenant_id: "tenant-local",
      workspace_id: "workspace-local",
      owner_user_id: "owner-local"
    },
    conversation_scope: {
      chat_document_id: "chat-doc-local",
      interaction_id: "interaction-001"
    },
    review_card: {
      title: "수정 응답 검토",
      presentation_mode: "side_by_side_review",
      default_action: "review_repair"
    },
    original_response_ref: {
      cx_generation_id: "cx-gen-parent-001",
      link: "/api/v1/generations/cx-gen-parent-001",
      parent_generation_mutated: false
    },
    repaired_response_summary: {
      cx_generation_id: "cx-gen-repair-001",
      status: "SUCCEEDED",
      alias: "default",
      provider_capability: "grounded_generation",
      finish_reason: "stop",
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
      remediation_action_id: "remediation-001",
      lineage_status: "REPAIRED",
      action_type: "regenerate_answer",
      lineage_type: "repair",
      attempt_no: 2,
      result_ref: { kind: "cx_generation", id: "cx-gen-repair-001" }
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
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/decisions",
      idempotency_key_hint: "request-001"
    },
    links: {
      handoff:
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001",
      original_generation: "/api/v1/generations/cx-gen-parent-001",
      repaired_generation: "/api/v1/generations/cx-gen-repair-001",
      remediation_execution:
        "/api/v1/generations/cx-gen-parent-001/remediation-executions/remediation-001"
    },
    redaction_summary: {
      raw_output_included: false,
      raw_prompt_included: false,
      raw_source_text_included: false,
      evidence_text_included: false,
      provider_detail_included: false,
      storage_path_included: false
    },
    checked_at: "2026-08-27T00:01:00Z",
    ...overrides
  };
}

function surface(overrides = {}) {
  return buildRepairedResponseReviewSurfaceFromProjection(projection(overrides));
}

describe("AE Web repaired response review card", () => {
  it("builds a view model with disabled decision buttons by default", () => {
    const viewModel = buildRepairedResponseReviewCardViewModel(surface());
    const summary = buildRepairedResponseReviewCardSummary(surface());

    assert.equal(
      viewModel.card_schema_version,
      AE_WEB_REPAIRED_RESPONSE_REVIEW_CARD_SCHEMA_VERSION
    );
    assert.equal(viewModel.primaryActions.length, 2);
    assert.equal(viewModel.primaryActions.every(action => action.disabled), true);
    assert.equal(viewModel.secondaryLinks.length, 3);
    assert.equal(viewModel.decisionState.status, "READY_FOR_DECISION");
    assert.equal(summary.enabled_action_count, 0);
    assert.equal(summary.metadata.rawPromptRendered, false);
  });

  it("renders safe escaped HTML for the chat review card", () => {
    const html = renderRepairedResponseReviewCard(
      surface({
        review_card: {
          ...projection().review_card,
          title: "<검토 & 확인>"
        },
        repaired_response_summary: {
          ...projection().repaired_response_summary,
          output_preview: "<script>alert('x')</script> 개선 응답"
        }
      })
    );

    assert.match(html, /data-repaired-response-review-card="handoff-001"/);
    assert.match(html, /&lt;검토 &amp; 확인&gt;/);
    assert.match(html, /&lt;script&gt;alert\(&#039;x&#039;\)&lt;\/script&gt;/);
    assert.doesNotMatch(
      html,
      /raw_prompt|raw_generation_output|source_text|service_token|database_url|provider_url|storage_path/i
    );
  });

  it("enables primary actions only when the decision flow is ready", () => {
    const ready = buildRepairedResponseReviewCardViewModel(surface(), {
      decisionEnabled: true
    });
    const submitting = buildRepairedResponseReviewCardViewModel(surface(), {
      decisionEnabled: true,
      decisionState: { status: "SUBMITTING", action: "accept_repair" }
    });
    const recorded = buildRepairedResponseReviewCardViewModel(surface(), {
      decisionEnabled: true,
      decisionState: {
        status: "RECORDED",
        action: "accept_repair",
        decisionId: "decision-001"
      }
    });
    const recordedHtml = renderRepairedResponseReviewCard(surface(), {
      decisionEnabled: true,
      decisionState: {
        status: "RECORDED",
        action: "accept_repair",
        decisionId: "decision-001"
      }
    });
    const failedHtml = renderRepairedResponseReviewCard(surface(), {
      decisionEnabled: true,
      decisionState: {
        status: "FAILED",
        action: "keep_original",
        errorStatus: "NETWORK_ERROR"
      }
    });

    assert.deepEqual(
      ready.primaryActions.map(action => action.disabled),
      [false, false]
    );
    assert.equal(submitting.primaryActions.every(action => action.disabled), true);
    assert.equal(recorded.primaryActions.every(action => action.disabled), true);
    assert.equal(recorded.primaryActions[0].selected, true);
    assert.match(recordedHtml, /RECORDED · decision-001/);
    assert.match(failedHtml, /FAILED · NETWORK_ERROR/);
  });

  it("handles missing optional links, unavailable actions, and empty previews", () => {
    const cardSurface = surface({
      repaired_response_summary: {
        ...projection().repaired_response_summary,
        output_preview: " "
      },
      decision_controls: {
        ...projection().decision_controls,
        available_actions: ["accept_repair"],
        secondary_actions: ["view_original", "view_lineage"]
      }
    });
    cardSurface.secondaryActions = ["view_original", "view_lineage", "unknown"];
    cardSurface.links.remediationExecution = "";
    const viewModel = buildRepairedResponseReviewCardViewModel(cardSurface, {
      decisionEnabled: true
    });
    const summary = buildRepairedResponseReviewCardSummary(cardSurface, {
      decisionEnabled: true
    });

    assert.equal(viewModel.repairedOutputPreview, "수정 응답 미리보기가 없습니다.");
    assert.deepEqual(
      viewModel.primaryActions.map(action => action.disabled),
      [false, true]
    );
    assert.deepEqual(
      viewModel.secondaryLinks.map(link => link.action),
      ["view_original"]
    );
    assert.equal(summary.secondary_link_count, 1);
  });

  it("rejects unsafe card view model payloads", () => {
    const cardSurface = surface();
    cardSurface.title = "raw_prompt should never render";

    assert.throws(
      () => buildRepairedResponseReviewCardViewModel(cardSurface),
      /unsafe payload fields/
    );
    assert.throws(
      () => buildRepairedResponseReviewCardViewModel({}),
      /surface is invalid/
    );
  });
});
