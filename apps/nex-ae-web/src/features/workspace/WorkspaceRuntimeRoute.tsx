import { useEffect, useMemo, useRef, useState } from "react";

import { useOptionalInstalledRuntime } from "../../app/providers/RuntimeProvider";
import { useSession } from "../../app/providers/SessionProvider";
import { buildGenerationFeedbackRequest } from "../../generationFeedback.js";
import { buildRepairedResponseDecisionRequest } from "../../repairedResponseDecisionClient.js";
import {
  markRepairedResponseDecisionFailed,
  markRepairedResponseDecisionRecorded,
  markRepairedResponseDecisionSubmitting,
} from "../../repairedResponseDecisionState.js";
import { mapWorkState, type WorkStatePresentation } from "../../ux/workState";
import type { WorkspaceResultProjection } from "./BusinessResultCard";
import type { GenerationFeedbackState, GenerationFeedbackValue } from "./ResponseQualityActions";
import {
  executeWorkspaceDraft,
  issueFromStatus,
  type GroundedGenerationClientPort,
  type InteractionAgentResultPort,
  type WorkspaceExecutionIssue,
  type WorkspaceExecutionUpdate,
} from "./workspaceExecution";
import {
  WorkspacePage,
  type WorkspaceController,
  type WorkspaceDraft,
  type WorkspaceMessage,
  type WorkspaceSource,
} from "./WorkspacePage";

const createGenerationFeedbackRequest = buildGenerationFeedbackRequest as unknown as (input: {
  readonly tenantId: string;
  readonly userId: string;
  readonly interactionId: string;
  readonly chatDocumentId: string;
  readonly feedbackValue: GenerationFeedbackValue;
  readonly feedbackReasons: readonly string[];
}) => any;

const createRepairedResponseDecisionRequest = buildRepairedResponseDecisionRequest as unknown as (input: {
  readonly reviewSurface: any;
  readonly action: "accept_repair" | "keep_original";
  readonly submittedVia: "chat_review";
  readonly actorClaimsRef: {
    readonly actor_type: "user";
    readonly actor_id: string;
    readonly tenant_id: string;
  };
}) => any;

export function WorkspaceRuntimeRoute() {
  const runtime = useOptionalInstalledRuntime();
  if (!runtime) return <WorkspacePage />;
  return <InstalledWorkspaceRuntime runtime={runtime} />;
}

export function InstalledWorkspaceRuntime({
  runtime,
}: {
  readonly runtime: NonNullable<ReturnType<typeof useOptionalInstalledRuntime>>;
}) {
  const { sessionState } = useSession();
  const [workState, setWorkState] = useState(() => mapWorkState("IDLE"));
  const [progressHistory, setProgressHistory] = useState<WorkStatePresentation[]>([]);
  const [messages, setMessages] = useState<WorkspaceMessage[]>([]);
  const [sources, setSources] = useState<readonly WorkspaceSource[]>([]);
  const [result, setResult] = useState<WorkspaceResultProjection | null>(null);
  const [issue, setIssue] = useState<WorkspaceExecutionIssue | null>(null);
  const [feedback, setFeedback] = useState<GenerationFeedbackState | null>(null);
  const [repairedResponseReview, setRepairedResponseReview] = useState<any | null>(null);
  const workspacePromise = useRef<ReturnType<typeof runtime.clients.workspace.createWorkspace> | null>(null);
  const activeExecution = useRef<{ abort: AbortController; interactionId: string | null } | null>(null);
  const lastDraft = useRef<WorkspaceDraft | null>(null);

  useEffect(() => () => activeExecution.current?.abort.abort(), []);

  function applyUpdate(update: WorkspaceExecutionUpdate) {
    setWorkState(update.workState);
    setProgressHistory(current => appendActualState(current, update.workState));
    if (update.message) {
      setMessages(current => upsertMessage(current, update.message!));
    }
    if (update.sources) setSources(update.sources);
    if ("result" in update) setResult(update.result ?? null);
    if ("issue" in update) setIssue(update.issue ?? null);
    if ("repairedResponseReview" in update) {
      setRepairedResponseReview(update.repairedResponseReview ?? null);
    }
    if (activeExecution.current && update.interactionId) {
      activeExecution.current.interactionId = update.interactionId;
    }
  }

  async function start(draft: WorkspaceDraft) {
    activeExecution.current?.abort.abort();
    const abort = new AbortController();
    activeExecution.current = { abort, interactionId: null };
    lastDraft.current = draft;
    setMessages(current => [...current, {
      id: `user:${Date.now()}`,
      role: "user",
      content: draft.prompt,
    }]);
    setProgressHistory([]);
    setResult(null);
    setSources([]);
    setIssue(null);
    setFeedback(null);
    setRepairedResponseReview(null);
    setWorkState(mapWorkState("ACCEPTING"));
    try {
      workspacePromise.current ??= runtime.clients.workspace.createWorkspace({
        title: "내 업무 공간",
        locale: "ko-KR",
      });
      const workspace = await workspacePromise.current;
      const outcome = await executeWorkspaceDraft({
        draft,
        workspaceId: workspace.workspaceId,
        conversationId: workspace.conversationId,
        sourceDocumentIds: [],
        generationClient: runtime.clients.groundedGeneration as GroundedGenerationClientPort,
        interactionResultClient: runtime.clients.interactionAgentResult as InteractionAgentResultPort,
        repairedResponseReviewClient: runtime.clients.repairedResponseReview,
        onUpdate: applyUpdate,
        signal: abort.signal,
      });
      if (outcome.interactionId && outcome.message && outcome.status !== "ACTIVE") {
        setFeedback({ status: "READY", value: null });
      }
    } catch (error) {
      if (abort.signal.aborted) {
        applyUpdate({
          workState: mapWorkState("CANCELLED"),
          interactionId: activeExecution.current?.interactionId ?? null,
          issue: null,
        });
      } else {
        applyUpdate({
          workState: mapWorkState("FAILED"),
          interactionId: activeExecution.current?.interactionId ?? null,
          issue: issueFromStatus(statusOf(error), isRetryable(error)),
        });
      }
    }
  }

  const controller = useMemo<WorkspaceController>(() => ({
    submit(draft) {
      void start(draft);
    },
    async cancel() {
      const execution = activeExecution.current;
      execution?.abort.abort();
      if (execution?.interactionId) {
        const client = runtime.clients.groundedGeneration as GroundedGenerationClientPort;
        await client.cancelInteraction?.(execution.interactionId);
      }
      setWorkState(mapWorkState("CANCELLED"));
      setProgressHistory(current => appendActualState(current, mapWorkState("CANCELLED")));
      setIssue(null);
    },
    retry() {
      if (lastDraft.current) void start(lastDraft.current);
    },
    async submitFeedback(value: GenerationFeedbackValue) {
      const interactionId = activeExecution.current?.interactionId;
      const tenantId = sessionState.tenantRef?.id;
      const userId = sessionState.subjectRef?.id;
      const currentWorkspace = workspacePromise.current ? await workspacePromise.current : null;
      if (!interactionId || !tenantId || !userId || !currentWorkspace) return;
      setFeedback({ status: "SUBMITTING", value });
      try {
        const request = createGenerationFeedbackRequest({
          tenantId,
          userId,
          interactionId,
          chatDocumentId: currentWorkspace.conversationId,
          feedbackValue: value,
          feedbackReasons: value === "positive" ? ["helpful"] : value === "negative" ? ["not_helpful"] : [],
        });
        await (runtime.clients.generationFeedback as any).submitGenerationFeedback(request);
        setFeedback({ status: "RECORDED", value });
      } catch {
        setFeedback({ status: "FAILED", value });
      }
    },
    async submitRepairedDecision(action) {
      const surface = repairedResponseReview;
      const actorId = sessionState.subjectRef?.id;
      const tenantId = sessionState.tenantRef?.id;
      if (!surface || !actorId || !tenantId) return;
      const client = runtime.clients.repairedResponseDecision as any;
      const submitting = markRepairedResponseDecisionSubmitting(
        surface.decisionState,
        action,
        client.clientMode,
      );
      setRepairedResponseReview({ ...surface, decisionState: submitting });
      try {
        const request = createRepairedResponseDecisionRequest({
          reviewSurface: surface,
          action,
          submittedVia: "chat_review",
          actorClaimsRef: { actor_type: "user", actor_id: actorId, tenant_id: tenantId },
        });
        const result = await client.submitRepairedResponseDecision(request);
        setRepairedResponseReview({
          ...surface,
          decisionState: markRepairedResponseDecisionRecorded(submitting, result),
        });
      } catch (error) {
        setRepairedResponseReview({
          ...surface,
          decisionState: markRepairedResponseDecisionFailed(submitting, action, error, client.clientMode),
        });
      }
    },
  }), [repairedResponseReview, runtime, sessionState.subjectRef?.id, sessionState.tenantRef?.id]);

  return (
    <WorkspacePage
      controller={controller}
      workState={workState}
      progressHistory={progressHistory}
      messages={messages}
      sources={sources}
      result={result}
      issue={issue}
      feedback={feedback}
      repairedResponseReview={repairedResponseReview}
    />
  );
}

function appendActualState(
  current: readonly WorkStatePresentation[],
  next: WorkStatePresentation,
) {
  if (next.state === "IDLE" || next.state === "UNKNOWN") return [...current];
  if (current.at(-1)?.state === next.state) return [...current];
  return [...current, next];
}

function upsertMessage(current: readonly WorkspaceMessage[], next: WorkspaceMessage) {
  const index = current.findIndex(item => item.id === next.id);
  if (index < 0) return [...current, next];
  return current.map((item, itemIndex) => itemIndex === index ? next : item);
}

function statusOf(error: unknown) {
  return error && typeof error === "object" && "status" in error
    ? String(error.status)
    : "WORKSPACE_EXECUTION_UNAVAILABLE";
}

function isRetryable(error: unknown) {
  return Boolean(error && typeof error === "object" && "retryable" in error && error.retryable);
}
