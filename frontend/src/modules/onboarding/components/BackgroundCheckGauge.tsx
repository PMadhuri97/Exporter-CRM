/**
 * The background-check gauge — **owner: Developer 4A** (L4-03, L4-08).
 *
 * The six values of `background-check.md` §2, and nothing inferred from them. In
 * particular `NOT_STARTED` says **"Not started"**, never "pending" or "clear": no
 * check has run, and a screen that implies one has is the exact failure the
 * pass-through scanner warnings exist to prevent.
 *
 * Developer 1 (plans P3-1c, P3-3c): two served sub-states show as badges beside the
 * value, never as a seventh value. **Awaiting approval** — a CLEAR, FLAGGED or ON_HOLD
 * has been proposed and waits for a second officer; the gauge has not moved.
 * **Re-KYC due** — the Clear has expired or expires within the Re-KYC window; an
 * expired Clear still reads Clear (nothing moves it automatically), and the badge is
 * how that shows.
 */

import type { BackgroundCheckState } from '../types';

// One meaning per value (frontend-plan §5.2): not started is idle, in review is
// progress, more info is attention, clear is positive, flagged and on hold are
// negative. The lamp in front repeats the state as a shape (§18.2).
const STYLES: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'bg-sunken text-ink-2',
  IN_REVIEW: 'bg-progress-tint text-progress',
  MORE_INFO: 'bg-attention-tint text-attention',
  CLEAR: 'bg-positive-tint text-positive',
  FLAGGED: 'bg-negative-tint text-negative',
  ON_HOLD: 'bg-negative-tint text-negative',
};

const LAMP: Record<BackgroundCheckState, string> = {
  NOT_STARTED: '◌',
  IN_REVIEW: '◔',
  MORE_INFO: '?',
  CLEAR: '●',
  FLAGGED: '▲',
  ON_HOLD: '■',
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
        <span
          data-testid="background-check-gauge"
          data-value={value}
          className={`inline-flex w-fit items-center gap-1.5 rounded-sm px-2 py-1 text-body font-medium ${STYLES[value]}`}
        >
          <span aria-hidden className="text-[0.8em] leading-none">
            {LAMP[value]}
          </span>
          {LABELS[value]}
        </span>
        {awaitingApproval && (
          <span
            data-testid="awaiting-approval-badge"
            className="inline-flex items-center rounded-sm border border-dashed border-ink px-1.5 py-0.5 text-caption font-medium text-ink"
          >
            Awaiting approval
          </span>
        )}
        {rekycDue && (
          <span
            data-testid="rekyc-due-badge"
            className="inline-flex items-center gap-1 rounded-sm bg-attention-tint px-1.5 py-0.5 text-caption font-medium text-attention"
          >
            Re-KYC due
          </span>
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
