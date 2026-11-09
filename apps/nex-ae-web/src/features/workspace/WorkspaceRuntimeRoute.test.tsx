import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InstalledBrowserRuntime } from "../../app/runtime/installedRuntime";
import { SessionProvider } from "../../app/providers/SessionProvider";
import { InstalledWorkspaceRuntime } from "./WorkspaceRuntimeRoute";

describe("installed Workspace runtime route", () => {
  it("connects the installed clients to an owner-scoped typed result", async () => {
    const user = userEvent.setup();
    const createWorkspace = vi.fn(async () => ({
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      title: "내 업무 공간",
    }));
    const admitInteraction = vi.fn(async (payload: Record<string, unknown>) => ({
      groundedGenerationClientSchemaVersion: "ae_web_grounded_generation_client.v1",
      interactionId: String(payload.interaction_id),
      status: "PENDING",
      terminal: false,
      retryable: false,
      asyncGeneration: { lifecycle_status: "PENDING", cancellable: true },
      semanticPlanning: { status: "COMPILED" },
    }));
    const getInteractionAgentResult = vi.fn(async (interactionId: string) => ({
      interactionId,
      executionState: "SUCCEEDED",
      executionPhase: "FINALIZE",
      terminal: true,
      result: {
        status: "SUCCEEDED",
        artifactRefs: [],
        warnings: [],
        businessSummary: {
          resultType: "FINANCE.VOUCHER_DRAFT",
          schemaVersion: "ae_business_result_summary.v1",
          outcome: "COMMITTED",
          verificationStatus: "VERIFIED",
          approvalState: "APPROVED",
          businessOperationId: "private-operation",
          voucherNumber: "V-2026-009",
          amount: "8500.00",
          currency: "KRW",
          accountCodes: ["TRAVEL"],
          projectCode: "NVT",
          businessObjectLink: null,
        },
      },
    }));
    const submitGenerationFeedback = vi.fn(async () => ({ status: "RECORDED" }));
    const runtime = {
      clients: {
        workspace: { clientMode: "fetch", createWorkspace },
        groundedGeneration: {
          clientMode: "fetch",
          admitInteraction,
          getProgress: vi.fn(),
          refreshInteraction: vi.fn(),
          getResponse: vi.fn(),
          getCitationQuality: vi.fn(),
        },
        interactionAgentResult: { clientMode: "fetch", getInteractionAgentResult },
        generationFeedback: { clientMode: "fetch", submitGenerationFeedback },
        repairedResponseReview: null,
        repairedResponseDecision: null,
      },
    } as unknown as InstalledBrowserRuntime;

    render(
      <SessionProvider initialSession={{
        status: "authenticated",
        sessionId: "session-1",
        tenantRef: { type: "oa.tenant", id: "VO00" },
        subjectRef: { type: "oa.user", id: "employee-1" },
        scopes: [],
        roles: [],
      }}>
        <InstalledWorkspaceRuntime runtime={runtime} />
      </SessionProvider>,
    );
    await user.type(screen.getByRole("textbox", { name: "업무 요청" }), "교통비 전표를 등록해 주세요.");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(screen.getByText("교통비 전표를 등록해 주세요.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "전표 등록 결과" })).toBeInTheDocument());
    expect(screen.getByText("V-2026-009")).toBeInTheDocument();
    expect(screen.queryByText("private-operation")).not.toBeInTheDocument();
    expect(createWorkspace).toHaveBeenCalledWith({ title: "내 업무 공간", locale: "ko-KR" });
    expect(admitInteraction).toHaveBeenCalledOnce();
    expect(getInteractionAgentResult).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "도움됨" }));
    await waitFor(() => expect(screen.getByText("저장됨")).toBeInTheDocument());
    expect(submitGenerationFeedback).toHaveBeenCalledOnce();
    expect(submitGenerationFeedback.mock.calls[0]?.[0].payload).toMatchObject({
      tenant_id: "VO00",
      user_id: "employee-1",
      chat_document_id: "conversation-1",
      feedback_value: "positive",
    });
  });
});
