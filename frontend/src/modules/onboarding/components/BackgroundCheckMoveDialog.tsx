/**
 * Recording a background-check decision — **owner: Developer 4A** (L4-03).
 *
 * **Offers only what the server offered.** The moves, whether each needs a reason,
 * and whether each needs a risk rating all come from `allowed_moves`; this component
 * holds no move table and no role list. A rule change on the server changes what this
 * shows, with no edit here.
 *
 * The reason box is required exactly when the server says so, so the person is asked
 * before submitting rather than shown a 422 afterwards — and the same for the risk
 * rating on `CLEAR`.
 *
 * **A risk rating is sent only with a move that asks for one.** Choosing a rating for
 * `CLEAR` and then switching to another move clears it; otherwise the hidden value
 * would ride along on, say, a `FLAGGED` decision — which is append-only — and become
 * the company's displayed risk. The server refuses that too
 * (`BACKGROUND_CHECK_RISK_NOT_ALLOWED`); this keeps the screen from ever trying.
 *
 * **Maker-checker (Developer 1, P3-1c).** A move the server marks `approval_required`
 * (CLEAR, FLAGGED, ON_HOLD) is proposed, not recorded: the dialog says so and the
 * button reads "Propose for approval". The check moves only when a second compliance
 * officer approves it.
 */

import { useState } from 'react';

import type {
  BackgroundCheckMove,
  BackgroundCheckRisk,
  BackgroundCheckState,
} from '../types';
import { describeClearBlocker } from './background-check-labels';

const MOVE_LABELS: Partial<Record<BackgroundCheckState, string>> = {
  IN_REVIEW: 'Move to in review',
  CLEAR: 'Clear this company',
  MORE_INFO: 'Ask for more information',
  FLAGGED: 'Flag this company',
  ON_HOLD: 'Put on hold',
};

const RISKS: BackgroundCheckRisk[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

export function BackgroundCheckMoveDialog({
  moves,
  blockedReasons,
  isPending,
  error,
  onSubmit,
  onCancel,
}: {
  moves: BackgroundCheckMove[];
  blockedReasons: string[];
  isPending: boolean;
  error: string | null;
  onSubmit: (body: {
    to_value: BackgroundCheckState;
    reason: string | null;
    risk_rating: BackgroundCheckRisk | null;
  }) => void;
  onCancel: () => void;
}) {
  const [selected, setSelected] = useState<BackgroundCheckState | null>(null);
  const [reason, setReason] = useState('');
  const [risk, setRisk] = useState<BackgroundCheckRisk | ''>('');

  const move = moves.find((candidate) => candidate.to_value === selected) ?? null;
  // CLEAR is offered by the server even while its prerequisites are outstanding, so
  // the screen can explain. Sending it anyway would be a 409.
  const clearIsBlocked = selected === 'CLEAR' && blockedReasons.length > 0;
  const canSubmit =
    move !== null &&
    !clearIsBlocked &&
    (!move.reason_required || reason.trim().length > 0) &&
    (!move.risk_required || risk !== '');

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h4 className="text-sm font-semibold text-slate-900">Record a decision</h4>

      <fieldset className="mt-3">
        <legend className="text-xs font-medium text-slate-600">What has been decided?</legend>
        <div className="mt-2 flex flex-col gap-1">
          {moves.map((candidate) => (
            <label key={candidate.to_value} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="to_value"
                value={candidate.to_value}
                checked={selected === candidate.to_value}
                onChange={() => {
                  setSelected(candidate.to_value);
                  setRisk('');
                }}
              />
              {MOVE_LABELS[candidate.to_value] ?? candidate.to_value}
            </label>
          ))}
        </div>
      </fieldset>

      {clearIsBlocked && (
        <p className="mt-3 rounded bg-amber-50 p-2 text-xs text-amber-800">
          This company cannot be cleared yet: {blockedReasons.map(describeClearBlocker).join('; ')}.
        </p>
      )}

      {move?.risk_required && (
        <label className="mt-3 block text-sm">
          <span className="text-xs font-medium text-slate-600">Risk rating (required)</span>
          <select
            aria-label="Risk rating"
            className="mt-1 w-full rounded border border-slate-300 p-2 text-sm"
            value={risk}
            onChange={(event) => setRisk(event.target.value as BackgroundCheckRisk | '')}
          >
            <option value="">Choose a risk rating…</option>
            {RISKS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      )}

      {move?.approval_required && (
        <p data-testid="approval-required-note" className="mt-3 rounded bg-violet-50 p-2 text-xs text-violet-800">
          This needs a second compliance officer: it is recorded as a proposal, and the
          check moves only when someone else approves it.
        </p>
      )}

      {move && (
        <label className="mt-3 block text-sm">
          <span className="text-xs font-medium text-slate-600">
            {move.reason_required ? 'Reason (required)' : 'Reason (optional)'}
          </span>
          <textarea
            aria-label="Reason"
            rows={3}
            className="mt-1 w-full rounded border border-slate-300 p-2 text-sm"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      )}

      {error && (
        <p role="alert" className="mt-3 text-xs text-red-700">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          disabled={!canSubmit || isPending}
          onClick={() =>
            move &&
            onSubmit({
              to_value: move.to_value,
              reason: reason.trim() || null,
              risk_rating: move.risk_required && risk !== '' ? risk : null,
            })
          }
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
        >
          {isPending
            ? move?.approval_required
              ? 'Proposing…'
              : 'Recording…'
            : move?.approval_required
              ? 'Propose for approval'
              : 'Record decision'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
