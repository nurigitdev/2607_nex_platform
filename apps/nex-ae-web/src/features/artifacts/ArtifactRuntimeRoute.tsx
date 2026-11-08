import { useEffect, useRef, useState } from "react";

import type { WorkspaceIdentity } from "../../app/api/workspaceClientPort";
import { useOptionalInstalledRuntime } from "../../app/providers/RuntimeProvider";
import { useSession } from "../../app/providers/SessionProvider";
import { ArtifactPage, type ArtifactPageController } from "./ArtifactPage";
import {
  changeArtifactLifecycle,
  exportArtifact,
  loadArtifactDetail,
  loadArtifactLibrary,
  loadArtifactPreview,
  saveArtifactFile,
  type ArtifactDetailProjection,
  type ArtifactListItemProjection,
} from "./artifactExperience";

export function ArtifactRuntimeRoute() {
  const runtime = useOptionalInstalledRuntime();
  const { sessionState } = useSession();
  const [items, setItems] = useState<readonly ArtifactListItemProjection[]>([]);
  const [selected, setSelected] = useState<ArtifactDetailProjection | null>(null);
  const [preview, setPreview] = useState<{
    readonly fileName: string;
    readonly format: string;
    readonly text: string;
    readonly truncated: boolean;
  } | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
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
    const tenantId = sessionState.tenantRef?.id;
    const ownerUserId = sessionState.subjectRef?.id;
    if (!tenantId || !ownerUserId) {
      setError("로그인 정보를 확인할 수 없습니다. 다시 로그인해 주세요.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const current = await prepareWorkspace();
      setItems(await loadArtifactLibrary({
        client: runtime.clients.artifact,
        query: { tenantId, workspaceId: current.workspaceId, ownerUserId, limit: 50 },
      }));
    } catch (cause) {
      setError(messageFor(cause, "결과물 목록을 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [runtime, sessionState.subjectRef?.id, sessionState.tenantRef?.id]);

  async function selectArtifact(artifactId: string) {
    if (!runtime) return;
    setLoading(true);
    setError(null);
    setPreview(null);
    try {
      setSelected(await loadArtifactDetail({ client: runtime.clients.artifact, artifactId }));
    } catch (cause) {
      setError(messageFor(cause, "결과물 상세를 확인하지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }

  const controller: ArtifactPageController | null = runtime ? {
    refresh,
    select: selectArtifact,
    async preview(artifactId, fileId) {
      setLoading(true);
      setError(null);
      try {
        setPreview(await loadArtifactPreview({ client: runtime.clients.artifact, artifactId, fileId }));
      } catch (cause) {
        setError(messageFor(cause, "파일 미리보기를 표시하지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
    async download(fileId) {
      setLoading(true);
      setError(null);
      try {
        const saved = await saveArtifactFile({ client: runtime.clients.artifact, fileId });
        setFeedback(`${saved.fileName} 다운로드를 시작했습니다.`);
      } catch (cause) {
        setError(messageFor(cause, "파일을 다운로드하지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
    async lifecycle(artifactId, action) {
      setLoading(true);
      setError(null);
      try {
        await changeArtifactLifecycle({ client: runtime.clients.artifact, artifactId, action });
        setFeedback(actionFeedback(action));
        await refresh();
        await selectArtifact(artifactId);
      } catch (cause) {
        setError(messageFor(cause, "결과물 상태를 변경하지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
    async export(artifactId, formats) {
      setLoading(true);
      setError(null);
      try {
        const result = await exportArtifact({ client: runtime.clients.artifact, artifactId, formats });
        setFeedback(`${result.formats.join(", ")} 파일 생성을 요청했습니다.`);
      } catch (cause) {
        setError(messageFor(cause, "파일 생성을 요청하지 못했습니다."));
      } finally {
        setLoading(false);
      }
    },
  } : null;

  return <ArtifactPage
    controller={controller}
    items={items}
    selected={selected}
    preview={preview}
    feedback={feedback}
    loading={loading}
    error={error}
  />;
}

function actionFeedback(action: "ARCHIVE" | "RESTORE" | "MARK_DELETED") {
  return ({ ARCHIVE: "결과물을 보관했습니다.", RESTORE: "결과물을 복원했습니다.", MARK_DELETED: "결과물을 삭제했습니다." })[action];
}

function messageFor(error: unknown, fallback: string) {
  const status = error && typeof error === "object" && "status" in error ? String(error.status) : "";
  if (status === "HTTP_403" || status.includes("OWNER")) return "이 결과물을 볼 권한이 없습니다.";
  if (status === "HTTP_404") return "결과물을 찾을 수 없습니다.";
  return fallback;
}
