import {
  FileText,
  Paperclip,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  Button,
  Checkbox,
  EmptyState,
  IconButton,
  Select,
  StatusPill,
  Tabs,
  Textarea,
} from "../../design-system/components";
import { mapBusinessTerm } from "../../ux/terminology";
import { mapWorkState, type WorkStatePresentation } from "../../ux/workState";
import styles from "./WorkspacePage.module.css";

export interface WorkspaceAttachment {
  readonly id: string;
  readonly name: string;
  readonly size: number;
}

export interface WorkspaceSource {
  readonly id: string;
  readonly label: string;
  readonly detail?: string;
}

export interface WorkspaceMessage {
  readonly id: string;
  readonly role: "user" | "assistant";
  readonly content: string;
}

export interface WorkspaceDraft {
  readonly prompt: string;
  readonly useEvidence: boolean;
  readonly outputFormat: "answer" | "report" | "table";
  readonly attachments: readonly WorkspaceAttachment[];
}

export interface WorkspaceController {
  readonly submit: (draft: WorkspaceDraft) => Promise<void> | void;
  readonly cancel?: () => Promise<void> | void;
  readonly retry?: () => Promise<void> | void;
}

export interface WorkspacePageProps {
  readonly controller?: WorkspaceController | null;
  readonly workState?: WorkStatePresentation;
  readonly messages?: readonly WorkspaceMessage[];
  readonly sources?: readonly WorkspaceSource[];
  readonly recentTasks?: readonly string[];
}

const RECOMMENDED_WORK = Object.freeze([
  "업로드한 문서에서 핵심 내용을 정리해 주세요.",
  "근거와 함께 질문에 답해 주세요.",
  "업무 결과를 보고서 형식으로 작성해 주세요.",
]);

export function WorkspacePage({
  controller = null,
  workState = mapWorkState("IDLE"),
  messages = [],
  sources = [],
  recentTasks = [],
}: WorkspacePageProps) {
  const [prompt, setPrompt] = useState("");
  const [useEvidence, setUseEvidence] = useState(true);
  const [outputFormat, setOutputFormat] = useState<WorkspaceDraft["outputFormat"]>("answer");
  const [attachments, setAttachments] = useState<WorkspaceAttachment[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const workspaceTerm = mapBusinessTerm("WORKSPACE");

  const canSubmit = Boolean(controller && prompt.trim() && !submitting);
  const active = ["ACCEPTING", "PLANNING", "RUNNING", "RESUMING", "VERIFYING"].includes(
    workState.state,
  );
  const contextItems = useMemo(
    () => [
      {
        id: "progress",
        label: "진행",
        content: (
          <div className={styles.contextContent}>
            <StatusPill tone={workState.tone}>{workState.label}</StatusPill>
            <p>{progressDescription(workState)}</p>
          </div>
        ),
      },
      {
        id: "attachments",
        label: "첨부",
        count: attachments.length,
        content: (
          <ContextList
            empty="첨부한 파일이 없습니다."
            items={attachments.map(item => ({ id: item.id, label: item.name }))}
          />
        ),
      },
      {
        id: "sources",
        label: "출처",
        count: sources.length,
        content: <ContextList empty="연결된 출처가 없습니다." items={sources} />,
      },
    ],
    [attachments, sources, workState],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !controller) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await controller.submit({
        prompt: prompt.trim(),
        useEvidence,
        outputFormat,
        attachments,
      });
      setPrompt("");
      resizeTextarea();
    } catch {
      setActionError("요청을 전송하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []).map((file, index) => ({
      id: `${file.name}:${file.size}:${file.lastModified}:${index}`,
      name: file.name,
      size: file.size,
    }));
    setAttachments(current => deduplicateAttachments([...current, ...selected]));
    event.target.value = "";
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && canSubmit) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function resizeTextarea() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 176)}px`;
  }

  async function runControl(action: "cancel" | "retry") {
    const callback = controller?.[action];
    if (!callback) return;
    setActionError(null);
    try {
      await callback();
    } catch {
      setActionError(action === "cancel" ? "취소하지 못했습니다." : "재시도하지 못했습니다.");
    }
  }

  return (
    <section className={styles.page} aria-labelledby="workspace-title">
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>Interactive Agent</span>
          <h1 id="workspace-title">{workspaceTerm.label}</h1>
        </div>
        <StatusPill tone={workState.tone}>{workState.label}</StatusPill>
      </header>

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <section className={styles.conversation} aria-label="대화">
            {messages.length === 0 ? (
              <div className={styles.emptyWorkspace}>
                <EmptyState
                  icon={Sparkles}
                  title="무엇을 도와드릴까요?"
                  description="업무 내용을 자연어로 입력하면 필요한 흐름을 시작합니다."
                />
                <div className={styles.recommendations} aria-label="추천 업무">
                  {RECOMMENDED_WORK.map(item => (
                    <button key={item} type="button" onClick={() => setPrompt(item)}>{item}</button>
                  ))}
                </div>
                {recentTasks.length > 0 ? (
                  <section className={styles.recent} aria-labelledby="recent-title">
                    <h2 id="recent-title">최근 작업</h2>
                    <ul>{recentTasks.map(task => <li key={task}>{task}</li>)}</ul>
                  </section>
                ) : null}
              </div>
            ) : (
              <ol className={styles.messages}>
                {messages.map(item => (
                  <li key={item.id} className={item.role === "user" ? styles.userMessage : styles.agentMessage}>
                    <span>{item.role === "user" ? "나" : "IA"}</span>
                    <p>{item.content}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <form className={styles.composer} onSubmit={submit}>
            {attachments.length > 0 ? (
              <ul className={styles.attachmentChips} aria-label="첨부 파일">
                {attachments.map(item => (
                  <li key={item.id}>
                    <FileText aria-hidden="true" size={15} />
                    <span>{item.name}</span>
                    <IconButton
                      label={`${item.name} 제거`}
                      icon={<X aria-hidden="true" size={14} />}
                      size="sm"
                      onClick={() => setAttachments(current => current.filter(value => value.id !== item.id))}
                    />
                  </li>
                ))}
              </ul>
            ) : null}
            <Textarea
              ref={textareaRef}
              label="업무 요청"
              value={prompt}
              rows={2}
              placeholder="처리할 업무를 입력하세요"
              onChange={event => setPrompt(event.target.value)}
              onInput={resizeTextarea}
              onKeyDown={handleComposerKeyDown}
            />
            <div className={styles.composerToolbar}>
              <div className={styles.composerOptions}>
                <input
                  ref={fileInputRef}
                  className={styles.fileInput}
                  type="file"
                  multiple
                  onChange={selectFiles}
                  aria-label="파일 선택"
                />
                <IconButton
                  label="파일 첨부"
                  icon={<Paperclip aria-hidden="true" size={18} />}
                  onClick={() => fileInputRef.current?.click()}
                />
                <Checkbox
                  label="근거 사용"
                  checked={useEvidence}
                  onChange={event => setUseEvidence(event.target.checked)}
                />
                <Select
                  label="출력 형식"
                  value={outputFormat}
                  onChange={event => setOutputFormat(event.target.value as WorkspaceDraft["outputFormat"])}
                >
                  <option value="answer">답변</option>
                  <option value="report">보고서</option>
                  <option value="table">표</option>
                </Select>
              </div>
              <Button
                type="submit"
                disabled={!canSubmit}
                loading={submitting}
                leadingIcon={<Send aria-hidden="true" size={17} />}
              >
                보내기
              </Button>
            </div>
            {active && controller?.cancel ? (
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<Square aria-hidden="true" size={14} />}
                onClick={() => void runControl("cancel")}
              >
                처리 취소
              </Button>
            ) : null}
            {workState.state === "FAILED" && controller?.retry ? (
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<RotateCcw aria-hidden="true" size={15} />}
                onClick={() => void runControl("retry")}
              >
                다시 시도
              </Button>
            ) : null}
            {actionError ? <p className={styles.error} role="alert">{actionError}</p> : null}
          </form>
        </div>

        <aside className={styles.contextPanel} aria-label="작업 컨텍스트">
          <Tabs items={contextItems} defaultValue="progress" label="작업 컨텍스트" />
        </aside>
      </div>
    </section>
  );
}

function ContextList({
  items,
  empty,
}: {
  readonly items: readonly { id: string; label: string; detail?: string }[];
  readonly empty: string;
}) {
  if (items.length === 0) return <p className={styles.contextEmpty}>{empty}</p>;
  return (
    <ul className={styles.contextList}>
      {items.map(item => (
        <li key={item.id}>
          <strong>{item.label}</strong>
          {item.detail ? <span>{item.detail}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function progressDescription(state: WorkStatePresentation): string {
  if (state.state === "UNKNOWN") return "현재 상태를 확인하고 있습니다.";
  if (state.state === "WAITING_APPROVAL") return "승인이 완료되면 처리를 이어갑니다.";
  if (state.terminal) return "처리가 종료되었습니다.";
  return "현재 업무 상태를 기준으로 표시합니다.";
}

function deduplicateAttachments(values: readonly WorkspaceAttachment[]): WorkspaceAttachment[] {
  return [...new Map(values.map(item => [`${item.name}:${item.size}`, item])).values()];
}
