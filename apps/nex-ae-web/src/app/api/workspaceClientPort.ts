export interface WorkspaceIdentity {
  readonly workspaceId: string;
  readonly conversationId: string;
  readonly title: string;
}

export interface WorkspaceClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly createWorkspace: (input: {
    readonly title: string;
    readonly locale?: string;
  }) => Promise<WorkspaceIdentity>;
}

export class WorkspaceClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;

  constructor(message: string, status = "WORKSPACE_REQUEST_FAILED", statusCode: number | null = null) {
    super(message);
    this.name = "WorkspaceClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function createWorkspaceClient({
  mode,
  baseUrl = "",
  fetchImpl,
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
}): WorkspaceClientPort {
  if (mode === "mock") {
    return Object.freeze({
      clientMode: "mock" as const,
      async createWorkspace(input: { readonly title: string; readonly locale?: string }) {
        const title = requiredTitle(input.title);
        return Object.freeze({
          workspaceId: "workspace-local",
          conversationId: "chat-doc-local",
          title,
        });
      },
    });
  }
  if (typeof fetchImpl !== "function") {
    throw new WorkspaceClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  return Object.freeze({
    clientMode: "fetch" as const,
    async createWorkspace(input: { readonly title: string; readonly locale?: string }) {
      const response = await fetchImpl(`${baseUrl}/api/v1/workspaces`, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          title: requiredTitle(input.title),
          runtime_defaults: { locale: optionalLocale(input.locale) },
        }),
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new WorkspaceClientError(
          "Workspace를 준비하지 못했습니다.",
          textOr(payload.error_code, "WORKSPACE_REQUEST_FAILED"),
          response.status,
        );
      }
      return projectWorkspace(payload);
    },
  });
}

export function projectWorkspace(value: unknown): WorkspaceIdentity {
  if (!isObject(value) || value.workspace_schema_version !== "ae_workspace_state.v1") {
    throw new WorkspaceClientError("Workspace 응답이 올바르지 않습니다.", "WORKSPACE_RESPONSE_INVALID");
  }
  return Object.freeze({
    workspaceId: requiredText(value.workspace_id, "workspace_id"),
    conversationId: requiredText(value.chat_document_id, "chat_document_id"),
    title: requiredText(value.title, "title"),
  });
}

function requiredTitle(value: unknown) {
  const title = requiredText(value, "title");
  if (title.length > 120) {
    throw new WorkspaceClientError("Workspace 제목이 너무 깁니다.", "WORKSPACE_TITLE_INVALID");
  }
  return title;
}

function optionalLocale(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "ko-KR";
}

function requiredText(value: unknown, field: string) {
  if (typeof value !== "string" || !value.trim()) {
    throw new WorkspaceClientError(`${field} 값이 필요합니다.`, "WORKSPACE_RESPONSE_INVALID");
  }
  return value.trim();
}

function textOr(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await response.json();
    return isObject(value) ? value : {};
  } catch {
    return {};
  }
}
