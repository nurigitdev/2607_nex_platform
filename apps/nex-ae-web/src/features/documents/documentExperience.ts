import { buildDocumentScope, buildRetrievalRequest } from "../../documentScope.js";
import { buildRetrievalQualityWarningSurface } from "../../retrievalQualityWarnings.js";
import {
  buildUploadFileMetadata,
  buildUploadSurfaceDraftFromFileMetadata,
} from "../../uploadSurface.js";
import type { DocumentLibraryItem } from "../../app/api/documentLibraryClientPort";

const projectUploadFileMetadata = buildUploadFileMetadata as unknown as (input: {
  readonly file: File;
}) => Readonly<Record<string, unknown>>;
const projectUploadDraft = buildUploadSurfaceDraftFromFileMetadata as unknown as (input: {
  readonly workspaceId: string;
  readonly fileMetadata: Readonly<Record<string, unknown>>;
  readonly ownerScope: {
    readonly tenantId: string;
    readonly ownerUserId: string;
    readonly uploadedByUserId: string;
  };
}) => Readonly<Record<string, unknown>>;

export interface DocumentProgressProjection {
  readonly status: string;
  readonly progressPercent: number;
  readonly terminal: boolean;
  readonly retrievalUsable: boolean;
  readonly retryable: boolean;
}

export interface RetrievalProjection {
  readonly status: string;
  readonly evidenceCount: number;
  readonly confidenceBucket: string;
  readonly warningVisible: boolean;
  readonly warningTitle: string;
  readonly warningMessage: string;
  readonly noAnswer: boolean;
}

export async function submitDocumentUpload({
  file,
  workspaceId,
  tenantId,
  ownerUserId,
  uploadClient,
  progressClient,
  onProgress = () => undefined,
  wait = waitForSeconds,
  maxPolls = 20,
}: {
  readonly file: File;
  readonly workspaceId: string;
  readonly tenantId: string;
  readonly ownerUserId: string;
  readonly uploadClient: any;
  readonly progressClient: any;
  readonly onProgress?: (progress: DocumentProgressProjection) => void;
  readonly wait?: (seconds: number) => Promise<void>;
  readonly maxPolls?: number;
}) {
  const metadata = projectUploadFileMetadata({ file });
  const draft = projectUploadDraft({
    workspaceId,
    fileMetadata: metadata,
    ownerScope: { tenantId, ownerUserId, uploadedByUserId: ownerUserId },
  });
  const submission = await uploadClient.submitUploadDraft(draft, { file });
  if (!submission.uploadHandoffId) {
    throw Object.assign(new Error("Upload handoff is unavailable."), {
      status: "UPLOAD_HANDOFF_MISSING",
    });
  }
  let last: DocumentProgressProjection | null = null;
  for (let attempt = 0; attempt < maxPolls; attempt += 1) {
    const progress = await progressClient.getProgress(submission.uploadHandoffId);
    last = Object.freeze({
      status: String(progress.status),
      progressPercent: Number(progress.progressPercent),
      terminal: progress.terminal === true,
      retrievalUsable: progress.vectorIndex?.retrievalUsable === true,
      retryable: progress.failure?.retryable === true,
    });
    onProgress(last);
    if (last.terminal) break;
    if (progressClient.clientMode !== "mock") await wait(1);
  }
  if (!last?.terminal) {
    throw Object.assign(new Error("Upload progress poll limit reached."), {
      status: "UPLOAD_PROGRESS_TIMEOUT",
      retryable: true,
    });
  }
  return Object.freeze({
    documentId: String(submission.documentId),
    dedupeStatus: String(submission.dedupeStatus),
    progress: last,
  });
}

export async function searchDocumentEvidence({
  query,
  conversationId,
  documents,
  selectedDocumentIds,
  retrievalClient,
}: {
  readonly query: string;
  readonly conversationId: string;
  readonly documents: readonly DocumentLibraryItem[];
  readonly selectedDocumentIds: readonly string[];
  readonly retrievalClient: any;
}): Promise<RetrievalProjection> {
  const scope = buildDocumentScope({ documents, selectedDocumentIds });
  const request = buildRetrievalRequest({
    userMessage: query,
    chatDocumentId: conversationId,
    documentScope: scope,
    grounded: true,
  });
  const result = await retrievalClient.submitRetrievalRequest(request);
  const warning = buildRetrievalQualityWarningSurface(result);
  return Object.freeze({
    status: String(result.cxStatus),
    evidenceCount: Number(result.evidenceCount || 0),
    confidenceBucket: String(result.confidenceBucket || "UNKNOWN"),
    warningVisible: warning.visible === true,
    warningTitle: String(warning.title),
    warningMessage: String(warning.message),
    noAnswer: result.cxStatus === "NO_ANSWER" || warning.recommended_action === "show_no_answer",
  });
}

function waitForSeconds(seconds: number) {
  return new Promise<void>(resolve => globalThis.setTimeout(resolve, seconds * 1000));
}
