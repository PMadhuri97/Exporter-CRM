/**
 * The background-check gauge.
 *
 * The six values of `background-check.md` §2, and nothing inferred from them. In
 * particular `NOT_STARTED` says **"Not started"**, never "pending" or "clear": no
 * check has run, and a screen that implies one has is the exact failure the
 * pass-through scanner warnings exist to prevent.
 *
 * Two served sub-states show as badges beside the
 * value, never as a seventh value. **Awaiting approval** — a CLEAR, FLAGGED or ON_HOLD
 * has been proposed and waits for a second officer; the gauge has not moved.
 * **Re-KYC due** — the Clear has expired or expires within the Re-KYC window; an
 * expired Clear still reads Clear (nothing moves it automatically), and the badge is
 * how that shows.
 */

import { Badge, type BadgeTone } from '@/components';

import type { BackgroundCheckState } from '../types';

// One meaning per value (frontend-plan §5.2, §18.2): not started is neutral, in review
// is progress, more info is attention, clear is positive, flagged and on hold are
// negative. The words always say the state.
const TONE: Record<BackgroundCheckState, BadgeTone> = {
  NOT_STARTED: 'neutral',
  IN_REVIEW: 'progress',
  MORE_INFO: 'attention',
  CLEAR: 'positive',
  FLAGGED: 'negative',
  ON_HOLD: 'negative',
};

const LABELS: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  MORE_INFO: 'More information needed',
  CLEAR: 'Clear',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

/** What each value means, in a sentence, so nobody has to guess. */
const DESCRIPTIONS: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'No background check has been started for this company.',
  IN_REVIEW: 'Compliance is reviewing checks, screening items and documents.',
  MORE_INFO: 'Compliance has asked for something specific before it can continue.',
  CLEAR: 'Compliance has cleared this company, with a risk rating and a recorded reason.',
  FLAGGED: 'A concern has been raised. Deals cannot be handed over.',
  ON_HOLD: 'A flagged company put on hold. Deals cannot be handed over.',
};

export function BackgroundCheckGauge({
  value,
  awaitingApproval = false,
  rekycDue = false,
}: {
  value: BackgroundCheckState;
  awaitingApproval?: boolean;
  rekycDue?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={TONE[value]} data-testid="background-check-gauge" data-value={value}>
          {LABELS[value]}
        </Badge>
        {awaitingApproval && (
          <Badge variant="outline" data-testid="awaiting-approval-badge">
            Awaiting approval
          </Badge>
        )}
        {rekycDue && (
          <Badge tone="attention" data-testid="rekyc-due-badge">
            Re-KYC due
          </Badge>
        )}
      </div>
      <p className="text-secondary text-ink-3">
        {DESCRIPTIONS[value]}
        {awaitingApproval &&
          ' A proposed decision is waiting for a second compliance officer to approve it.'}
      </p>
    </div>
  );
}
