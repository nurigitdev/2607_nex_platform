import { describe, expect, it, vi } from "vitest";

import {
  WorkspaceClientError,
  createWorkspaceClient,
  projectWorkspace,
} from "./workspaceClientPort";

const WORKSPACE_RESPONSE = Object.freeze({
  workspace_schema_version: "ae_workspace_state.v1",
  workspace_id: "workspace-1",
  chat_document_id: "conversation-1",
  title: "내 업무 공간",
});

describe("owner-scoped workspace client", () => {
  it("creates an idempotent browser workspace without owner claims in the payload", async () => {
    const fetchImpl = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify(WORKSPACE_RESPONSE), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    const client = createWorkspaceClient({
      mode: "fetch",
      baseUrl: "/ae-api",
      fetchImpl,
    });

    await expect(client.createWorkspace({ title: "내 업무 공간" })).resolves.toEqual({
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      title: "내 업무 공간",
    });
    expect(fetchImpl).toHaveBeenCalledWith("/ae-api/api/v1/workspaces", expect.objectContaining({
      method: "POST",
      credentials: "include",
    }));
    const body = JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ title: "내 업무 공간", runtime_defaults: { locale: "ko-KR" } });
    expect(body).not.toHaveProperty("tenant_id");
    expect(body).not.toHaveProperty("owner_user_id");
  });

  it("supports a bounded mock identity and rejects invalid responses", async () => {
    const mock = createWorkspaceClient({ mode: "mock" });
    await expect(mock.createWorkspace({ title: "개인 작업" })).resolves.toMatchObject({
      workspaceId: "workspace-local",
      conversationId: "chat-doc-local",
    });
    expect(() => projectWorkspace({ ...WORKSPACE_RESPONSE, workspace_schema_version: "other" }))
      .toThrowError(expect.objectContaining<Partial<WorkspaceClientError>>({
        status: "WORKSPACE_RESPONSE_INVALID",
      }));
  });

  it("maps HTTP and malformed JSON failures without reflecting server detail", async () => {
    const fetchImpl = vi.fn<typeof globalThis.fetch>(async () => new Response("not-json", { status: 503 }));
    const client = createWorkspaceClient({
      mode: "fetch",
      fetchImpl,
    });
    await expect(client.createWorkspace({ title: "내 업무 공간" })).rejects.toMatchObject({
      status: "WORKSPACE_REQUEST_FAILED",
      statusCode: 503,
      message: "Workspace를 준비하지 못했습니다.",
    });
  });
});
