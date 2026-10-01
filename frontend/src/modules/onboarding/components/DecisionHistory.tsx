/**
 * The background check's decision trail — **owner: Developer 4A** (L4-04, L4-06);
 * evidence per decision and cycle grouping by **Developer 1** (plans P2-1c, P2-3d).
 *
 * Every decision, newest first, with the evidence it rested on. Decisions are
 * append-only: a reopen or reassessment is a **new** decision that supersedes the
 * one before, and nothing here was ever edited — which is why the list shows a
 * chain rather than a current state with an edit history.
 *
 * Each row shows the counts of what it pinned and opens to the evidence itself,
 * resolved by the server (`…/decisions/{id}/evidence`): each check with its result,
 * who recorded it and when, its provenance and its evidence; each screening answer as
 * it was given; each document. What is shown is what the decision rested on — pinned
 * rows are never edited — and a review recorded since is flagged, not substituted.
 *
 * With more than one check cycle, the decisions are grouped by cycle, newest first
 * (a Re-KYC / Re-KYB starts a cycle; earlier ones stay readable).
 */

import { useState } from 'react';

import { formatDateTime, humanize } from '@/lib/format';

import { useDecisionEvidence } from '../hooks';
import type {
  BackgroundCheckDecision,
  BackgroundCheckState,
  DecisionEvidenceItem,
} from '../types';

import { actorLabel } from './actor-label';
import { EvidenceList } from './EvidenceList';
import { RiskChip } from './RiskChip';
import { provenanceLabel, verificationTypeLabel } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

const LABELS: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  MORE_INFO: 'More information needed',
  CLEAR: 'Clear',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

/** `rules_version` → words. A decision recorded before rules were versioned has none. */
function rulesLabel(version: string | null | undefined): string {
  if (!version || version === 'clear-2026-09-28-8items') return 'eight-item checklist rules';
  if (version === 'clear-2026-10-01-7items') return 'seven-item checklist rules';
  return version;
}

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

function ResolvedItem({ item }: { item: DecisionEvidenceItem }) {
  if (item.verification) {
    const check = item.verification;
    return (
      <li data-testid="decision-evidence-check" className="rounded border border-slate-100 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-900">
            {verificationTypeLabel(check.verification_type)} check
          </span>
          <VerificationStatusChip value={check.status} />
          {check.risk_level && <VerificationStatusChip value={check.risk_level} />}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {check.is_placeholder
            ? 'Placeholder · no provider ran this check'
            : provenanceLabel(check)}
          {' · '}
          {formatDateTime(check.performed_at)}
          {check.recorded_by && ` · recorded by ${actorLabel(check.recorded_by_name, check.recorded_by)}`}
        </p>
        {check.pinned_review ? (
          <p className="mt-1 text-xs text-slate-600">
            Review relied on: {humanize(check.pinned_review.review_status)} by{' '}
            {actorLabel(check.pinned_review.reviewed_by_name, check.pinned_review.reviewed_by)},{' '}
            {formatDateTime(check.pinned_review.reviewed_at)}
            {check.pinned_review.note && ` — ${check.pinned_review.note}`}
          </p>
        ) : (
          <p className="mt-1 text-xs text-slate-500">Not reviewed when the decision was taken.</p>
        )}
        {check.review_superseded && (
          <p data-testid="review-superseded" className="mt-1 text-xs font-medium text-amber-700">
            A later review has been recorded since this decision.
          </p>
        )}
        <EvidenceList note={check.evidence_note} refs={check.evidence_refs} />
      </li>
    );
  }
  if (item.screening_item) {
    const answer = item.screening_item;
    return (
      <li data-testid="decision-evidence-screening" className="rounded border border-slate-100 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-900">{answer.label}</span>
          <VerificationStatusChip value={answer.status} />
          {answer.retired && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
              Retired item
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Answered by {actorLabel(answer.reviewed_by_name, answer.reviewed_by)}
          {answer.reviewed_at && `, ${formatDateTime(answer.reviewed_at)}`} · Manual (person)
        </p>
        <EvidenceList note={answer.comment} refs={answer.evidence_refs} />
      </li>
    );
  }
  if (item.document) {
    const document = item.document;
    return (
      <li data-testid="decision-evidence-document" className="rounded border border-slate-100 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-900">{document.file_name}</span>
          <VerificationStatusChip value={document.scan_status} />
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {humanize(document.category)} · uploaded {formatDateTime(document.uploaded_at)}
          {document.uploaded_by && ` by ${actorLabel(document.uploaded_by_name, document.uploaded_by)}`}
        </p>
        {document.is_downloadable && (
          <EvidenceList note={null} refs={[{ type: 'document', ref: document.crm_document_id }]} />
        )}
      </li>
    );
  }
  return (
    <li className="text-xs text-slate-500">
      A pinned {humanize(item.kind).toLowerCase()} could not be found.
    </li>
  );
}

function DecisionEvidenceDetail({
  customerId,
  decision,
}: {
  customerId: string;
  decision: BackgroundCheckDecision;
}) {
  const evidence = useDecisionEvidence(customerId, decision.id, true);
  if (evidence.isLoading) {
    return <p className="mt-2 text-xs text-slate-500">Loading the evidence…</p>;
  }
  if (evidence.isError || !evidence.data) {
    return (
      <p role="alert" className="mt-2 text-xs text-red-700">
        The evidence could not be loaded.
      </p>
    );
  }
  return (
    <div data-testid="decision-evidence" className="mt-2">
      <p className="text-xs text-slate-500">Taken under the {rulesLabel(evidence.data.rules_version)}.</p>
      {evidence.data.items.length > 0 && (
        <ul className="mt-2 flex flex-col gap-2">
          {evidence.data.items.map((item, index) => (
            <ResolvedItem key={`${item.kind}-${index}`} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DecisionRow({
  decision,
  customerId,
}: {
  decision: BackgroundCheckDecision;
  customerId?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li data-testid="decision-row" className="rounded border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-900">
          {LABELS[decision.from_value]} → {LABELS[decision.to_value]}
        </span>
        <RiskChip risk={decision.risk_rating} />
      </div>
      {decision.reason && <p className="mt-1 text-sm text-slate-700">{decision.reason}</p>}
      <p className="mt-1 text-xs text-slate-500">
        {formatDateTime(decision.decided_at)}
        {decision.decided_by ? ` · ${actorLabel(decision.decided_by_name, decision.decided_by)}` : ''}
      </p>
      <EvidenceSummary decision={decision} />
      {customerId && (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className="mt-1 text-xs font-medium text-brand-600 hover:underline"
          >
            {open ? 'Hide evidence' : 'Show evidence'}
          </button>
          {open && <DecisionEvidenceDetail customerId={customerId} decision={decision} />}
        </>
      )}
    </li>
  );
}

export function DecisionHistory({
  decisions,
  isLoading,
  isError,
  customerId,
}: {
  decisions: BackgroundCheckDecision[];
  isLoading: boolean;
  isError: boolean;
  /** The company, so a row can open its resolved evidence. Omitted: counts only. */
  customerId?: string;
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

  // Grouped by cycle only when there is more than one; the server resolves a legacy
  // decision's cycle, so `cycle_number` is set on every decision of a company with one.
  const cycles = [...new Set(decisions.map((decision) => decision.cycle_number ?? null))];
  if (cycles.length <= 1) {
    return (
      <ol className="flex flex-col gap-3">
        {decisions.map((decision) => (
          <DecisionRow key={decision.id} decision={decision} customerId={customerId} />
        ))}
      </ol>
    );
  }
  const current = Math.max(...cycles.map((number) => number ?? 0));
  return (
    <div className="flex flex-col gap-4">
      {cycles.map((number) => (
        <section key={number ?? 'none'} data-testid="decision-cycle" data-cycle={number ?? ''}>
          <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {number === null ? 'Earlier decisions' : `Cycle ${number}`}
            {number === current && ' (current)'}
          </h5>
          <ol className="flex flex-col gap-3">
            {decisions
              .filter((decision) => (decision.cycle_number ?? null) === number)
              .map((decision) => (
                <DecisionRow key={decision.id} decision={decision} customerId={customerId} />
              ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
