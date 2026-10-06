/**
 * Re-KYC / Re-KYB — start a new check cycle.
 *
 * The buttons are the server's `allowed_cycle_actions`, exactly: the server offers a
 * kind only when it would accept the start (COMPLIANCE or ADMIN; not on a FLAGGED or
 * ON_HOLD company; not while the current cycle is still empty). This file keeps no
 * role list and no state table.
 *
 * A start needs a reason. When `reopens` is set the company is CLEAR, and the same
 * request moves it back to IN_REVIEW — said before anyone confirms, because it
 * pauses the company's handovers until the new cycle is cleared.
 */

import { useState } from 'react';

import { ApiError } from '@/lib/api/errors';

import { useStartCheckCycle } from '../hooks';
import type { BackgroundCheckCycleAction } from '../types';

import { cycleKindLabel } from './background-check-labels';

export function CheckCycleActions({
  customerId,
  actions,
}: {
  customerId: string;
  actions: BackgroundCheckCycleAction[];
}) {
  const start = useStartCheckCycle(customerId);
  const [chosen, setChosen] = useState<BackgroundCheckCycleAction | null>(null);
  const [reason, setReason] = useState('');

  if (actions.length === 0) return null;

  function close() {
    setChosen(null);
    setReason('');
    start.reset();
  }

  return (
    <div data-testid="check-cycle-actions" className="mt-3">
      {!chosen && (
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <button
              key={action.kind}
              type="button"
              onClick={() => setChosen(action)}
              className="rounded border border-line-strong px-3 py-1.5 text-body text-ink hover:bg-sunken"
            >
              Start {cycleKindLabel(action.kind)}
            </button>
          ))}
        </div>
      )}
      {chosen && (
        <div
          role="dialog"
          aria-label={`Start ${cycleKindLabel(chosen.kind)}`}
          className="rounded border border-line p-3"
        >
          <p className="text-body font-medium text-ink">
            Start a {cycleKindLabel(chosen.kind)}
          </p>
          <p className="mt-1 text-caption text-ink-2">
            A new check cycle starts with every screening item unanswered and no results;
            the current cycle stays readable.
            {chosen.reopens &&
              ' This company is Clear: starting it moves the check back to In review, and its deals cannot be handed over until the new cycle is cleared.'}
          </p>
          <label className="mt-2 block text-caption text-ink-2">
            Reason
            <textarea
              aria-label="Reason"
              className="mt-1 w-full rounded border border-line-strong p-2 text-body"
              value={reason}
              disabled={start.isPending}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          {start.isError && (
            <p role="alert" className="mt-2 text-caption text-negative">
              {start.error instanceof ApiError
                ? start.error.message
                : 'The new cycle could not be started.'}
            </p>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              className="rounded border border-line-strong px-3 py-1.5 text-body"
              onClick={close}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded bg-accent-solid px-3 py-1.5 text-body text-white disabled:opacity-50"
              disabled={start.isPending || (chosen.reason_required && !reason.trim())}
              onClick={() =>
                start.mutate(
                  { kind: chosen.kind as 'RE_KYC' | 'RE_KYB', reason: reason.trim() },
                  { onSuccess: close },
                )
              }
            >
              Start {cycleKindLabel(chosen.kind)}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
