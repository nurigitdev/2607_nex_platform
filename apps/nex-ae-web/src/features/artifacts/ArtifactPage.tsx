import { Archive, Download, Eye, FileOutput, History, RotateCcw, Trash2 } from "lucide-react";

import { Button, EmptyState, StatusPill } from "../../design-system/components";
import type {
  ArtifactDetailProjection,
  ArtifactListItemProjection,
} from "./artifactExperience";
import styles from "./ArtifactPage.module.css";

export interface ArtifactPageController {
  readonly refresh: () => Promise<void> | void;
  readonly select: (artifactId: string) => Promise<void> | void;
  readonly preview: (artifactId: string, fileId: string) => Promise<void> | void;
  readonly download: (fileId: string) => Promise<void> | void;
  readonly lifecycle: (artifactId: string, action: "ARCHIVE" | "RESTORE" | "MARK_DELETED") => Promise<void> | void;
  readonly export: (artifactId: string, formats: readonly string[]) => Promise<void> | void;
}

export function ArtifactPage({
  controller = null,
  items = [],
  selected = null,
  preview = null,
  feedback = null,
  loading = false,
  error = null,
}: {
  readonly controller?: ArtifactPageController | null;
  readonly items?: readonly ArtifactListItemProjection[];
  readonly selected?: ArtifactDetailProjection | null;
  readonly preview?: { readonly fileName: string; readonly format: string; readonly text: string; readonly truncated: boolean } | null;
  readonly feedback?: string | null;
  readonly loading?: boolean;
  readonly error?: string | null;
}) {
  return (
    <section className={styles.page} aria-labelledby="artifact-title">
      <header>
        <div><span>Generated Outputs</span><h1 id="artifact-title">결과물</h1></div>
        <div className={styles.headerActions}>
          <StatusPill tone={loading ? "info" : "neutral"}>{loading ? "처리 중" : `${items.length}건`}</StatusPill>
          <Button variant="ghost" size="sm" onClick={() => void controller?.refresh()}>새로고침</Button>
        </div>
      </header>
      {error ? <div className={styles.error} role="alert">{error}</div> : null}
      {feedback ? <div className={styles.feedback} role="status">{feedback}</div> : null}
      <div className={styles.layout}>
        <section className={styles.library} aria-labelledby="artifact-library-title">
          <h2 id="artifact-library-title">내 결과물</h2>
          {items.length === 0 ? (
            <EmptyState icon={FileOutput} title="생성된 결과물이 없습니다" description="업무 결과로 생성된 문서와 파일이 여기에 표시됩니다." />
          ) : (
            <ul>
              {items.map(item => (
                <li key={item.artifactId} className={selected?.artifactId === item.artifactId ? styles.selected : undefined}>
                  <button type="button" onClick={() => void controller?.select(item.artifactId)}>
                    <strong>{item.displayTitle}</strong>
                    <span>{formatLabel(item.primaryFormat)} · 버전 {item.versionCount}개</span>
                    <small>근거 {item.evidenceRefCount}건 · {statusLabel(item.artifactStatus)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className={styles.detail} aria-labelledby="artifact-detail-title">
          <h2 id="artifact-detail-title">결과물 상세</h2>
          {!selected ? (
            <EmptyState icon={FileOutput} title="결과물을 선택해 주세요" description="미리보기, 다운로드와 버전을 확인할 수 있습니다." />
          ) : (
            <>
              <div className={styles.detailHeader}>
                <div><strong>{selected.displayTitle}</strong><span>{statusLabel(selected.artifactStatus)}</span></div>
                <LifecycleActions artifact={selected} controller={controller} />
              </div>
              <div className={styles.exportActions} aria-label="내보내기">
                <Button variant="secondary" size="sm" onClick={() => void controller?.export(selected.artifactId, ["DOCX"])}>DOCX 만들기</Button>
                <Button variant="secondary" size="sm" onClick={() => void controller?.export(selected.artifactId, ["PDF"])}>PDF 만들기</Button>
              </div>
              <section className={styles.files} aria-labelledby="artifact-files-title">
                <h3 id="artifact-files-title">파일</h3>
                <ul>{selected.files.map(file => (
                  <li key={file.artifactFileId}>
                    <span>{file.fileName} · {formatLabel(file.format)}</span>
                    <div>
                      <Button variant="ghost" size="sm" disabled={!file.previewAvailable} leadingIcon={<Eye aria-hidden="true" size={16} />} onClick={() => void controller?.preview(selected.artifactId, file.artifactFileId)}>미리보기</Button>
                      <Button variant="ghost" size="sm" disabled={!file.downloadAvailable} leadingIcon={<Download aria-hidden="true" size={16} />} onClick={() => void controller?.download(file.artifactFileId)}>다운로드</Button>
                    </div>
                  </li>
                ))}</ul>
              </section>
              <section className={styles.versions} aria-labelledby="artifact-versions-title">
                <h3 id="artifact-versions-title"><History aria-hidden="true" size={17} /> 버전</h3>
                <ol>{selected.versions.map(version => (
                  <li key={version.id}><span>버전 {version.number ?? "-"}</span><span>{version.formats.map(formatLabel).join(", ")}</span>{version.current ? <strong>현재</strong> : null}</li>
                ))}</ol>
              </section>
              {preview ? (
                <section className={styles.preview} aria-labelledby="artifact-preview-title">
                  <h3 id="artifact-preview-title">{preview.fileName} 미리보기</h3>
                  <pre>{preview.text}</pre>
                  {preview.truncated ? <p>일부 내용만 표시합니다.</p> : null}
                </section>
              ) : null}
            </>
          )}
        </section>
      </div>
    </section>
  );
}

function LifecycleActions({ artifact, controller }: { readonly artifact: ArtifactDetailProjection; readonly controller: ArtifactPageController | null }) {
  const archived = artifact.artifactStatus === "ARCHIVED" || artifact.artifactStatus === "DELETED";
  return <div className={styles.lifecycle}>
    {archived ? (
      <Button variant="secondary" size="sm" leadingIcon={<RotateCcw aria-hidden="true" size={16} />} onClick={() => void controller?.lifecycle(artifact.artifactId, "RESTORE")}>복원</Button>
    ) : (
      <Button variant="secondary" size="sm" leadingIcon={<Archive aria-hidden="true" size={16} />} onClick={() => void controller?.lifecycle(artifact.artifactId, "ARCHIVE")}>보관</Button>
    )}
    <Button variant="danger" size="sm" leadingIcon={<Trash2 aria-hidden="true" size={16} />} disabled={artifact.artifactStatus === "DELETED"} onClick={() => void controller?.lifecycle(artifact.artifactId, "MARK_DELETED")}>삭제</Button>
  </div>;
}

function statusLabel(status: string) {
  return ({ READY: "준비됨", DRAFT: "작성 중", RENDERING: "생성 중", FAILED: "실패", ARCHIVED: "보관됨", DELETED: "삭제됨" } as Record<string, string>)[status] ?? "상태 확인 필요";
}

function formatLabel(format: string) {
  return format === "HTML_PREVIEW" ? "웹 미리보기" : format;
}
