import { FileSearch, FileUp, Files, RefreshCw } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent } from "react";

import type { DocumentLibraryItem } from "../../app/api/documentLibraryClientPort";
import {
  Button,
  Checkbox,
  EmptyState,
  Input,
  StatusPill,
  Tabs,
} from "../../design-system/components";
import type {
  DocumentProgressProjection,
  RetrievalProjection,
} from "./documentExperience";
import styles from "./DocumentWorkspacePage.module.css";

export interface DocumentDetailProjection {
  readonly documentId: string;
  readonly filename: string;
  readonly processingStatus: string;
  readonly extractionStatus: string;
  readonly summaryStatus: string;
  readonly confidenceBucket: string;
}

export interface DocumentWorkspaceController {
  readonly refresh: () => Promise<void> | void;
  readonly upload: (file: File) => Promise<void> | void;
  readonly openDetail: (documentId: string) => Promise<void> | void;
  readonly search: (query: string, selectedDocumentIds: readonly string[]) => Promise<void> | void;
}

export function DocumentWorkspacePage({
  controller = null,
  initialTab = "documents",
  documents = [],
  detail = null,
  progress = null,
  retrieval = null,
  loading = false,
  error = null,
  duplicate = false,
}: {
  readonly controller?: DocumentWorkspaceController | null;
  readonly initialTab?: "documents" | "upload" | "retrieval";
  readonly documents?: readonly DocumentLibraryItem[];
  readonly detail?: DocumentDetailProjection | null;
  readonly progress?: DocumentProgressProjection | null;
  readonly retrieval?: RetrievalProjection | null;
  readonly loading?: boolean;
  readonly error?: string | null;
  readonly duplicate?: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (file && controller) await controller.upload(file);
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (query.trim() && selectedIds.length > 0 && controller) {
      await controller.search(query.trim(), selectedIds);
    }
  }

  const documentList = documents.length === 0 ? (
    <EmptyState
      icon={Files}
      title="등록된 문서가 없습니다"
      description="파일을 첨부하면 처리 상태와 요약을 여기에서 확인할 수 있습니다."
    />
  ) : (
    <ul className={styles.documentList} aria-label="내 문서">
      {documents.map(item => (
        <li key={item.documentId}>
          <div>
            <strong>{item.filename}</strong>
            <span>{formatBytes(item.sizeBytes)} · {item.contentType}</span>
            {item.summaryPreview ? <p>{item.summaryPreview}</p> : null}
          </div>
          <div className={styles.documentActions}>
            <StatusPill tone={item.summaryAvailable ? "success" : "warning"}>
              {item.summaryAvailable ? "요약 준비됨" : "처리 중"}
            </StatusPill>
            <Button variant="secondary" size="sm" onClick={() => void controller?.openDetail(item.documentId)}>
              상세 보기
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );

  const tabs = [
    {
      id: "documents",
      label: "내 문서",
      count: documents.length,
      content: (
        <div className={styles.tabPanel}>
          <div className={styles.toolbar}>
            <p>내가 첨부한 문서와 처리 상태를 확인합니다.</p>
            <Button
              variant="ghost"
              size="sm"
              leadingIcon={<RefreshCw aria-hidden="true" size={16} />}
              onClick={() => void controller?.refresh()}
            >
              새로고침
            </Button>
          </div>
          {documentList}
          {detail ? (
            <section className={styles.detail} aria-labelledby="document-detail-title">
              <h2 id="document-detail-title">문서 상세</h2>
              <dl>
                <div><dt>파일</dt><dd>{detail.filename}</dd></div>
                <div><dt>처리</dt><dd>{humanStatus(detail.processingStatus)}</dd></div>
                <div><dt>텍스트 추출</dt><dd>{humanStatus(detail.extractionStatus)}</dd></div>
                <div><dt>요약</dt><dd>{humanStatus(detail.summaryStatus)}</dd></div>
              </dl>
            </section>
          ) : null}
        </div>
      ),
    },
    {
      id: "upload",
      label: "파일 첨부",
      content: (
        <form className={styles.tabPanel} onSubmit={event => void upload(event)}>
          <div className={styles.filePicker}>
            <FileUp aria-hidden="true" size={28} />
            <label htmlFor="document-file">업무에 사용할 파일 선택</label>
            <input id="document-file" type="file" onChange={selectFile} />
            <span>{file ? `${file.name} · ${formatBytes(file.size)}` : "선택한 파일이 없습니다."}</span>
          </div>
          <Button type="submit" disabled={!file || !controller} loading={loading}>파일 첨부</Button>
          {duplicate ? <p className={styles.notice} role="status">이미 등록된 파일입니다. 기존 문서를 사용합니다.</p> : null}
          {progress ? (
            <div className={styles.progress} role="status" aria-live="polite">
              <span>문서 처리 {progress.progressPercent}%</span>
              <progress max={100} value={progress.progressPercent} />
              <strong>{progress.retrievalUsable ? "문서 근거로 사용할 수 있습니다." : humanStatus(progress.status)}</strong>
            </div>
          ) : null}
        </form>
      ),
    },
    {
      id: "retrieval",
      label: "문서 근거 찾기",
      content: (
        <form className={styles.tabPanel} onSubmit={event => void search(event)}>
          <fieldset className={styles.scope}>
            <legend>검색할 문서</legend>
            {documents.length === 0 ? <p>먼저 파일을 첨부해 주세요.</p> : documents.map(item => (
              <Checkbox
                key={item.documentId}
                label={item.filename}
                checked={selectedIds.includes(item.documentId)}
                onChange={event => setSelectedIds(current => event.target.checked
                  ? [...current, item.documentId]
                  : current.filter(id => id !== item.documentId))}
              />
            ))}
          </fieldset>
          <Input label="찾을 내용" value={query} onChange={event => setQuery(event.target.value)} />
          <Button type="submit" disabled={!query.trim() || selectedIds.length === 0 || !controller} loading={loading}>
            근거 찾기
          </Button>
          {retrieval ? <RetrievalResult result={retrieval} /> : null}
        </form>
      ),
    },
  ];

  return (
    <section className={styles.page} aria-labelledby="documents-title">
      <header>
        <div>
          <span>Knowledge Workspace</span>
          <h1 id="documents-title">문서</h1>
        </div>
        <StatusPill tone={loading ? "info" : "neutral"}>{loading ? "처리 중" : "준비됨"}</StatusPill>
      </header>
      {error ? <div className={styles.error} role="alert">{error}</div> : null}
      <Tabs items={tabs} defaultValue={initialTab} label="문서 작업" />
    </section>
  );
}

function RetrievalResult({ result }: { readonly result: RetrievalProjection }) {
  return (
    <section className={styles.retrievalResult} aria-labelledby="retrieval-result-title">
      <FileSearch aria-hidden="true" size={22} />
      <div>
        <h2 id="retrieval-result-title">사용한 출처</h2>
        <p>{result.noAnswer ? "선택한 문서에서 충분한 근거를 찾지 못했습니다." : `근거 ${result.evidenceCount}건을 찾았습니다.`}</p>
        <span>신뢰 상태: {humanStatus(result.confidenceBucket)}</span>
        {result.warningVisible ? <strong>{result.warningTitle}: {result.warningMessage}</strong> : null}
      </div>
    </section>
  );
}

function humanStatus(status: string) {
  return ({
    READY: "준비됨",
    INDEX_READY: "검색 준비됨",
    SUCCEEDED: "완료",
    PROCESSING: "처리 중",
    QUEUED: "대기 중",
    NOT_READY: "준비 중",
    NO_ANSWER: "근거 부족",
    FAILED: "실패",
  } as Record<string, string>)[status] ?? "확인 필요";
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
