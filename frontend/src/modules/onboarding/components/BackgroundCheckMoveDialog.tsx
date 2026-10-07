/**
 * Recording a background-check decision.
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
 * **Maker-checker.** A move the server marks `approval_required`
 * (CLEAR, FLAGGED, ON_HOLD) is proposed, not recorded: the dialog says so and the
 * button reads "Propose for approval". The check moves only when a second compliance
 * officer approves it. No checker is chosen here: the second person is whoever, in
 * the pool of eligible officers, approves it.
 *
 * **The relationship manager.** Starting the check on an in-pipeline company with no RM
 * needs one in the same request (`relationshipManagerRequired`); the dialog asks for it
 * on the start and sends it with the move.
 */

import { useState } from 'react';

import { RelationshipManagerChoice } from './RelationshipManagerChoice';

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
  initialMove = null,
  relationshipManagerRequired = false,
}: {
  moves: BackgroundCheckMove[];
  blockedReasons: string[];
  isPending: boolean;
  error: string | null;
  onSubmit: (body: {
    to_value: BackgroundCheckState;
    reason: string | null;
    risk_rating: BackgroundCheckRisk | null;
    relationship_manager_user_id: string | null;
  }) => void;
  onCancel: () => void;
  /** The move chosen in the status card (frontend-plan §8.5.1), already selected. */
  initialMove?: BackgroundCheckState | null;
  /** The start needs an RM named in the same request (the server says so). */
  relationshipManagerRequired?: boolean;
}) {
  const [selected, setSelected] = useState<BackgroundCheckState | null>(initialMove);
  const [reason, setReason] = useState('');
  const [risk, setRisk] = useState<BackgroundCheckRisk | ''>('');
  // Set by the choice only when this user may name one; otherwise the start waits.
  const [rmUserId, setRmUserId] = useState<string | null>(null);

  const move = moves.find((candidate) => candidate.to_value === selected) ?? null;
  // CLEAR is offered by the server even while its prerequisites are outstanding, so
  // the screen can explain. Sending it anyway would be a 409.
  const clearIsBlocked = selected === 'CLEAR' && blockedReasons.length > 0;
  // Only the start (the one move to IN_REVIEW a NOT_STARTED check has) asks for an RM.
  const asksForRm = relationshipManagerRequired && selected === 'IN_REVIEW';
  const canSubmit =
    move !== null &&
    !clearIsBlocked &&
    (!asksForRm || rmUserId !== null) &&
    (!move.reason_required || reason.trim().length > 0) &&
    (!move.risk_required || risk !== '');

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h4 className="text-body font-semibold text-ink">Record a decision</h4>

      <fieldset className="mt-3">
        <legend className="text-caption font-medium text-ink-2">What has been decided?</legend>
        <div className="mt-2 flex flex-col gap-1">
          {moves.map((candidate) => (
            <label key={candidate.to_value} className="flex items-center gap-2 text-body">
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
        <p className="mt-3 rounded bg-attention-tint p-2 text-caption text-attention">
          This company cannot be cleared yet: {blockedReasons.map(describeClearBlocker).join('; ')}.
        </p>
      )}

      {asksForRm && (
        <div className="mt-3">
          <RelationshipManagerChoice
            value={rmUserId}
            onChange={setRmUserId}
            action="to start the check"
          />
        </div>
      )}

      {move?.risk_required && (
        <label className="mt-3 block text-body">
          <span className="text-caption font-medium text-ink-2">Risk rating (required)</span>
          <select
            aria-label="Risk rating"
            className="mt-1 w-full rounded border border-line-strong p-2 text-body"
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
        <p data-testid="approval-required-note" className="mt-3 rounded bg-transparent p-2 text-caption text-ink">
          This needs a second compliance officer: it is recorded as a proposal, and the
          check moves only when someone else approves it.
        </p>
      )}

      {move && (
        <label className="mt-3 block text-body">
          <span className="text-caption font-medium text-ink-2">
            {move.reason_required ? 'Reason (required)' : 'Reason (optional)'}
          </span>
          <textarea
            aria-label="Reason"
            rows={3}
            className="mt-1 w-full rounded border border-line-strong p-2 text-body"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      )}

      {error && (
        <p role="alert" className="mt-3 text-caption text-negative">
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
              relationship_manager_user_id: asksForRm ? rmUserId : null,
            })
          }
          className="rounded bg-accent-solid px-3 py-1.5 text-body text-white disabled:opacity-40"
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
          className="rounded border border-line-strong px-3 py-1.5 text-body"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
