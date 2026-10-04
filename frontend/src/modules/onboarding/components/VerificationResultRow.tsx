/**
 * One company verification result in the workspace — **owner: Developer 4B**
 * (verification-and-screening.md §4, §8, §9; 4B-7).
 *
 * Provenance and placeholder status are the server's (`provenance`, `is_placeholder`)
 * and are never inferred here: a stub is labelled as the RXIL stub, not RXIL, and a
 * placeholder — a row no provider ever ran — does not look like a check in flight.
 */

import { useMemo, useState } from 'react';

import { Icon } from '@/design/icons';
import { formatDateTime, humanize } from '@/lib/format';

import type { VerificationResult } from '../types';

import { EvidenceList } from './EvidenceList';
import { ReviewChain, ReviewDialog } from './ReviewDialog';
import { provenanceLabel } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

export function VerificationResultRow({
  result,
  customerId,
  canReview,
  onStale,
}: {
  result: VerificationResult;
  customerId: string;
  canReview: boolean;
  onStale: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const normalized = useMemo(
    () => JSON.stringify(result.normalized_result, null, 2),
    [result.normalized_result],
  );
  const placeholder = result.is_placeholder;

  return (
    <div
      data-testid="verification-result"
      className={`border-b border-line py-4 last:border-b-0 ${placeholder ? 'opacity-70' : ''}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{humanize(result.verification_type)}</span>
            {placeholder ? (
              // Deliberately not the PENDING chip a real in-flight check gets.
              <span className="inline-flex items-center gap-1 rounded-sm border border-dashed border-line-strong bg-sunken px-2 py-1 text-xs font-medium text-ink-3">
                <Icon.notStarted size={12} /> Not run
              </span>
            ) : (
              <VerificationStatusChip value={result.status} />
            )}
            {result.risk_level && <VerificationStatusChip value={result.risk_level} />}
            {result.review_status && <VerificationStatusChip value={result.review_status} />}
          </div>
          <p className="mt-1 text-xs text-ink-3">
            {placeholder ? 'Placeholder · no provider ran this check' : provenanceLabel(result)}
            {' · '}
            {formatDateTime(result.performed_at)}
          </p>
          {result.entity_type === 'BUYER' && (
            // Company-keyed checks (P4-5): a check recorded on a deal, against that
            // deal's buyer, before the buyer was a company — now one of its checks.
            <p data-testid="recorded-as-buyer-check" className="mt-0.5 text-xs text-ink-3">
              Recorded on a deal as the buyer&apos;s check
              {result.subject_snapshot?.name ? ` (${result.subject_snapshot.name})` : ''}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink"
        >
          {expanded ? <Icon.caretUp size={14} /> : <Icon.caretDown size={14} />}
          {expanded ? 'Hide details' : 'View details'}
        </button>
      </div>
      <EvidenceList note={result.evidence_note} refs={result.evidence_refs} />
      {expanded && (
        <div className="mt-3 grid gap-3 rounded-lg bg-paper p-3 text-xs md:grid-cols-2">
          <div>
            <span className="text-ink-3">Provider reference</span>
            <p className="mt-0.5 break-all text-ink">{result.provider_reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-ink-3">Valid until</span>
            <p className="mt-0.5 text-ink">{formatDateTime(result.valid_until)}</p>
          </div>
          <div className="md:col-span-2">
            <span className="text-ink-3">Provider result</span>
            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-surface p-3 text-[11px] leading-5 text-ink">
              {normalized}
            </pre>
          </div>
        </div>
      )}
      <ReviewChain reviews={result.reviews} />
      <ReviewDialog
        result={result}
        entityType="EXPORTER"
        entityReference={customerId}
        canReview={canReview}
        onStale={onStale}
      />
    </div>
  );
}
