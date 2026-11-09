import { Check, Minus, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";

import { buildRepairedResponseReviewCardViewModel } from "../../repairedResponseReviewCard.js";
import { Button, StatusPill } from "../../design-system/components";
import styles from "./ResponseQualityActions.module.css";

export type GenerationFeedbackValue = "positive" | "negative" | "neutral";

export interface GenerationFeedbackState {
  readonly status: "READY" | "SUBMITTING" | "RECORDED" | "FAILED";
  readonly value: GenerationFeedbackValue | null;
}

export function ResponseQualityActions({
  feedback,
  repairedResponseReview,
  onFeedback,
  onRepairedDecision,
}: {
  readonly feedback?: GenerationFeedbackState | null;
  readonly repairedResponseReview?: unknown;
  readonly onFeedback?: (value: GenerationFeedbackValue) => Promise<void> | void;
  readonly onRepairedDecision?: (action: "accept_repair" | "keep_original") => Promise<void> | void;
}) {
  const review = safeReviewViewModel(repairedResponseReview, Boolean(onRepairedDecision));
  if (!feedback && !review) return null;

  return (
    <section className={styles.surface} aria-label="응답 품질 작업">
      {review ? (
        <section className={styles.review} aria-labelledby="repaired-response-review-title">
          <header>
            <Wrench aria-hidden="true" size={18} />
            <div>
              <h2 id="repaired-response-review-title">수정된 응답 검토</h2>
              <p>{review.title}</p>
            </div>
            <StatusPill tone={review.decisionState.status === "RECORDED" ? "success" : "warning"}>
              {reviewStatusLabel(review.decisionState.status)}
            </StatusPill>
          </header>
          <p className={styles.preview}>{review.repairedOutputPreview}</p>
          <div className={styles.actions}>
            {review.primaryActions.map((action: any) => (
              <Button
                key={action.action}
                variant={action.action === "accept_repair" ? "primary" : "secondary"}
                size="sm"
                disabled={action.disabled}
                leadingIcon={action.action === "accept_repair" ? <Check aria-hidden="true" size={15} /> : undefined}
                data-repaired-response-decision-action={action.action}
                onClick={() => void onRepairedDecision?.(action.action)}
              >
                {action.label}
              </Button>
            ))}
          </div>
        </section>
      ) : null}

      {feedback ? (
        <section className={styles.feedback} aria-labelledby="generation-feedback-title">
          <div>
            <h2 id="generation-feedback-title">이 응답이 도움이 되었나요?</h2>
            <StatusPill tone={feedback.status === "FAILED" ? "danger" : feedback.status === "RECORDED" ? "success" : "neutral"}>
              {feedbackStatusLabel(feedback.status)}
            </StatusPill>
          </div>
          <div className={styles.actions}>
            <FeedbackButton value="positive" label="도움됨" icon={<ThumbsUp aria-hidden="true" size={15} />} feedback={feedback} onFeedback={onFeedback} />
            <FeedbackButton value="neutral" label="보통" icon={<Minus aria-hidden="true" size={15} />} feedback={feedback} onFeedback={onFeedback} />
            <FeedbackButton value="negative" label="문제 있음" icon={<ThumbsDown aria-hidden="true" size={15} />} feedback={feedback} onFeedback={onFeedback} />
          </div>
        </section>
      ) : null}
    </section>
  );
}

function FeedbackButton({
  value,
  label,
  icon,
  feedback,
  onFeedback,
}: {
  readonly value: GenerationFeedbackValue;
  readonly label: string;
  readonly icon: React.ReactNode;
  readonly feedback: GenerationFeedbackState;
  readonly onFeedback?: (value: GenerationFeedbackValue) => Promise<void> | void;
}) {
  return (
    <Button
      variant={feedback.value === value ? "primary" : "ghost"}
      size="sm"
      disabled={!onFeedback || feedback.status === "SUBMITTING"}
      leadingIcon={icon}
      aria-pressed={feedback.value === value}
      data-generation-feedback-value={value}
      onClick={() => void onFeedback?.(value)}
    >
      {label}
    </Button>
  );
}

function safeReviewViewModel(surface: unknown, decisionEnabled: boolean): any | null {
  if (!surface) return null;
  try {
    return buildRepairedResponseReviewCardViewModel(surface as any, {
      decisionEnabled,
      decisionState: (surface as any).decisionState,
    });
  } catch {
    return null;
  }
}

function feedbackStatusLabel(status: GenerationFeedbackState["status"]) {
  return ({ READY: "선택 가능", SUBMITTING: "저장 중", RECORDED: "저장됨", FAILED: "저장 실패" })[status];
}

function reviewStatusLabel(status: string) {
  return ({ READY_FOR_DECISION: "선택 필요", SUBMITTING: "저장 중", RECORDED: "선택 완료", FAILED: "저장 실패" } as Record<string, string>)[status] ?? "검토 필요";
}
