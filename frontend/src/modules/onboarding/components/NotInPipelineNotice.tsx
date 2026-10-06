/**
 * "This company is not in the sales pipeline".
 *
 * A company that exists only because it was somebody's buyer is a full company
 * record — it can be screened, cleared and traded with — but nobody is selling to
 * it. Its `journey` column reads `LEAD` because the column is `NOT NULL`, not
 * because anyone judged it, and `ck_exporter_profile_not_in_pipeline_start`
 * requires exactly that. So showing a `LEAD` chip and an empty qualification form
 * would be actively misleading: it would invite someone to qualify a company that
 * the server refuses to qualify (`COMPANY_NOT_IN_PIPELINE`, 409).
 *
 * This replaces those controls with the reason, and — for a role that may act — the
 * one action that changes it. That is the difference between a screen
 * that explains itself and one that offers a button which 409s, the same principle
 * `handover_blocked_reason` follows on the deal page.
 *
 * `onBringIn` is optional: a read-only role (DEVELOPER) sees the explanation with
 * no action, because the server would refuse it.
 */


import { Button } from '@/components';
import { Icon } from '@/design/icons';

export interface NotInPipelineNoticeProps {
  /** What is not available, in the words of the panel it replaces. */
  what: string;
  /** Offered only to a role the server would accept it from. */
  onBringIn?: () => void;
  /** True while the request is in flight, so the button cannot be pressed twice. */
  busy?: boolean;
}

export function NotInPipelineNotice({ what, onBringIn, busy }: NotInPipelineNoticeProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-dashed border-line-strong bg-paper p-5 text-body"
      data-testid="not-in-pipeline-notice"
    >
      <p className="flex items-start gap-2 font-medium text-ink">
        <Icon.info size={16} className="mt-0.5 shrink-0 text-ink-3" />
        {what} is not needed: this company is not in the sales pipeline.
      </p>
      <p className="text-ink-2">
        It exists because it was the buyer on a deal, so nobody is selling to it. It is
        still a full company record — it can be screened and cleared like any other.
      </p>
      {onBringIn && (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" variant="secondary" onClick={onBringIn} disabled={busy}>
            Bring into the pipeline <Icon.forward size={14} />
          </Button>
          <span className="text-caption text-ink-3">
            Do this if we are going to sell to them. Its journey starts at LEAD.
          </span>
        </div>
      )}
    </div>
  );
}
