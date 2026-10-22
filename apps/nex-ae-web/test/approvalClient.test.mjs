import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ApprovalClientError,
  approvalDecisionRoute,
  approvalGateRoute,
  approvalInboxRoute,
  assertApprovalPayloadSafe,
  buildApprovalDecisionRequest,
  buildDefaultMockApprovalInbox,
  createFetchApprovalClient,
  createMockApprovalClient,
  isApprovalGateExpired,
  normalizeApprovalDecision,
  normalizeApprovalGateDetail,
  normalizeApprovalInbox
} from "../src/approvalClient.js";

const GATE_ID = "42000000-0000-4000-8000-000000000001";
const DENIED_ID = "42000000-0000-4000-8000-000000000002";
const BUSINESS_ID = "42000000-0000-4000-8000-000000000003";
const EXPIRED_ID = "42000000-0000-4000-8000-000000000004";

describe("AE Web approval client", () => {
  it("builds bounded same-origin routes and exact decision requests", () => {
    assert.equal(approvalInboxRoute(), "/api/v1/approval-gates?limit=50");
    assert.equal(approvalGateRoute(GATE_ID), `/api/v1/approval-gates/${GATE_ID}`);
    assert.equal(
      approvalDecisionRoute(GATE_ID),
      `/api/v1/approval-gates/${GATE_ID}/decisions`
    );
    assert.deepEqual(
      buildApprovalDecisionRequest({
        decision: "APPROVE",
        decisionComment: " Reviewed. ",
        correlationId: "conversation-s42",
        causationId: "interaction-s42"
      }),
      {
        schema_version: "wc_approval_decision_request.v1",
        decision: "APPROVE",
        decision_comment: "Reviewed.",
        correlation_id: "conversation-s42",
        causation_id: "interaction-s42"
      }
    );
    assert.throws(() => approvalInboxRoute(0), ApprovalClientError);
    assert.throws(() => approvalInboxRoute(101), ApprovalClientError);
    assert.throws(() => approvalGateRoute("bad"), ApprovalClientError);
    assert.throws(
      () => buildApprovalDecisionRequest({ decision: "DELETE" }),
      error => error.status === "APPROVAL_DECISION_INVALID"
    );
    assert.throws(
      () =>
        buildApprovalDecisionRequest({
          decision: "REJECT",
          decisionComment: "x".repeat(2001)
        }),
      error => error.status === "APPROVAL_DECISION_COMMENT_INVALID"
    );
  });

  it("normalizes and redacts inbox, detail, and decision contracts", () => {
    const inbox = normalizeApprovalInbox(buildDefaultMockApprovalInbox(), {
      clientMode: "mock",
      route: approvalInboxRoute()
    });
    const detail = normalizeApprovalGateDetail({
      schema_version: "wc_approval_gate_detail.v1",
      gate: inbox.gates[0],
      created_at: "2026-10-22T08:00:00Z",
      version: 1,
      decision_options: ["APPROVE", "REJECT"]
    });
    const decision = normalizeApprovalDecision({
      schema_version: "wc_approval_decision.v1",
      tenant_id: "tenant-local",
      decision_id: "42100000-0000-4000-8000-000000000001",
      approval_work_item_id: GATE_ID,
      decision: "APPROVE",
      decided_by: "owner-local",
      decision_comment: null,
      decision_version: 1,
      authorized_by_oa: true,
      oa_decision_ref: "oa-decision-s42",
      authorization_revision_hash: `sha256:${"a".repeat(64)}`,
      authorization_checked_at: "2026-10-22T09:00:00Z",
      decided_at: "2026-10-22T09:00:00Z"
    });

    assert.equal(inbox.gates.length, 4);
    assert.deepEqual(
      [...new Set(inbox.gates.map(gate => gate.approval_domain))].sort(),
      ["AGENT_FORMAL", "BUSINESS_FORMAL", "NSL_WRITE"]
    );
    assert.equal(detail.gate.gate_id, GATE_ID);
    assert.equal(decision.authorized_by_oa, true);
    assert.doesNotMatch(
      JSON.stringify({ inbox, detail, decision }),
      /protected_request|semantic_hash|resume_target_ref|service_token|source_ref/
    );
    assert.throws(
      () => assertApprovalPayloadSafe({ protected_request_ref: "private" }),
      error => error.status === "APPROVAL_PAYLOAD_UNSAFE"
    );
  });

  it("supports approve, reject, exact replay, conflict, denial, and expiry", async () => {
    const client = createMockApprovalClient({
      now: () => new Date("2026-10-22T09:00:00Z")
    });
    const request = buildApprovalDecisionRequest({ decision: "APPROVE" });
    const first = await client.submitApprovalDecision(GATE_ID, request);
    const replay = await client.submitApprovalDecision(GATE_ID, request);
    const rejected = await client.submitApprovalDecision(
      BUSINESS_ID,
      buildApprovalDecisionRequest({ decision: "REJECT" })
    );

    assert.equal(first.decision_id, replay.decision_id);
    assert.equal(client.getDecisionCallCount(), 3);
    assert.equal(rejected.decision, "REJECT");
    await assert.rejects(
      () =>
        client.submitApprovalDecision(
          GATE_ID,
          buildApprovalDecisionRequest({ decision: "REJECT" })
        ),
      error => error.status === "APPROVAL_DECISION_CONFLICT"
    );
    await assert.rejects(
      () => client.submitApprovalDecision(DENIED_ID, request),
      error => error.status === "APPROVAL_DECISION_UNAUTHORIZED" && error.httpStatus === 403
    );
    await assert.rejects(
      () => client.submitApprovalDecision(EXPIRED_ID, request),
      error => error.status === "APPROVAL_EXPIRED" && error.httpStatus === 409
    );
    const inbox = await client.listApprovalGates({ limit: 50 });
    assert.equal(inbox.gates.some(gate => gate.gate_id === GATE_ID), false);
    assert.equal(inbox.gates.some(gate => gate.gate_id === BUSINESS_ID), false);
  });

  it("loads safe mock detail and rejects missing identities and malformed requests", async () => {
    const client = createMockApprovalClient();
    const detail = await client.getApprovalGate(GATE_ID);
    assert.deepEqual(detail.decision_options, ["APPROVE", "REJECT"]);
    await assert.rejects(
      () => client.getApprovalGate("42000000-0000-4000-8000-000000000099"),
      error => error.status === "APPROVAL_GATE_NOT_FOUND"
    );
    await assert.rejects(
      () => client.submitApprovalDecision(GATE_ID, { schema_version: "old" }),
      error => error.status === "APPROVAL_DECISION_REQUEST_INVALID"
    );
  });

  it("uses same-origin fetch without browser service headers", async () => {
    const calls = [];
    const inbox = buildDefaultMockApprovalInbox();
    const detail = {
      schema_version: "wc_approval_gate_detail.v1",
      gate: inbox.gates[0],
      created_at: "2026-10-22T08:00:00Z",
      version: 1,
      decision_options: ["APPROVE", "REJECT"]
    };
    const decision = {
      schema_version: "wc_approval_decision.v1",
      tenant_id: "tenant-local",
      decision_id: "42100000-0000-4000-8000-000000000001",
      approval_work_item_id: GATE_ID,
      decision: "APPROVE",
      decided_by: "owner-local",
      decision_comment: null,
      decision_version: 1,
      authorized_by_oa: true,
      oa_decision_ref: "oa-decision-s42",
      authorization_revision_hash: `sha256:${"a".repeat(64)}`,
      authorization_checked_at: "2026-10-22T09:00:00Z",
      decided_at: "2026-10-22T09:00:00Z"
    };
    const responses = [inbox, detail, decision];
    const client = createFetchApprovalClient({
      baseUrl: "/ae-api/",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return { ok: true, status: 200, json: async () => responses.shift() };
      }
    });

    await client.listApprovalGates();
    await client.getApprovalGate(GATE_ID);
    await client.submitApprovalDecision(
      GATE_ID,
      buildApprovalDecisionRequest({ decision: "APPROVE" })
    );

    assert.equal(calls[0].url, "/ae-api/api/v1/approval-gates?limit=50");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[2].options.method, "POST");
    for (const call of calls) {
      assert.equal(call.options.headers.Authorization, undefined);
      assert.equal(call.options.headers["X-NeX-Tenant-Id"], undefined);
      assert.equal(call.options.headers["X-NeX-Subject-Id"], undefined);
    }
  });

  it("maps fetch HTTP, network, malformed response, and missing fetch failures", async () => {
    const httpClient = createFetchApprovalClient({
      fetchImpl: async () => ({
        ok: false,
        status: 403,
        json: async () => ({
          error_code: "wc.approval_authorization_denied",
          detail: "Denied.",
          retryable: false
        })
      })
    });
    await assert.rejects(
      () => httpClient.listApprovalGates(),
      error => error.status === "wc.approval_authorization_denied" && error.httpStatus === 403
    );

    const networkClient = createFetchApprovalClient({
      fetchImpl: async () => {
        throw new Error("private");
      }
    });
    await assert.rejects(
      () => networkClient.listApprovalGates(),
      error => error.status === "APPROVAL_NETWORK_ERROR" && error.retryable
    );

    const malformedClient = createFetchApprovalClient({
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({ bad: true })
      })
    });
    await assert.rejects(
      () => malformedClient.listApprovalGates(),
      error => error.status === "APPROVAL_INBOX_INVALID"
    );

    assert.throws(
      () => createFetchApprovalClient({ fetchImpl: "bad" }),
      error => error.status === "APPROVAL_FETCH_REQUIRED"
    );
    assert.throws(
      () => createFetchApprovalClient({ baseUrl: 1, fetchImpl: async () => {} }),
      error => error.status === "APPROVAL_BASE_URL_INVALID"
    );
  });

  it("classifies expiration deterministically", () => {
    const gate = buildDefaultMockApprovalInbox().gates.at(-1);
    assert.equal(isApprovalGateExpired(gate, new Date("2026-10-22T09:00:00Z")), true);
    assert.equal(isApprovalGateExpired({ expires_at: null }), false);
    assert.equal(isApprovalGateExpired({ expires_at: "bad" }), false);
  });

  it("rejects malformed contract branches", () => {
    const inbox = buildDefaultMockApprovalInbox();
    assert.throws(() => normalizeApprovalInbox({}), ApprovalClientError);
    assert.throws(
      () => normalizeApprovalInbox({ ...inbox, returned_count: 1 }),
      ApprovalClientError
    );
    assert.throws(
      () => normalizeApprovalInbox({ ...inbox, subject_ref: { type: "bad", id: "x" } }),
      error => error.status === "APPROVAL_SUBJECT_INVALID"
    );
    assert.throws(
      () =>
        normalizeApprovalGateDetail({
          schema_version: "wc_approval_gate_detail.v1",
          gate: inbox.gates[0],
          created_at: "now",
          version: 0,
          decision_options: ["APPROVE", "REJECT"]
        }),
      error => error.status === "APPROVAL_INTEGER_INVALID"
    );
    assert.throws(
      () => normalizeApprovalDecision({ schema_version: "old" }),
      error => error.status === "APPROVAL_DECISION_RESPONSE_INVALID"
    );
  });
});
