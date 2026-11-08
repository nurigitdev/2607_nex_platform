import {
  buildClientRegistrySummary,
  createAeWebClients,
} from "../../clientRegistry.js";

import type {
  ClientGatewaySummary,
  LegacyClientMode,
} from "../domain/runtime";
import type { ApprovalClientPort } from "./approvalClientPort";
import { createWorkspaceClient, type WorkspaceClientPort } from "./workspaceClientPort";

interface ClientGatewayOptions {
  readonly mode: LegacyClientMode;
  readonly baseUrl: string;
  readonly fetchImpl?: typeof globalThis.fetch;
}

export interface LegacyClientGateway {
  readonly workspace: WorkspaceClientPort;
  readonly approval: ApprovalClientPort;
  readonly artifact: unknown;
  readonly documentDetail: unknown;
  readonly upload: unknown;
  readonly uploadProgress: unknown;
  readonly voucherAttachment: unknown;
  readonly retrieval: unknown;
  readonly generationFeedback: unknown;
  readonly groundedGeneration: unknown;
  readonly interactionAgentResult: unknown;
  readonly repairedResponseReview: unknown;
  readonly repairedResponseDecision: unknown;
  readonly summary: ClientGatewaySummary;
}

export function createLegacyClientGateway({
  mode,
  baseUrl,
  fetchImpl,
}: ClientGatewayOptions): LegacyClientGateway {
  const createClients = createAeWebClients as unknown as (options: {
    mode: LegacyClientMode;
    baseUrl: string;
    fetchImpl?: typeof globalThis.fetch;
  }) => ReturnType<typeof createAeWebClients>;
  const registry = createClients({ mode, baseUrl, fetchImpl });
  const summary = buildClientRegistrySummary(registry);

  return Object.freeze({
    workspace: createWorkspaceClient({ mode, baseUrl, fetchImpl }),
    approval: registry.approvalClient as unknown as ApprovalClientPort,
    artifact: registry.artifactClient,
    documentDetail: registry.documentDetailClient,
    upload: registry.uploadClient,
    uploadProgress: registry.uploadProgressClient,
    voucherAttachment: registry.voucherAttachmentClient,
    retrieval: registry.retrievalClient,
    generationFeedback: registry.generationFeedbackClient,
    groundedGeneration: registry.groundedGenerationClient,
    interactionAgentResult: registry.interactionAgentResultClient,
    repairedResponseReview: registry.repairedResponseReviewClient,
    repairedResponseDecision: registry.repairedResponseDecisionClient,
    summary: Object.freeze({
      schemaVersion: summary.client_registry_schema_version,
      clientMode: summary.client_mode,
      baseUrl: summary.base_url,
      clients: Object.freeze({ workspace: mode, ...summary.clients }),
      metadata: Object.freeze({ ...summary.metadata }),
    }),
  });
}
