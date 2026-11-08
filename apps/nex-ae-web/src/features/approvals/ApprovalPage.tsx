import { useQuery } from "@tanstack/react-query";
import { Paperclip, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  ApprovalClientPort,
  ApprovalGate,
  ApprovalGateDetail,
  UserApprovalProjection,
} from "../../app/api/approvalClientPort";
import {
  Button,
  EmptyState,
  StatusPill,
  Stepper,
  Tabs,
} from "../../design-system/components";
import { isApprovalGateExpired } from "../../approvalClient.js";
import { mapApprovalState } from "../../ux/workState";
import { ApprovalDecisionPanel } from "./ApprovalDecisionPanel";
import { ApprovalEvidence, approvalRiskLabel } from "./ApprovalEvidence";
import styles from "./ApprovalPage.module.css";

const DOMAIN_LABELS = Object.freeze({
  NSL_WRITE: "보호된 업무 실행",
  AGENT_FORMAL: "Agent 공식 작업",
  BUSINESS_FORMAL: "업무 결재",
});

export function ApprovalPage({
  client,
  now = () => new Date(),
}: {
  readonly client: ApprovalClientPort | null;
  readonly now?: () => Date;
}) {
  const [selectedGateId, setSelectedGateId] = useState<string | null>(null);
  const inbox = useQuery({
    queryKey: ["approval-inbox", client?.clientMode],
    queryFn: () => client!.listApprovalGates({ limit: 50 }),
    enabled: client !== null,
  });
  const gates = inbox.data?.gates ?? [];

  useEffect(() => {
    if (gates.length === 0) {
      setSelectedGateId(null);
      return;
    }
    if (!selectedGateId || !gates.some(gate => gate.gate_id === selectedGateId)) {
      setSelectedGateId(gates[0].gate_id);
    }
  }, [gates, selectedGateId]);

  return (
    <section className={styles.page} aria-labelledby="approval-page-title">
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>검토 업무</p>
          <h1 id="approval-page-title">승인함</h1>
        </div>
        <Button
          variant="secondary"
          size="sm"
          leadingIcon={<RefreshCw aria-hidden="true" size={16} />}
          onClick={() => void inbox.refetch()}
          disabled={client === null || inbox.isFetching}
        >
          새로고침
        </Button>
      </header>

      {client === null ? (
        <div role="alert" className={styles.alert}>승인 서비스를 연결할 수 없습니다.</div>
      ) : inbox.isPending ? (
        <div role="status" className={styles.statePanel}>승인 요청을 불러오는 중입니다.</div>
      ) : inbox.isError ? (
        <div role="alert" className={styles.statePanel}>
          <strong>승인 요청을 불러오지 못했습니다.</strong>
          <Button variant="secondary" size="sm" onClick={() => void inbox.refetch()}>
            다시 시도
          </Button>
        </div>
      ) : (
        <Tabs
          label="승인함 구분"
          defaultValue="pending"
          items={[
            {
              id: "pending",
              label: "대기",
              count: gates.length,
              content: gates.length > 0 ? (
                <ApprovalWorkspace
                  client={client}
                  gates={gates}
                  selectedGateId={selectedGateId}
                  onSelect={setSelectedGateId}
                  onDecisionComplete={() => inbox.refetch().then(() => undefined)}
                  now={now}
                />
              ) : (
                <EmptyState
                  title="대기 중인 승인 요청이 없습니다"
                  description="새 승인 요청이 접수되면 이곳에 표시됩니다."
                />
              ),
            },
            {
              id: "completed",
              label: "완료",
              disabled: true,
              content: null,
            },
            {
              id: "rejected",
              label: "반려",
              disabled: true,
              content: null,
            },
          ]}
        />
      )}
      <p className={styles.availabilityNote}>완료·반려 이력은 현재 조회 계약에서 제공되지 않습니다.</p>
    </section>
  );
}

function ApprovalWorkspace({
  client,
  gates,
  selectedGateId,
  onSelect,
  onDecisionComplete,
  now,
}: {
  readonly client: ApprovalClientPort;
  readonly gates: readonly ApprovalGate[];
  readonly selectedGateId: string | null;
  readonly onSelect: (gateId: string) => void;
  readonly onDecisionComplete: () => Promise<void>;
  readonly now: () => Date;
}) {
  return (
    <div className={styles.workspace}>
      <ApprovalList
        gates={gates}
        selectedGateId={selectedGateId}
        onSelect={onSelect}
        now={now}
      />
      {selectedGateId ? (
        <ApprovalDetail
          client={client}
          gateId={selectedGateId}
          now={now}
          onDecisionComplete={onDecisionComplete}
        />
      ) : null}
    </div>
  );
}

function ApprovalList({
  gates,
  selectedGateId,
  onSelect,
  now,
}: {
  readonly gates: readonly ApprovalGate[];
  readonly selectedGateId: string | null;
  readonly onSelect: (gateId: string) => void;
  readonly now: () => Date;
}) {
  return (
    <div className={styles.listPane} aria-label="대기 중인 승인 요청">
      <div className={styles.listHeading}>
        <h2>검토 대기</h2>
        <span>{gates.length}건</span>
      </div>
      <ul className={styles.approvalList}>
        {gates.map(gate => {
          const state = approvalStateForGate(gate, now());
          return (
            <li key={gate.gate_id}>
              <button
                type="button"
                className={styles.listItem}
                aria-pressed={gate.gate_id === selectedGateId}
                onClick={() => onSelect(gate.gate_id)}
              >
                <span className={styles.listItemTopline}>
                  <span>{DOMAIN_LABELS[gate.approval_domain]}</span>
                  <StatusPill tone={state.tone}>{state.label}</StatusPill>
                </span>
                <strong>{gate.title}</strong>
                <span className={styles.summary}>{gate.summary}</span>
                <span className={styles.itemMeta}>
                  {gate.attachment_manifest ? (
                    <><Paperclip aria-hidden="true" size={14} /> 첨부 {gate.attachment_manifest.attachment_count}개</>
                  ) : "첨부 없음"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ApprovalDetail({
  client,
  gateId,
  now,
  onDecisionComplete,
}: {
  readonly client: ApprovalClientPort;
  readonly gateId: string;
  readonly now: () => Date;
  readonly onDecisionComplete: () => Promise<void>;
}) {
  const detail = useQuery({
    queryKey: ["approval-detail", client.clientMode, gateId],
    queryFn: () => client.getApprovalGate(gateId),
  });
  const projection = useQuery({
    queryKey: ["approval-projection", client.clientMode, gateId],
    queryFn: () => client.getApprovalProjection(gateId),
  });

  if (detail.isPending || projection.isPending) {
    return <div className={styles.detailPane} role="status">승인 상세를 불러오는 중입니다.</div>;
  }
  if (detail.isError || projection.isError) {
    return (
      <div className={styles.detailPane} role="alert">
        <strong>승인 상세를 불러오지 못했습니다.</strong>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void Promise.all([detail.refetch(), projection.refetch()])}
        >
          다시 시도
        </Button>
      </div>
    );
  }

  return (
    <ApprovalDetailContent
      client={client}
      detail={detail.data}
      projection={projection.data}
      now={now}
      onDecisionComplete={onDecisionComplete}
    />
  );
}

function ApprovalDetailContent({
  client,
  detail,
  projection,
  now,
  onDecisionComplete,
}: {
  readonly client: ApprovalClientPort;
  readonly detail: ApprovalGateDetail;
  readonly projection: UserApprovalProjection;
  readonly now: () => Date;
  readonly onDecisionComplete: () => Promise<void>;
}) {
  const gate = detail.gate;
  const state = approvalStateForGate(gate, now());
  const project =
    projection.project.display_name ?? projection.project.project_id ?? "정보 미제공";
  const requester = projection.requester.display_name ?? "정보 미제공";
  const amount = projection.amount.value
    ? `${projection.amount.value} ${projection.amount.currency ?? ""}`.trim()
    : "정보 미제공";

  return (
    <article className={styles.detailPane} aria-labelledby="approval-detail-title">
      <header className={styles.detailHeader}>
        <div>
          <p>{DOMAIN_LABELS[projection.approval_domain]}</p>
          <h2 id="approval-detail-title">{projection.title}</h2>
        </div>
        <StatusPill tone={state.tone}>{state.label}</StatusPill>
      </header>
      <p className={styles.businessSummary}>{projection.summary}</p>

      <dl className={styles.facts}>
        <div><dt>요청자</dt><dd>{requester}</dd></div>
        <div><dt>Project</dt><dd>{project}</dd></div>
        <div><dt>금액</dt><dd>{amount}</dd></div>
        <div><dt>요청 시각</dt><dd>{formatDateTime(projection.requested_at.value)}</dd></div>
        <div><dt>업무일</dt><dd>{projection.business_date.value ?? "정보 미제공"}</dd></div>
        <div><dt>위험도</dt><dd>{approvalRiskLabel(projection.risk)}</dd></div>
      </dl>

      {gate.formal_approval ? <FormalProgress progress={gate.formal_approval} /> : null}
      <ApprovalEvidence
        risk={projection.risk}
        manifest={gate.attachment_manifest}
        resolveResourceRoute={client.resolveResourceRoute}
      />
      <ApprovalDecisionPanel
        client={client}
        gateId={gate.gate_id}
        actionable={state.outcome === "pending"}
        onNext={onDecisionComplete}
      />

      <details className={styles.technicalDetails}>
        <summary>기술 상세</summary>
        <dl>
          <div><dt>제공자</dt><dd>{projection.approval_provider_type ?? "없음"}</dd></div>
          <div><dt>대상 참조</dt><dd>{projection.approval_target_ref ?? "없음"}</dd></div>
          <div><dt>업무 작업 ID</dt><dd>{projection.business_operation_id ?? "없음"}</dd></div>
          <div><dt>기술 ID</dt><dd>{projection.gate_id}</dd></div>
        </dl>
      </details>
    </article>
  );
}

function FormalProgress({ progress }: { readonly progress: NonNullable<ApprovalGate["formal_approval"]> }) {
  const items = Array.from({ length: progress.stage_count }, (_, index) => {
    const stage = index + 1;
    return {
      id: `stage-${stage}`,
      label: `${stage}단계`,
      state: stage < progress.current_stage ? "complete" : stage === progress.current_stage ? "current" : "pending",
    } as const;
  });
  return (
    <section className={styles.section} aria-labelledby="formal-progress-title">
      <div className={styles.sectionHeading}>
        <h3 id="formal-progress-title">결재 진행</h3>
        <span>요청 역할: {progress.requested_role}</span>
      </div>
      <Stepper items={items} label="업무 결재 진행 단계" />
    </section>
  );
}

function approvalStateForGate(gate: ApprovalGate, now: Date) {
  return mapApprovalState(isApprovalGateExpired(gate, now) ? "EXPIRED" : gate.state);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "정보 미제공"
    : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
