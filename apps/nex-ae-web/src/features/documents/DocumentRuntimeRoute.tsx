import { useEffect, useRef, useState } from "react";

import type { DocumentLibraryItem } from "../../app/api/documentLibraryClientPort";
import type { WorkspaceIdentity } from "../../app/api/workspaceClientPort";
import { useOptionalInstalledRuntime } from "../../app/providers/RuntimeProvider";
import { useSession } from "../../app/providers/SessionProvider";
import {
  DocumentWorkspacePage,
  type DocumentDetailProjection,
  type DocumentWorkspaceController,
} from "./DocumentWorkspacePage";
import {
  searchDocumentEvidence,
  submitDocumentUpload,
  type DocumentProgressProjection,
  type RetrievalProjection,
} from "./documentExperience";

export function DocumentRuntimeRoute({
  initialTab = "documents",
}: {
  readonly initialTab?: "documents" | "upload" | "retrieval";
}) {
  const runtime = useOptionalInstalledRuntime();
  const { sessionState } = useSession();
  const [documents, setDocuments] = useState<readonly DocumentLibraryItem[]>([]);
  const [detail, setDetail] = useState<DocumentDetailProjection | null>(null);
  const [progress, setProgress] = useState<DocumentProgressProjection | null>(null);
  const [retrieval, setRetrieval] = useState<RetrievalProjection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const workspace = useRef<WorkspaceIdentity | null>(null);

  async function prepareWorkspace() {
    if (!runtime) throw new Error("Installed runtime is unavailable.");
    workspace.current ??= await runtime.clients.workspace.createWorkspace({
      title: "내 업무 공간",
      locale: "ko-KR",
    });
    return workspace.current;
  }

  async function refresh() {
    if (!runtime) return;
    setLoading(true);
    setError(null);
    try {
      const current = await prepareWorkspace();
      setDocuments(await runtime.clients.documentLibrary.listWorkspaceDocuments(current.workspaceId));
    } catch (cause) {
      setError(messageFor(cause, "문서 목록을 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [runtime]);

  const controller: DocumentWorkspaceController | null = runtime ? {
    refresh,
    async upload(file) {
      const tenantId = sessionState.tenantRef?.id;
      const ownerUserId = sessionState.subjectRef?.id;
      if (!tenantId || !ownerUserId) {
        setError("로그인 정보를 확인할 수 없습니다. 다시 로그인해 주세요.");
        return;
      }
      setLoading(true);
      setError(null);
      setDuplicate(false);
      setProgress(null);
      try {
        const current = await prepareWorkspace();
        const outcome = await submitDocumentUpload({
          file,
          workspaceId: current.workspaceId,
          tenantId,
          ownerUserId,
          uploadClient: runtime.clients.upload,
          progressClient: runtime.clients.uploadProgress,
          onProgress: setProgress,
        });
        setDuplicate(outcome.dedupeStatus !== "CREATED");
        setDocuments(await runtime.clients.documentLibrary.listWorkspaceDocuments(current.workspaceId));
      } catch (cause) {
        setError(messageFor(cause, "파일을 첨부하지 못했습니다. 다시 시도해 주세요."));
      } finally {
        setLoading(false);
      }
    },
    async openDetail(documentId) {
      setLoading(true);
      setError(null);
      try {
        const value = await (runtime.clients.documentDetail as any).getDocumentDetail(documentId);
        setDetail({
          documentId: String(value.documentId),
          filename: String(value.filename),
          processingStatus: String(value.processingStatus),
          extractionStatus: String(value.extractionStatus),
          summaryStatus: String(value.summaryStatus),
          confidenceBucket: String(value.confidenceBucket),
        });
      } catch (cause) {
        setError(messageFor(cause, "문서 상세를 확인하지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
    async search(query, selectedDocumentIds) {
      setLoading(true);
      setError(null);
      setRetrieval(null);
      try {
        const current = await prepareWorkspace();
        setRetrieval(await searchDocumentEvidence({
          query,
          conversationId: current.conversationId,
          documents,
          selectedDocumentIds,
          retrievalClient: runtime.clients.retrieval,
        }));
      } catch (cause) {
        setError(messageFor(cause, "문서 근거를 찾지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
  } : null;

  return (
    <DocumentWorkspacePage
      controller={controller}
      initialTab={initialTab}
      documents={documents}
      detail={detail}
      progress={progress}
      retrieval={retrieval}
      loading={loading}
      error={error}
      duplicate={duplicate}
    />
  );
}

function messageFor(error: unknown, fallback: string) {
  const status = error && typeof error === "object" && "status" in error
    ? String(error.status)
    : "";
  if (status.includes("OWNER") || status === "HTTP_403") {
    return "이 문서를 볼 권한이 없습니다.";
  }
  return fallback;
}
