import {
  buildGroundedGenerationRequest,
  runGroundedGenerationWorkflow,
} from "../../groundedGenerationWorkflow.js";
import {
  buildGroundedGenerationPresentation,
  buildGroundedGenerationPresentationFailure,
} from "../../groundedGenerationPresentation.js";
import { createInteractionId } from "../../runtimeIdentifiers.js";
import { mapSourceWorkState, mapWorkState, type WorkStatePresentation } from "../../ux/workState";
import type { WorkspaceResultProjection } from "./BusinessResultCard";
import type { WorkspaceDraft, WorkspaceMessage, WorkspaceSource } from "./WorkspacePage";

const executeGroundedGeneration = runGroundedGenerationWorkflow as unknown as (input: {
  readonly client: GroundedGenerationClientPort;
  readonly request: Readonly<Record<string, unknown>>;
  readonly maxPolls: number;
  readonly wait: (seconds: number) => Promise<void>;
  readonly signal: AbortSignal | null;
  readonly onState: (state: Record<string, unknown>) => void;
}) => Promise<any>;

const presentGroundedGeneration = buildGroundedGenerationPresentation as unknown as (input: {
  readonly workflow: any;
  readonly repairedResponseReviewClient: unknown;
}) => Promise<any>;

export interface GroundedGenerationClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly admitInteraction: (payload: Readonly<Record<string, unknown>>) => Promise<unknown>;
  readonly getProgress: (interactionId: string) => Promise<unknown>;
  readonly refreshInteraction: (interactionId: string) => Promise<unknown>;
  readonly getResponse: (interactionId: string) => Promise<unknown>;
  readonly getCitationQuality: (interactionId: string) => Promise<unknown>;
  readonly cancelInteraction?: (interactionId: string) => Promise<unknown>;
}

export interface InteractionAgentResultPort {
  readonly clientMode: "mock" | "fetch";
  readonly getInteractionAgentResult: (interactionId: string) => Promise<AgentResultProjection>;
}

export interface AgentResultProjection {
  readonly interactionId: string;
  readonly executionState: string;
  readonly executionPhase: string;
  readonly terminal: boolean;
  readonly result: null | {
    readonly status: string;
    readonly artifactRefs: readonly string[];
    readonly warnings: readonly string[];
    readonly businessSummary?: WorkspaceResultProjection["businessSummary"];
  };
}

export interface WorkspaceExecutionIssue {
  readonly message: string;
  readonly retryable: boolean;
  readonly nextAction: string;
  readonly technicalCode: string;
}

export interface WorkspaceExecutionUpdate {
  readonly workState: WorkStatePresentation;
  readonly interactionId: string | null;
  readonly message?: WorkspaceMessage;
  readonly sources?: readonly WorkspaceSource[];
  readonly result?: WorkspaceResultProjection | null;
  readonly issue?: WorkspaceExecutionIssue | null;
}

export interface WorkspaceExecutionOutcome extends WorkspaceExecutionUpdate {
  readonly status: "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED" | "ACTIVE";
}

export async function executeWorkspaceDraft({
  draft,
  workspaceId,
  conversationId,
  sourceDocumentIds = [],
  generationClient,
  interactionResultClient,
  repairedResponseReviewClient = null,
  onUpdate = () => undefined,
  wait = waitForSeconds,
  maxGenerationPolls = 30,
  maxAgentPolls = 150,
  agentPollSeconds = 2,
  signal = null,
}: {
  readonly draft: WorkspaceDraft;
  readonly workspaceId: string;
  readonly conversationId: string;
  readonly sourceDocumentIds?: readonly string[];
  readonly generationClient: GroundedGenerationClientPort;
  readonly interactionResultClient: InteractionAgentResultPort;
  readonly repairedResponseReviewClient?: unknown;
  readonly onUpdate?: (update: WorkspaceExecutionUpdate) => void;
  readonly wait?: (seconds: number) => Promise<void>;
  readonly maxGenerationPolls?: number;
  readonly maxAgentPolls?: number;
  readonly agentPollSeconds?: number;
  readonly signal?: AbortSignal | null;
}): Promise<WorkspaceExecutionOutcome> {
  const interactionId = createInteractionId();
  const documentIds = uniqueTexts(sourceDocumentIds);
  const grounded = draft.useEvidence && documentIds.length > 0;
  onUpdate(update("ACCEPTING", interactionId));
  const request = buildGroundedGenerationRequest({
    interactionId,
    workspaceId,
    chatDocumentId: conversationId,
    userMessage: draft.prompt,
    documentScope: grounded ? { document_scope: { document_ids: documentIds } } : null,
    grounded,
  });
  const workflow = await executeGroundedGeneration({
    client: generationClient,
    request,
    maxPolls: maxGenerationPolls,
    wait,
    signal,
    onState: (state: Record<string, unknown>) => {
      assertNotAborted(signal);
      onUpdate({
        ...updateFromGenerationState(state, interactionId),
        issue: null,
      });
    },
  });
  assertNotAborted(signal);

  if (workflow.agentExecutionAdmitted === true) {
    onUpdate(update("PLANNING", interactionId));
    return pollAgentResult({
      client: interactionResultClient,
      interactionId,
      onUpdate,
      wait,
      maxPolls: maxAgentPolls,
      pollSeconds: agentPollSeconds,
      signal,
    });
  }

  let presentation;
  try {
    presentation = await presentGroundedGeneration({
      workflow,
      repairedResponseReviewClient,
    });
  } catch (error) {
    presentation = buildGroundedGenerationPresentationFailure(workflow, error);
  }
  if (workflow.status === "COMPLETED" && presentation.displayMode !== "PRESENTATION_UNAVAILABLE") {
    const sources = groundedSources(workflow);
    const outcome: WorkspaceExecutionOutcome = {
      status: "COMPLETED",
      workState: mapWorkState("SUCCEEDED"),
      interactionId,
      message: {
        id: `assistant:${interactionId}`,
        role: "assistant",
        content: presentation.assistantText,
      },
      sources,
      result: null,
      issue: null,
    };
    onUpdate(outcome);
    return outcome;
  }
  const issue = issueFromStatus(workflow.state?.errorStatus, workflow.state?.retryable === true);
  const outcome: WorkspaceExecutionOutcome = {
    status: workflow.status === "ACTIVE" ? "ACTIVE" : "FAILED",
    workState: mapWorkState(workflow.status === "ACTIVE" ? "RUNNING" : "FAILED"),
    interactionId,
    message: {
      id: `assistant:${interactionId}`,
      role: "assistant",
      content: presentation.assistantText,
    },
    result: null,
    issue,
  };
  onUpdate(outcome);
  return outcome;
}

async function pollAgentResult({
  client,
  interactionId,
  onUpdate,
  wait,
  maxPolls,
  pollSeconds,
  signal,
}: {
  readonly client: InteractionAgentResultPort;
  readonly interactionId: string;
  readonly onUpdate: (update: WorkspaceExecutionUpdate) => void;
  readonly wait: (seconds: number) => Promise<void>;
  readonly maxPolls: number;
  readonly pollSeconds: number;
  readonly signal: AbortSignal | null;
}): Promise<WorkspaceExecutionOutcome> {
  for (let attempt = 1; attempt <= maxPolls; attempt += 1) {
    assertNotAborted(signal);
    let projection: AgentResultProjection;
    try {
      projection = await client.getInteractionAgentResult(interactionId);
    } catch (error) {
      if (statusCodeOf(error) === 404) {
        if (client.clientMode !== "mock") await wait(pollSeconds);
        continue;
      }
      throw error;
    }
    const workState = workStateFromAgentProjection(projection);
    const current = { workState, interactionId, issue: null };
    onUpdate(current);
    if (projection.terminal) {
      const status = projection.result?.status || projection.executionState;
      const terminalState = mapSourceWorkState("AgentExecution", status);
      const result = resultProjection(projection, status);
      const succeeded = ["SUCCEEDED", "PARTIAL"].includes(status);
      const outcome: WorkspaceExecutionOutcome = {
        status: status === "PARTIAL" ? "PARTIAL" : succeeded ? "COMPLETED" : "FAILED",
        workState: terminalState,
        interactionId,
        message: {
          id: `assistant:${interactionId}`,
          role: "assistant",
          content: succeeded
            ? "Agent 업무 처리가 완료되었습니다."
            : "업무 처리가 종료되었습니다. 아래 안내를 확인해 주세요.",
        },
        result,
        issue: succeeded ? null : issueFromStatus(status, status === "FAILED"),
      };
      onUpdate(outcome);
      return outcome;
    }
    if (client.clientMode !== "mock") await wait(pollSeconds);
  }
  const outcome: WorkspaceExecutionOutcome = {
    status: "ACTIVE",
    workState: mapWorkState("RUNNING"),
    interactionId,
    issue: {
      message: "업무 처리가 계속 진행 중입니다.",
      retryable: false,
      nextAction: "잠시 후 진행 상태를 다시 확인해 주세요.",
      technicalCode: "AGENT_RESULT_POLL_LIMIT_REACHED",
    },
  };
  onUpdate(outcome);
  return outcome;
}

function updateFromGenerationState(state: Record<string, unknown>, interactionId: string) {
  const lifecycle = typeof state.lifecycleStatus === "string" ? state.lifecycleStatus : "UNKNOWN";
  const currentStage = typeof state.currentStage === "string" ? state.currentStage : "";
  const workState = currentStage.includes("PLAN")
    ? mapWorkState("PLANNING")
    : mapSourceWorkState("GenerationLifecycle", lifecycle);
  return { workState, interactionId };
}

export function workStateFromAgentProjection(projection: AgentResultProjection) {
  if (projection.terminal) {
    return mapSourceWorkState(
      "AgentExecution",
      projection.result?.status || projection.executionState,
    );
  }
  const phase = projection.executionPhase.toUpperCase();
  if (phase.includes("PLAN")) return mapWorkState("PLANNING");
  if (phase.includes("APPROVAL")) return mapWorkState("WAITING_APPROVAL");
  if (phase.includes("RESUME")) return mapWorkState("RESUMING");
  if (phase.includes("VERIFY") || phase.includes("FINALIZE")) {
    return mapWorkState("VERIFYING");
  }
  return mapSourceWorkState("AgentExecution", projection.executionState);
}

function update(state: string, interactionId: string): WorkspaceExecutionUpdate {
  return { workState: mapWorkState(state), interactionId, issue: null };
}

function resultProjection(projection: AgentResultProjection, status: string): WorkspaceResultProjection {
  const artifactCount = projection.result?.artifactRefs.length ?? 0;
  const warningCount = projection.result?.warnings.length ?? 0;
  return {
    status,
    businessSummary: projection.result?.businessSummary ?? null,
    artifactCount,
    warnings: warningCount > 0
      ? [`결과에 확인이 필요한 항목이 ${warningCount}건 있습니다.`]
      : [],
  };
}

function groundedSources(workflow: Record<string, any>): readonly WorkspaceSource[] {
  if (workflow.groundingRequested !== true) return [];
  const count = Number(workflow.admission?.retrieval?.evidence_count ?? 0);
  const status = workflow.state?.citationQuality?.quality?.citation_status;
  if (!Number.isInteger(count) || count < 1) return [];
  return [{
    id: `citations:${workflow.state?.interactionId ?? "current"}`,
    label: `검증된 근거 ${count}건`,
    detail: status === "VALIDATED" ? "인용 검증 완료" : "인용 상태 확인 필요",
  }];
}

export function issueFromStatus(status: unknown, retryable: boolean): WorkspaceExecutionIssue {
  const candidate = typeof status === "string" ? status.trim().slice(0, 120) : "";
  const code = /^[A-Z][A-Z0-9_.-]{0,119}$/.test(candidate)
    ? candidate
    : "WORKSPACE_EXECUTION_UNAVAILABLE";
  const message = code.includes("CANCEL")
    ? "요청이 취소되었습니다."
    : code.includes("APPROVAL")
      ? "승인 상태를 확인하지 못했습니다."
      : "요청을 완료하지 못했습니다.";
  return {
    message,
    retryable,
    nextAction: retryable
      ? "잠시 후 다시 시도해 주세요."
      : "승인 상태 또는 입력 내용을 확인해 주세요.",
    technicalCode: code,
  };
}

function uniqueTexts(values: readonly string[]) {
  return [...new Set(values.filter(value => typeof value === "string" && value.trim()).map(value => value.trim()))];
}

function statusCodeOf(error: unknown) {
  return error && typeof error === "object" && "statusCode" in error
    ? Number(error.statusCode)
    : null;
}

function assertNotAborted(signal: AbortSignal | null) {
  if (signal?.aborted) {
    const error = new Error("Workspace execution was cancelled.");
    Object.assign(error, { status: "WORKSPACE_EXECUTION_CANCELLED" });
    throw error;
  }
}

function waitForSeconds(seconds: number) {
  return new Promise<void>(resolve => globalThis.setTimeout(resolve, seconds * 1000));
}
