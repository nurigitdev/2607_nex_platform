import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildDefaultMockApprovalInbox,
  createMockApprovalClient,
  normalizeApprovalInbox
} from "../src/approvalClient.js";
import {
  AE_WEB_APPROVAL_UI_SCHEMA_VERSION,
  buildApprovalUiSummary,
  createApprovalUiController,
  renderApprovalUi
} from "../src/approvalUi.js";

function readyState(overrides = {}) {
  return {
    phase: "READY",
    clientMode: "mock",
    inbox: normalizeApprovalInbox(buildDefaultMockApprovalInbox()),
    selectedGateId: null,
    detail: null,
    decision: null,
    errorStatus: null,
    feedback: null,
    ...overrides
  };
}

describe("AE Web approval UI read model", () => {
  it("preserves three approval domains and safe actionable counts", () => {
    const state = readyState();
    const summary = buildApprovalUiSummary(state, {
      now: new Date("2026-10-22T09:00:00Z")
    });
    const html = renderApprovalUi(state, {
      now: new Date("2026-10-22T09:00:00Z")
    });

    assert.equal(summary.ui_schema_version, AE_WEB_APPROVAL_UI_SCHEMA_VERSION);
    assert.equal(summary.gate_count, 4);
    assert.equal(summary.actionable_count, 3);
    assert.equal(summary.expired_count, 1);
    assert.equal(summary.formal_projection_count, 1);
    assert.deepEqual(summary.domain_counts, {
      NSL_WRITE: 2,
      AGENT_FORMAL: 1,
      BUSINESS_FORMAL: 1
    });
    assert.match(html, /data-approval-domain="NSL_WRITE"/);
    assert.match(html, /data-approval-domain="AGENT_FORMAL"/);
    assert.match(html, /data-approval-domain="BUSINESS_FORMAL"/);
    assert.match(html, /1 \/ 2 단계 · TEAM_LEAD/);
    assert.match(html, /증빙 2개/);
    assert.match(html, /만료/);
    assert.doesNotMatch(
      html,
      /protected_request|semantic_hash|resume_target_ref|service_token|source_ref/
    );
  });

  it("renders business formal progress and keeps terminal state aligned", async () => {
    const container = {
      innerHTML: "",
      addEventListener() {},
      querySelector() {
        return { value: "P8-S74 formal approval" };
      }
    };
    const controller = createApprovalUiController({
      container,
      client: createMockApprovalClient(),
      now: () => new Date("2026-10-22T09:00:00Z")
    });

    await controller.refresh();
    await controller.selectGate("42000000-0000-4000-8000-000000000003");

    assert.match(container.innerHTML, /data-business-formal="true"/);
    assert.match(container.innerHTML, /data-formal-current-stage="1"/);
    assert.match(container.innerHTML, /data-formal-stage-count="2"/);
    assert.match(container.innerHTML, /data-formal-requested-role="TEAM_LEAD"/);
    assert.match(container.innerHTML, /EOS 대상/);
    assert.match(container.innerHTML, /eos-stage-p8-s42/);
    assert.match(container.innerHTML, /data-approval-attachment-manifest="true"/);
    assert.match(container.innerHTML, /교통비-영수증.png/);
    assert.match(container.innerHTML, /다운로드/);
    assert.doesNotMatch(container.innerHTML, /object_ref|bucket|rustfs|storage_path/i);

    await controller.submitDecision("APPROVE");

    assert.equal(controller.snapshot().phase, "DECIDED");
    assert.equal(
      controller.snapshot().detail.gate.formal_approval.terminal_state,
      "APPROVED"
    );
    assert.match(container.innerHTML, /data-formal-terminal-state="APPROVED"/);
    assert.match(container.innerHTML, /data-approval-decision="APPROVE" disabled/);
  });

  it("renders safe detail, decision controls, terminal and denied states", () => {
    const inbox = normalizeApprovalInbox(buildDefaultMockApprovalInbox());
    const detail = {
      schema_version: "wc_approval_gate_detail.v1",
      gate: inbox.gates[0],
      created_at: "2026-10-22T08:00:00Z",
      version: 1,
      decision_options: ["APPROVE", "REJECT"]
    };
    const detailHtml = renderApprovalUi(
      readyState({
        phase: "DETAIL_READY",
        selectedGateId: detail.gate.gate_id,
        detail
      })
    );
    const decidedHtml = renderApprovalUi(
      readyState({
        phase: "DECIDED",
        selectedGateId: detail.gate.gate_id,
        detail: { ...detail, gate: { ...detail.gate, state: "APPROVED" } },
        decision: {
          decision: "APPROVE",
          decision_id: "42100000-0000-4000-8000-000000000001"
        },
        feedback: "승인이 안전하게 기록되었습니다."
      })
    );
    const deniedHtml = renderApprovalUi(
      readyState({
        phase: "UNAUTHORIZED",
        selectedGateId: detail.gate.gate_id,
        detail,
        errorStatus: "APPROVAL_DECISION_UNAUTHORIZED"
      })
    );

    assert.match(detailHtml, /data-approval-decision="APPROVE"/);
    assert.match(detailHtml, /data-approval-decision="REJECT"/);
    assert.match(detailHtml, /검토 의견/);
    assert.match(decidedHtml, /decision 42100000/);
    assert.match(decidedHtml, /data-approval-decision="APPROVE" disabled/);
    assert.match(deniedHtml, /data-phase="UNAUTHORIZED"/);
    assert.match(deniedHtml, /data-approval-decision="REJECT" disabled/);
  });

  it("escapes display-safe text and renders loading and empty states", () => {
    const inbox = normalizeApprovalInbox(buildDefaultMockApprovalInbox());
    inbox.gates[0] = { ...inbox.gates[0], title: "<script>alert(1)</script>" };
    const html = renderApprovalUi(readyState({ inbox }));
    const loading = renderApprovalUi(readyState({ phase: "LOADING", inbox: null }));
    const empty = renderApprovalUi(
      readyState({ inbox: { ...inbox, gates: [], returned_count: 0 } })
    );

    assert.doesNotMatch(html, /<script>/);
    assert.match(html, /&lt;script&gt;/);
    assert.match(loading, /불러오는 중/);
    assert.match(empty, /처리할 승인 요청이 없습니다/);
  });

  it("discards an in-flight inbox response after the session client changes", async () => {
    let resolveInbox;
    const staleInbox = new Promise(resolve => {
      resolveInbox = resolve;
    });
    const container = {
      innerHTML: "",
      addEventListener() {},
      querySelector() {
        return null;
      }
    };
    const client = listApprovalGates => ({
      clientMode: "mock",
      listApprovalGates,
      async getApprovalGate() {},
      async submitApprovalDecision() {}
    });
    const controller = createApprovalUiController({
      container,
      client: client(() => staleInbox)
    });

    const refresh = controller.refresh();
    controller.setClient(client(async () => ({ gates: [] })));
    resolveInbox(normalizeApprovalInbox(buildDefaultMockApprovalInbox()));
    await refresh;

    assert.equal(controller.snapshot().phase, "IDLE");
    assert.doesNotMatch(container.innerHTML, /data-approval-domain/);
  });
});
