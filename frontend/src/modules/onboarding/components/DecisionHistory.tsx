/**
 * The background check's decision trail — **owner: Developer 4A** (L4-04, L4-06).
 *
 * Every decision, newest first, with the evidence it rested on. Decisions are
 * append-only: a reopen or reassessment is a **new** decision that supersedes the
 * one before, and nothing here was ever edited — which is why the list shows a
 * chain rather than a current state with an edit history.
 *
 * The evidence is **ids and counts only**. The snapshot pins ids, never contents
 * (contract §6), so there is nothing else to show, and inventing a document name or
 * a check result here would be showing something the decision did not record.
 */

import type { BackgroundCheckDecision, BackgroundCheckState } from '../types';

import { RiskChip } from './RiskChip';

const LABELS: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  MORE_INFO: 'More information needed',
  CLEAR: 'Clear',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

function EvidenceSummary({ decision }: { decision: BackgroundCheckDecision }) {
  const counts = decision.evidence.reduce<Record<string, number>>((totals, item) => {
    totals[item.kind] = (totals[item.kind] ?? 0) + 1;
    return totals;
  }, {});

  if (decision.evidence.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        No evidence was recorded against this decision.
      </p>
    );
  }

  const parts = [
    counts.DOCUMENT && `${counts.DOCUMENT} document${counts.DOCUMENT === 1 ? '' : 's'}`,
    counts.VERIFICATION_RESULT &&
      `${counts.VERIFICATION_RESULT} check${counts.VERIFICATION_RESULT === 1 ? '' : 's'}`,
    counts.SCREENING_ITEM &&
      `${counts.SCREENING_ITEM} screening item${counts.SCREENING_ITEM === 1 ? '' : 's'}`,
  ].filter(Boolean);

  return (
    <p className="text-xs text-slate-500" data-testid="evidence-summary">
      Recorded against {parts.join(', ')}.
    </p>
  );
}

export function DecisionHistory({
  decisions,
  isLoading,
  isError,
}: {
  decisions: BackgroundCheckDecision[];
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading decisions…</p>;
  }
  if (isError) {
    return (
      <p role="alert" className="text-sm text-red-700">
        The decision history could not be loaded.
      </p>
    );
  }
  if (decisions.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No decisions have been recorded for this company yet.
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-3">
      {decisions.map((decision) => (
        <li
          key={decision.id}
          data-testid="decision-row"
          className="rounded border border-slate-200 p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-900">
              {LABELS[decision.from_value]} → {LABELS[decision.to_value]}
            </span>
            <RiskChip risk={decision.risk_rating} />
          </div>
          {decision.reason && (
            <p className="mt-1 text-sm text-slate-700">{decision.reason}</p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            {new Date(decision.decided_at).toLocaleString()}
            {decision.decided_by ? ` · ${decision.decided_by}` : ''}
          </p>
          <EvidenceSummary decision={decision} />
        </li>
      ))}
    </ol>
  );
}
