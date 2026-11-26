import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Plus, RefreshCw, Save, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { BusinessProposalClientPort } from "../../app/api/businessProposalClientPort";
import type {
  BusinessVoucherClientPort,
  BusinessVoucherDraft,
  BusinessVoucherLine,
} from "../../app/api/businessVoucherClientPort";
import { Button, EmptyState, Input, Select } from "../../design-system/components";
import { BusinessJourney } from "../business/BusinessJourney";
import styles from "./VoucherDraftPage.module.css";

export function VoucherDraftPage({
  client,
  proposalClient,
}: {
  readonly client: BusinessVoucherClientPort | null;
  readonly proposalClient: BusinessProposalClientPort | null;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const drafts = useQuery({
    queryKey: ["business-voucher-drafts", client?.clientMode],
    queryFn: () => client!.list(),
    enabled: client !== null,
  });
  const approved = useQuery({
    queryKey: ["approved-business-proposals", proposalClient?.clientMode],
    queryFn: () => proposalClient!.list(["APPROVED"]),
    enabled: proposalClient !== null,
  });
  const items = drafts.data ?? [];

  useEffect(() => {
    if (!items.length) setSelectedId(null);
    else if (!selectedId || !items.some(item => item.candidate_id === selectedId)) {
      setSelectedId(items[0].candidate_id);
    }
  }, [items, selectedId]);

  return <section className={styles.page} aria-labelledby="voucher-draft-title">
    <header className={styles.header}>
      <div><p>회계 업무</p><h1 id="voucher-draft-title">전표 검토</h1></div>
      <div className={styles.headerActions}>
        <Button variant="secondary" size="sm" leadingIcon={<RefreshCw aria-hidden="true" size={16} />} onClick={() => void drafts.refetch()}>새로고침</Button>
        <Button size="sm" leadingIcon={<Plus aria-hidden="true" size={16} />} onClick={() => setCreating(true)}>전표 초안</Button>
      </div>
    </header>
    {!client ? <p className={styles.notice} role="alert">전표 서비스를 연결할 수 없습니다.</p>
      : creating ? <CreateDraft
        client={client}
        proposals={approved.data ?? []}
        onCancel={() => setCreating(false)}
        onCreated={async draft => {
          setCreating(false); setSelectedId(draft.candidate_id); await drafts.refetch();
        }}
      />
      : drafts.isPending ? <p className={styles.notice}>전표를 불러오는 중입니다.</p>
      : items.length === 0 ? <EmptyState title="전표 초안이 없습니다" description="승인된 품의서를 선택해 실제 지출 증빙 기반 전표를 작성할 수 있습니다." />
      : <div className={styles.workspace}>
        <aside className={styles.list} aria-label="전표 초안 목록"><h2>내 전표 <span>{items.length}건</span></h2><ul>
          {items.map(item => <li key={item.candidate_id}><button type="button" data-candidate-id={item.candidate_id} aria-pressed={item.candidate_id === selectedId} onClick={() => setSelectedId(item.candidate_id)}>
            <strong>{item.project_code}</strong><span>{stateLabel(item.state)} · revision {item.current_revision_no}</span><small>{Number(item.balance.debit).toLocaleString("ko-KR")} {item.transaction_currency}</small>
          </button></li>)}
        </ul></aside>
        {selectedId ? <DraftEditor key={selectedId} client={client} draft={items.find(item => item.candidate_id === selectedId)!} onChanged={async () => { await drafts.refetch(); }} /> : null}
      </div>}
  </section>;
}

function DraftEditor({ client, draft, onChanged }: {
  readonly client: BusinessVoucherClientPort;
  readonly draft: BusinessVoucherDraft;
  readonly onChanged: () => Promise<void>;
}) {
  const [recognitionDate, setRecognitionDate] = useState(draft.recognition_date);
  const [lines, setLines] = useState(() => draft.lines.map(line => ({ ...line })));
  const [pending, setPending] = useState<"save" | "validate" | "submit" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const editable = draft.state === "DRAFT" || draft.state === "RETURNED_FOR_CORRECTION";
  const balance = useMemo(() => lines.reduce((sum, line) => ({
    debit: sum.debit + Number(line.debit_original || 0),
    credit: sum.credit + Number(line.credit_original || 0),
  }), { debit: 0, credit: 0 }), [lines]);
  const balanced = balance.debit > 0 && balance.debit === balance.credit;

  function updateLine(index: number, field: keyof BusinessVoucherLine, value: string) {
    setLines(current => current.map((line, lineIndex) => lineIndex === index ? { ...line, [field]: value } : line));
  }
  async function run(kind: "save" | "validate" | "submit") {
    setPending(kind); setMessage(null);
    try {
      if (kind === "save") await client.revise(draft, { recognitionDate, lines });
      else if (kind === "validate") await client.validate(draft);
      else await client.submit(draft);
      setMessage(kind === "save" ? "새 revision으로 저장했습니다." : kind === "validate" ? "현재 revision 검증을 통과했습니다." : "회계 검토를 요청했습니다.");
      setConfirmed(false); await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "요청을 처리하지 못했습니다."); }
    finally { setPending(null); }
  }

  return <article className={styles.editor}>
    <div className={styles.editorHeader}><div><span>{stateLabel(draft.state)} · revision {draft.current_revision_no}</span><h2>{draft.project_code}</h2></div><strong>{draft.approved_document?.remaining_amount ?? "-"} {draft.transaction_currency} 잔여</strong></div>
    <BusinessJourney value={draft.journey} />
    <Input label="회계 인식일" type="date" value={recognitionDate} disabled={!editable} onChange={event => setRecognitionDate(event.target.value)} />
    <div className={styles.lineTable} role="table" aria-label="전표 라인">
      <div className={styles.lineHeader} role="row"><span>계정과목</span><span>적요</span><span>차변</span><span>대변</span></div>
      {lines.map((line, index) => <div className={styles.line} role="row" key={line.line_no}>
        <Input label={`${line.line_no}번 계정과목`} value={line.account_code} disabled={!editable} onChange={event => updateLine(index, "account_code", event.target.value.toUpperCase())} />
        <Input label={`${line.line_no}번 적요`} value={line.description ?? ""} disabled={!editable} onChange={event => updateLine(index, "description", event.target.value)} />
        <Input label={`${line.line_no}번 차변`} inputMode="decimal" value={line.debit_original} disabled={!editable} onChange={event => updateLine(index, "debit_original", event.target.value)} />
        <Input label={`${line.line_no}번 대변`} inputMode="decimal" value={line.credit_original} disabled={!editable} onChange={event => updateLine(index, "credit_original", event.target.value)} />
      </div>)}
    </div>
    <div className={`${styles.balance} ${balanced ? styles.pass : styles.fail}`}><span>차변 {balance.debit.toLocaleString("ko-KR")}</span><span>대변 {balance.credit.toLocaleString("ko-KR")}</span><strong>{balanced ? "대차 일치" : "대차 불일치"}</strong></div>
    {editable ? <div className={styles.actions}>
      <Button variant="secondary" leadingIcon={<Save aria-hidden="true" size={16} />} loading={pending === "save"} onClick={() => void run("save")}>revision 저장</Button>
      <Button variant="secondary" leadingIcon={<CheckCircle2 aria-hidden="true" size={16} />} loading={pending === "validate"} disabled={!balanced} onClick={() => void run("validate")}>검증</Button>
      {!confirmed ? <Button leadingIcon={<Send aria-hidden="true" size={16} />} disabled={!balanced} onClick={() => setConfirmed(true)}>회계 상신</Button>
        : <div className={styles.confirm} role="alert"><span>현재 revision을 잠그고 회계 결재를 요청합니다.</span><Button variant="ghost" onClick={() => setConfirmed(false)}>취소</Button><Button loading={pending === "submit"} onClick={() => void run("submit")}>상신 확인</Button></div>}
    </div> : null}
    {message ? <p className={styles.message} role="status">{message}</p> : null}
  </article>;
}

function CreateDraft({ client, proposals, onCancel, onCreated }: {
  readonly client: BusinessVoucherClientPort;
  readonly proposals: Awaited<ReturnType<BusinessProposalClientPort["list"]>>;
  readonly onCancel: () => void;
  readonly onCreated: (draft: BusinessVoucherDraft) => Promise<void>;
}) {
  const eligible = proposals.filter(item => item.approved_envelope_id && item.current_revision.project_codes.length > 0);
  const [proposalId, setProposalId] = useState(eligible[0]?.proposal_id ?? "");
  const [expenseAccount, setExpenseAccount] = useState("");
  const [offsetAccount, setOffsetAccount] = useState("");
  const [amount, setAmount] = useState("");
  const [recognitionDate, setRecognitionDate] = useState(new Date().toISOString().slice(0, 10));
  const [sourceRef, setSourceRef] = useState("");
  const [pending, setPending] = useState(false);
  const proposal = eligible.find(item => item.proposal_id === proposalId);
  const attachmentHash = proposal?.current_revision.attachment_manifest.find(
    item => typeof item.content_hash === "string",
  )?.content_hash;
  async function create() {
    if (!proposal?.approved_envelope_id || typeof attachmentHash !== "string") return;
    setPending(true);
    try {
      await onCreated(await client.create({
        envelopeId: proposal.approved_envelope_id,
        projectCode: proposal.current_revision.project_codes[0],
        recognitionDate,
        sourceKind: "EXPENSE_CLAIM",
        sourceRecordRef: sourceRef,
        lines: [
          { account_code: expenseAccount, debit_original: amount, credit_original: "0.0000", source_record_line_ref: `${sourceRef}:1`, description: proposal.current_revision.title, evidence_hash: attachmentHash },
          { account_code: offsetAccount, debit_original: "0.0000", credit_original: amount, source_record_line_ref: `${sourceRef}:2`, description: "지급 상계", evidence_hash: attachmentHash },
        ],
      }));
    } finally { setPending(false); }
  }
  return <article className={styles.create}>
    <h2>승인된 품의서에서 전표 생성</h2>
    <Select label="승인 품의서" value={proposalId} onChange={event => setProposalId(event.target.value)}><option value="">선택</option>{eligible.map(item => <option key={item.proposal_id} value={item.proposal_id}>{item.current_revision.title} · {item.current_revision.project_codes[0]}</option>)}</Select>
    <div className={styles.createGrid}><Input label="비용 계정코드" value={expenseAccount} onChange={event => setExpenseAccount(event.target.value.toUpperCase())} /><Input label="지급 계정코드" value={offsetAccount} onChange={event => setOffsetAccount(event.target.value.toUpperCase())} /><Input label="금액" inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} /><Input label="회계 인식일" type="date" value={recognitionDate} onChange={event => setRecognitionDate(event.target.value)} /><Input label="증빙 참조" value={sourceRef} onChange={event => setSourceRef(event.target.value)} /></div>
    {proposal && typeof attachmentHash !== "string" ? <p className={styles.notice}>실제 지출 증빙이 있는 승인 품의서만 전표로 전환할 수 있습니다.</p> : null}
    <div className={styles.actions}><Button variant="ghost" onClick={onCancel}>취소</Button><Button loading={pending} disabled={!proposal || typeof attachmentHash !== "string" || !expenseAccount || !offsetAccount || !amount || !sourceRef} onClick={() => void create()}>초안 생성</Button></div>
  </article>;
}

function stateLabel(state: BusinessVoucherDraft["state"]) { return ({ DRAFT: "초안", READY_FOR_REVIEW: "회계 결재 중", RETURNED_FOR_CORRECTION: "수정 요청", APPROVED: "승인", POSTED: "전기 완료", INVALIDATED: "무효" } as const)[state]; }
