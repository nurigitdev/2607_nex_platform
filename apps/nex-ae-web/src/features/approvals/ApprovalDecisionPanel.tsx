import { useMutation } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type {
  ApprovalClientPort,
  ApprovalDecisionRequest,
  ApprovalDecisionResult,
} from "../../app/api/approvalClientPort";
import {
  Button,
  ConfirmDialog,
  StatusPill,
  Textarea,
} from "../../design-system/components";
import { buildApprovalDecisionRequest } from "../../approvalClient.js";
import styles from "./ApprovalPage.module.css";

type Decision = "APPROVE" | "REJECT";
const buildDecisionRequest = buildApprovalDecisionRequest as unknown as (input: {
  readonly decision: Decision;
  readonly decisionComment: string | null;
}) => ApprovalDecisionRequest;

export function ApprovalDecisionPanel({
  client,
  gateId,
  actionable,
  onNext,
}: {
  readonly client: ApprovalClientPort;
  readonly gateId: string;
  readonly actionable: boolean;
  readonly onNext: () => void | Promise<void>;
}) {
  const [rejectionReason, setRejectionReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);
  const [result, setResult] = useState<ApprovalDecisionResult | null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const mutation = useMutation({
    mutationFn: ({ decision, comment }: { decision: Decision; comment: string | null }) => {
      const request = buildDecisionRequest({
        decision,
        decisionComment: comment,
      });
      return client.submitApprovalDecision(gateId, request);
    },
    onSuccess: decision => setResult(decision),
  });

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  if (!actionable && result === null) return null;
  if (result) {
    const approved = result.decision === "APPROVE";
    return (
      <section
        ref={resultRef}
        className={styles.decisionResult}
        aria-labelledby="decision-result-title"
        role="status"
        tabIndex={-1}
      >
        <div>
          <h3 id="decision-result-title">결정이 기록되었습니다</h3>
          <StatusPill tone={approved ? "success" : "danger"}>
            {approved ? "승인됨" : "반려됨"}
          </StatusPill>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void onNext()}>
          다음 요청 검토
        </Button>
      </section>
    );
  }

  const reasonMissing = rejectionReason.trim().length === 0;
  return (
    <section className={styles.decisionPanel} aria-labelledby="decision-panel-title">
      <div>
        <h3 id="decision-panel-title">승인 결정</h3>
        <p>검토 결과를 확인한 뒤 결정을 기록합니다.</p>
      </div>
      <Textarea
        label="반려 사유"
        value={rejectionReason}
        onChange={event => setRejectionReason(event.target.value)}
        onBlur={() => setReasonTouched(true)}
        error={reasonTouched && reasonMissing ? "반려 사유를 입력해 주세요." : undefined}
        hint={!reasonTouched ? "반려하는 경우 사유가 필요합니다." : undefined}
        required
        disabled={mutation.isPending}
      />
      {mutation.isError ? (
        <div role="alert" className={styles.decisionError}>
          {decisionErrorMessage(mutation.error)}
        </div>
      ) : null}
      <div className={styles.decisionActions}>
        <ConfirmDialog
          title="이 요청을 승인하시겠습니까?"
          description="승인 결정은 업무 실행 절차를 계속 진행합니다."
          confirmLabel="승인 확정"
          trigger={
            <Button
              leadingIcon={<Check aria-hidden="true" size={17} />}
              loading={mutation.isPending && mutation.variables?.decision === "APPROVE"}
              disabled={mutation.isPending}
            >
              승인
            </Button>
          }
          onConfirm={() => mutation.mutate({ decision: "APPROVE", comment: null })}
        />
        <ConfirmDialog
          title="이 요청을 반려하시겠습니까?"
          description="입력한 사유가 요청자에게 결정 근거로 전달됩니다."
          confirmLabel="반려 확정"
          destructive
          trigger={
            <Button
              variant="danger"
              leadingIcon={<X aria-hidden="true" size={17} />}
              loading={mutation.isPending && mutation.variables?.decision === "REJECT"}
              disabled={reasonMissing || mutation.isPending}
            >
              반려
            </Button>
          }
          onConfirm={() => mutation.mutate({
            decision: "REJECT",
            comment: rejectionReason.trim(),
          })}
        />
      </div>
    </section>
  );
}

function decisionErrorMessage(error: unknown) {
  const status = errorStatus(error);
  if (status === "APPROVAL_EXPIRED") return "승인 기한이 만료되었습니다.";
  if (status === "APPROVAL_DECISION_UNAUTHORIZED") {
    return "현재 계정에 승인 권한이 없습니다.";
  }
  if (status === "APPROVAL_DECISION_CONFLICT") {
    return "다른 결정이 이미 기록되었습니다. 목록을 새로고침해 주세요.";
  }
  if (isRetryable(error)) return "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  return "승인 결정을 기록하지 못했습니다.";
}

function errorStatus(error: unknown) {
  if (error && typeof error === "object" && "status" in error) {
    return String(error.status);
  }
  return "";
}

function isRetryable(error: unknown) {
  return Boolean(
    error &&
      typeof error === "object" &&
      (("retryable" in error && error.retryable === true) ||
        ("httpStatus" in error && Number(error.httpStatus) >= 500)),
  );
}
