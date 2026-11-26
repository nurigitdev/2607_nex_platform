import { useQuery } from "@tanstack/react-query";
import { FileCheck2, RefreshCw, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  BusinessProposal,
  BusinessProposalApprovalPreview,
  BusinessProposalClientPort,
  BusinessProposalState,
  ProposalRevisionCommand,
} from "../../app/api/businessProposalClientPort";
import { Button, EmptyState, Input, Select, Textarea } from "../../design-system/components";
import { BusinessJourney } from "../business/BusinessJourney";
import styles from "./ProposalPage.module.css";

const FILTERS: readonly { value: BusinessProposalState | "ALL"; label: string }[] = [
  { value: "ALL", label: "전체" },
  { value: "DRAFT", label: "초안" },
  { value: "SUBMITTED", label: "결재 중" },
  { value: "APPROVED", label: "승인" },
  { value: "REJECTED", label: "반려" },
  { value: "WITHDRAWN", label: "회수" },
];

export function ProposalPage({ client }: { readonly client: BusinessProposalClientPort | null }) {
  const [filter, setFilter] = useState<BusinessProposalState | "ALL">("ALL");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const proposals = useQuery({
    queryKey: ["business-proposals", client?.clientMode, filter],
    queryFn: () => client!.list(filter === "ALL" ? [] : [filter]),
    enabled: client !== null,
  });
  const items = proposals.data ?? [];

  useEffect(() => {
    if (!items.length) setSelectedId(null);
    else if (!selectedId || !items.some(item => item.proposal_id === selectedId)) {
      setSelectedId(items[0].proposal_id);
    }
  }, [items, selectedId]);

  return (
    <section className={styles.page} aria-labelledby="proposal-page-title">
      <header className={styles.header}>
        <div><p>업무 문서</p><h1 id="proposal-page-title">품의서</h1></div>
        <Button
          variant="secondary"
          size="sm"
          leadingIcon={<RefreshCw aria-hidden="true" size={16} />}
          onClick={() => void proposals.refetch()}
          disabled={!client || proposals.isFetching}
        >새로고침</Button>
      </header>
      <div className={styles.filters} role="group" aria-label="품의서 상태 필터">
        {FILTERS.map(item => (
          <button
            key={item.value}
            type="button"
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
          >{item.label}</button>
        ))}
      </div>
      {!client ? <div className={styles.notice} role="alert">품의서 서비스를 연결할 수 없습니다.</div>
        : proposals.isPending ? <div className={styles.notice} role="status">품의서를 불러오는 중입니다.</div>
        : proposals.isError ? <div className={styles.notice} role="alert">품의서를 불러오지 못했습니다.</div>
        : items.length === 0 ? (
          <EmptyState title="품의서가 없습니다" description="워크스페이스에서 품의서 초안을 작성하면 이곳에서 검토할 수 있습니다." />
        ) : (
          <div className={styles.workspace}>
            <ProposalList items={items} selectedId={selectedId} onSelect={setSelectedId} />
            {selectedId ? (
              <ProposalEditor
                key={selectedId}
                client={client}
                proposal={items.find(item => item.proposal_id === selectedId)!}
                onChanged={() => proposals.refetch().then(() => undefined)}
              />
            ) : null}
          </div>
        )}
    </section>
  );
}

function ProposalList({ items, selectedId, onSelect }: {
  readonly items: readonly BusinessProposal[];
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
}) {
  return <aside className={styles.list} aria-label="품의서 목록">
    <h2>내 품의서 <span>{items.length}건</span></h2>
    <ul>{items.map(item => <li key={item.proposal_id}>
      <button type="button" aria-pressed={item.proposal_id === selectedId} onClick={() => onSelect(item.proposal_id)}>
        <strong>{item.current_revision.title}</strong>
        <span>{item.current_revision.project_codes.join(", ") || "회사 공통"}</span>
        <small>{stateLabel(item.state)} · {formatMoney(item)}</small>
      </button>
    </li>)}</ul>
  </aside>;
}

function ProposalEditor({ client, proposal, onChanged }: {
  readonly client: BusinessProposalClientPort;
  readonly proposal: BusinessProposal;
  readonly onChanged: () => Promise<void>;
}) {
  const revision = proposal.current_revision;
  const [form, setForm] = useState(() => ({
    title: revision.title,
    purpose: revision.purpose,
    businessJustification: revision.business_justification,
    requestedAmount: revision.requested_amount,
    originalCurrency: revision.original_currency,
    validUntil: revision.valid_until?.slice(0, 10) ?? "",
  }));
  const [preview, setPreview] = useState<BusinessProposalApprovalPreview | null>(null);
  const [approvers, setApprovers] = useState<Record<number, string>>({});
  const [pending, setPending] = useState<"save" | "preview" | "submit" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const editable = proposal.state === "DRAFT";
  const selections = useMemo(() => preview?.required_stages.map(stage => ({
    stage_order: stage.stage_order,
    subject_id: approvers[stage.stage_order] ?? "",
  })) ?? [], [preview, approvers]);
  const allSelected = selections.length > 0 && selections.every(item => item.subject_id);

  function updateForm(next: typeof form) {
    setForm(next);
    setPreview(null);
    setApprovers({});
    setConfirming(false);
  }

  async function save() {
    setPending("save"); setMessage(null); setPreview(null); setApprovers({});
    try {
      await client.revise(proposal.proposal_id, revisionCommand(proposal, form));
      setMessage("새 revision으로 저장했습니다.");
      await onChanged();
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setPending(null); }
  }

  async function loadPreview() {
    setPending("preview"); setMessage(null);
    try {
      const loaded = await client.previewApproval(proposal.proposal_id, new Date().toISOString());
      setPreview(loaded);
      setApprovers(Object.fromEntries(loaded.required_stages.map(stage => [stage.stage_order, stage.candidates[0]?.subject_id ?? ""])));
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setPending(null); }
  }

  async function submit() {
    if (!preview || !allSelected) return;
    setPending("submit"); setMessage(null);
    try {
      await client.selectApprovalLine(proposal.proposal_id, { preview, selectedApprovers: selections });
      await client.submit(proposal, preview, selections);
      setConfirming(false);
      setMessage("품의서를 상신했습니다.");
      await onChanged();
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setPending(null); }
  }

  return <article className={styles.editor}>
    <div className={styles.editorHeader}>
      <div><span>{stateLabel(proposal.state)} · revision {proposal.current_revision_no}</span><h2>{revision.title}</h2></div>
      <span>{revision.project_codes.join(", ") || "회사 공통"}</span>
    </div>
    <BusinessJourney value={proposal.journey} />
    <section className={styles.approvalLine} aria-labelledby="approval-line-title">
      <div>
        <div>
          <h3 id="approval-line-title">결재선</h3>
          <span>현재 revision에 적용할 필수 결재 단계를 확인합니다.</span>
        </div>
        {editable ? <Button variant="secondary" loading={pending === "preview"} onClick={() => void loadPreview()}>결재선 미리보기</Button> : null}
      </div>
      {preview ? <>
        <p className={styles.approvalAmount}>{preview.normalized_amount_evidence.normalized_amount} {preview.normalized_amount_evidence.functional_currency} 기준</p>
        {preview.required_stages.map(stage => <Select
          key={stage.stage_order}
          label={`${stage.stage_order}단계 · ${stage.position_type}`}
          value={approvers[stage.stage_order] ?? ""}
          onChange={event => setApprovers({ ...approvers, [stage.stage_order]: event.target.value })}
        >
          <option value="">결재자 선택</option>
          {stage.candidates.map(candidate => <option key={candidate.subject_id} value={candidate.subject_id}>{candidate.display_name}</option>)}
        </Select>)}
        {!confirming ? <Button leadingIcon={<FileCheck2 aria-hidden="true" size={16} />} disabled={!allSelected} onClick={() => setConfirming(true)}>상신</Button> : (
          <div className={styles.confirm} role="alert"><p>현재 revision과 결재선을 잠그고 상신합니다.</p><div><Button variant="ghost" onClick={() => setConfirming(false)}>취소</Button><Button loading={pending === "submit"} onClick={() => void submit()}>상신 확인</Button></div></div>
        )}
      </> : <p className={styles.approvalHint}>결재선 미리보기를 실행하면 금액과 업무 범위에 맞는 결재 단계가 표시됩니다.</p>}
    </section>
    {proposal.state === "REJECTED" ? <section className={styles.rejection} aria-labelledby="proposal-rejection-title">
      <h3 id="proposal-rejection-title">반려 사유</h3>
      <p>{proposal.rejection_reason ?? "반려 사유를 확인할 수 없습니다."}</p>
    </section> : null}
    <div className={styles.formGrid}>
      <Input label="제목" required value={form.title} disabled={!editable} onChange={event => updateForm({ ...form, title: event.target.value })} />
      <Input label="금액" required inputMode="decimal" value={form.requestedAmount} disabled={!editable} onChange={event => updateForm({ ...form, requestedAmount: event.target.value })} />
      <Input label="통화" required value={form.originalCurrency} disabled={!editable} onChange={event => updateForm({ ...form, originalCurrency: event.target.value.toUpperCase() })} />
      <Input label="유효 종료일" type="date" value={form.validUntil} disabled={!editable} onChange={event => updateForm({ ...form, validUntil: event.target.value })} />
      <div className={styles.full}><Textarea label="목적" required rows={3} value={form.purpose} disabled={!editable} onChange={event => updateForm({ ...form, purpose: event.target.value })} /></div>
      <div className={styles.full}><Textarea label="업무 필요성" required rows={5} value={form.businessJustification} disabled={!editable} onChange={event => updateForm({ ...form, businessJustification: event.target.value })} /></div>
    </div>
    {editable ? <div className={styles.actions}>
      <Button variant="secondary" leadingIcon={<Save aria-hidden="true" size={16} />} loading={pending === "save"} onClick={() => void save()}>revision 저장</Button>
    </div> : null}
    {message ? <p className={styles.message} role="status">{message}</p> : null}
  </article>;
}

function revisionCommand(proposal: BusinessProposal, form: {
  readonly title: string; readonly purpose: string; readonly businessJustification: string;
  readonly requestedAmount: string; readonly originalCurrency: string; readonly validUntil: string;
}): ProposalRevisionCommand {
  const revision = proposal.current_revision;
  return {
    proposal_id: proposal.proposal_id,
    revision_id: crypto.randomUUID(),
    company_id: proposal.company_id,
    document_type: revision.document_type,
    work_code: revision.work_code,
    title: form.title,
    purpose: form.purpose,
    business_justification: form.businessJustification,
    transaction_type: revision.transaction_type,
    requested_amount: form.requestedAmount,
    original_currency: form.originalCurrency,
    valid_from: revision.valid_from,
    valid_until: form.validUntil ? new Date(`${form.validUntil}T23:59:59Z`).toISOString() : null,
    scope_type: revision.scope_type,
    project_ids: revision.project_ids,
    project_codes: revision.project_codes,
    attachment_manifest: revision.attachment_manifest,
    expected_version: proposal.version,
    expected_revision: proposal.current_revision_no,
  };
}

function stateLabel(state: BusinessProposalState) { return ({ DRAFT: "초안", SUBMITTED: "결재 중", APPROVED: "승인", REJECTED: "반려", WITHDRAWN: "회수" } as const)[state]; }
function formatMoney(proposal: BusinessProposal) { return `${Number(proposal.current_revision.requested_amount).toLocaleString("ko-KR")} ${proposal.current_revision.original_currency}`; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "요청을 처리하지 못했습니다."; }
