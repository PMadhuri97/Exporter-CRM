/**
 * The background-check gauge — **owner: Developer 4A** (L4-03, L4-08).
 *
 * The six values of `background-check.md` §2, and nothing inferred from them. In
 * particular `NOT_STARTED` says **"Not started"**, never "pending" or "clear": no
 * check has run, and a screen that implies one has is the exact failure the
 * pass-through scanner warnings exist to prevent.
 */

import type { BackgroundCheckState } from '../types';

const STYLES: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  IN_REVIEW: 'bg-blue-50 text-blue-700 ring-blue-700/20',
  MORE_INFO: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  CLEAR: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  FLAGGED: 'bg-red-50 text-red-700 ring-red-600/20',
  ON_HOLD: 'bg-orange-50 text-orange-800 ring-orange-600/30',
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

export function BackgroundCheckGauge({ value }: { value: BackgroundCheckState }) {
  return (
    <div className="flex flex-col gap-1">
      <span
        data-testid="background-check-gauge"
        data-value={value}
        className={`inline-flex w-fit items-center rounded-full px-2.5 py-1 text-sm font-medium ring-1 ring-inset ${STYLES[value]}`}
      >
        {LABELS[value]}
      </span>
      <p className="text-xs text-slate-500">{DESCRIPTIONS[value]}</p>
    </div>
  );
}
