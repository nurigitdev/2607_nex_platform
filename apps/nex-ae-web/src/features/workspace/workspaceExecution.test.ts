import { describe, expect, it, vi } from "vitest";

import { createMockGroundedGenerationClient } from "../../groundedGenerationClient.js";
import {
  executeWorkspaceDraft,
  issueFromStatus,
  workStateFromAgentProjection,
  type AgentResultProjection,
  type GroundedGenerationClientPort,
  type InteractionAgentResultPort,
  type WorkspaceExecutionUpdate,
} from "./workspaceExecution";

const DRAFT = Object.freeze({
  prompt: "NVT 프로젝트 비용을 근거와 함께 알려주세요.",
  useEvidence: true,
  outputFormat: "answer" as const,
  attachments: [],
});

describe("Workspace durable execution integration", () => {
  it("runs grounded generation and projects verified citation counts", async () => {
    const updates: WorkspaceExecutionUpdate[] = [];
    const outcome = await executeWorkspaceDraft({
      draft: DRAFT,
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      sourceDocumentIds: ["document-1", "document-1"],
      generationClient: createMockGroundedGenerationClient() as GroundedGenerationClientPort,
      interactionResultClient: unusedAgentResultClient(),
      onUpdate: update => updates.push(update),
      wait: async () => undefined,
    });

    expect(outcome).toMatchObject({
      status: "COMPLETED",
      workState: { state: "SUCCEEDED" },
      message: { content: "Grounded mock response [1]." },
    });
    expect(outcome.sources).toEqual([{ id: expect.stringMatching(/^citations:/), label: "검증된 근거 1건", detail: "인용 검증 완료" }]);
    expect(updates.map(item => item.workState.state)).toContain("SUCCEEDED");
    expect(updates.map(item => item.workState.state)).not.toContain("UNKNOWN");
  });

  it("shows only actual planning, running, approval, resume, and success states", async () => {
    const updates: WorkspaceExecutionUpdate[] = [];
    const resultClient = sequencedAgentResultClient([
      agentResult("RUNNING", "STEP_EXECUTE"),
      agentResult("WAITING_APPROVAL", "APPROVAL_WAIT"),
      agentResult("RESUMING", "STEP_EXECUTE"),
      agentResult("SUCCEEDED", "FINALIZE", {
        status: "SUCCEEDED",
        artifactRefs: ["AE:ARTIFACT:one"],
        warnings: ["private-warning-code"],
        businessSummary: voucherSummary(),
      }),
    ]);
    const outcome = await executeWorkspaceDraft({
      draft: { ...DRAFT, useEvidence: false },
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      generationClient: compiledGenerationClient(),
      interactionResultClient: resultClient,
      maxAgentPolls: 4,
      wait: async () => undefined,
      onUpdate: update => updates.push(update),
    });

    const observedStates = updates
      .map(item => item.workState.state)
      .filter((state, index, values) => state !== values[index - 1]);
    expect(observedStates).toEqual([
      "ACCEPTING", "PLANNING", "RUNNING",
      "WAITING_APPROVAL", "RESUMING", "SUCCEEDED",
    ]);
    expect(outcome).toMatchObject({
      status: "COMPLETED",
      result: {
        status: "SUCCEEDED",
        artifactCount: 1,
        warnings: ["결과에 확인이 필요한 항목이 1건 있습니다."],
        businessSummary: { resultType: "FINANCE.VOUCHER_DRAFT" },
      },
    });
    expect(JSON.stringify(outcome)).not.toContain("private-warning-code");
  });

  it.each([
    ["PARTIAL", "PARTIAL", "PARTIAL", false],
    ["FAILED", "FAILED", "FAILED", true],
  ])("keeps %s terminal semantics and safe recovery guidance", async (
    executionState,
    resultStatus,
    expectedStatus,
    retryable,
  ) => {
    const outcome = await executeWorkspaceDraft({
      draft: { ...DRAFT, useEvidence: false },
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      generationClient: compiledGenerationClient(),
      interactionResultClient: sequencedAgentResultClient([
        agentResult(executionState, "FINALIZE", {
          status: resultStatus,
          artifactRefs: [],
          warnings: [],
        }),
      ]),
      maxAgentPolls: 1,
      wait: async () => undefined,
    });

    expect(outcome.status).toBe(expectedStatus);
    expect(outcome.workState.state).toBe(executionState);
    expect(Boolean(outcome.issue?.retryable)).toBe(retryable);
  });

  it("fails closed for an aborted execution and sanitizes technical failures", async () => {
    const abort = new AbortController();
    abort.abort();
    await expect(executeWorkspaceDraft({
      draft: DRAFT,
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      generationClient: compiledGenerationClient(),
      interactionResultClient: unusedAgentResultClient(),
      signal: abort.signal,
    })).rejects.toMatchObject({ status: "WORKSPACE_EXECUTION_CANCELLED" });

    expect(issueFromStatus("provider-secret-42", true)).toEqual({
      message: "요청을 완료하지 못했습니다.",
      retryable: true,
      nextAction: "잠시 후 다시 시도해 주세요.",
      technicalCode: "WORKSPACE_EXECUTION_UNAVAILABLE",
    });
  });

  it("uses durable Agent phase when the broad execution state is still RUNNING", () => {
    expect(workStateFromAgentProjection(agentResult("RUNNING", "PLAN_COMPILE")).state)
      .toBe("PLANNING");
    expect(workStateFromAgentProjection(agentResult("RUNNING", "APPROVAL_WAIT")).state)
      .toBe("WAITING_APPROVAL");
    expect(workStateFromAgentProjection(agentResult("RUNNING", "RESULT_VERIFY")).state)
      .toBe("VERIFYING");
    expect(workStateFromAgentProjection(agentResult("BLOCKED", "FINALIZE")).state)
      .toBe("FAILED");
  });
});

function compiledGenerationClient(): GroundedGenerationClientPort {
  return {
    clientMode: "mock",
    async admitInteraction(payload) {
      return {
        groundedGenerationClientSchemaVersion: "ae_web_grounded_generation_client.v1",
        interactionId: String(payload.interaction_id),
        status: "PENDING",
        terminal: false,
        retryable: false,
        asyncGeneration: { lifecycle_status: "PENDING", cancellable: true },
        semanticPlanning: { status: "COMPILED" },
      };
    },
    getProgress: vi.fn(),
    refreshInteraction: vi.fn(),
    getResponse: vi.fn(),
    getCitationQuality: vi.fn(),
  };
}

function sequencedAgentResultClient(values: readonly AgentResultProjection[]): InteractionAgentResultPort {
  let index = 0;
  return {
    clientMode: "mock",
    async getInteractionAgentResult() {
      return values[Math.min(index++, values.length - 1)]!;
    },
  };
}

function unusedAgentResultClient(): InteractionAgentResultPort {
  return {
    clientMode: "mock",
    getInteractionAgentResult: vi.fn(async () => agentResult("SUCCEEDED", "FINALIZE")),
  };
}

function agentResult(
  executionState: string,
  executionPhase: string,
  result: AgentResultProjection["result"] = null,
): AgentResultProjection {
  return {
    interactionId: "interaction-1",
    executionState,
    executionPhase,
    terminal: ["SUCCEEDED", "PARTIAL", "FAILED", "BLOCKED", "CANCELLED"].includes(executionState),
    result,
  };
}

function voucherSummary() {
  return {
    resultType: "FINANCE.VOUCHER_DRAFT" as const,
    schemaVersion: "ae_business_result_summary.v1" as const,
    outcome: "COMMITTED" as const,
    verificationStatus: "VERIFIED",
    approvalState: "APPROVED" as const,
    businessOperationId: "operation-1",
    voucherNumber: "V-2026-001",
    amount: "12000.00",
    currency: "KRW",
    accountCodes: ["TRAVEL"],
    projectCode: "NVT",
    businessObjectLink: null,
  };
}
