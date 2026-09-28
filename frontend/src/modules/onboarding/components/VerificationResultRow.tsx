/**
 * One company verification result in the workspace — **owner: Developer 4B**
 * (4b-task.md §5.4, §5.9, §5.10; 4B-7).
 *
 * Provenance and placeholder status are the server's (`provenance`, `is_placeholder`)
 * and are never inferred here: a stub is labelled as the RXIL stub, not RXIL, and a
 * placeholder — a row no provider ever ran — does not look like a check in flight.
 */

import { ChevronDown, ChevronUp, CircleDashed } from 'lucide-react';
import { useMemo, useState } from 'react';

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
      className={`border-b border-border py-4 last:border-b-0 ${placeholder ? 'opacity-70' : ''}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{humanize(result.verification_type)}</span>
            {placeholder ? (
              // Deliberately not the PENDING chip a real in-flight check gets.
              <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-strong bg-surface-sunken px-2 py-1 text-xs font-medium text-ink-faint">
                <CircleDashed size={12} /> Not run
              </span>
            ) : (
              <VerificationStatusChip value={result.status} />
            )}
            {result.risk_level && <VerificationStatusChip value={result.risk_level} />}
            {result.review_status && <VerificationStatusChip value={result.review_status} />}
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            {placeholder ? 'Placeholder · no provider ran this check' : provenanceLabel(result)}
            {' · '}
            {formatDateTime(result.performed_at)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted hover:text-ink"
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? 'Hide details' : 'View details'}
        </button>
      </div>
      <EvidenceList note={result.evidence_note} refs={result.evidence_refs} />
      {expanded && (
        <div className="mt-3 grid gap-3 rounded-lg bg-surface-subtle p-3 text-xs md:grid-cols-2">
          <div>
            <span className="text-ink-faint">Provider reference</span>
            <p className="mt-0.5 break-all text-ink">{result.provider_reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-ink-faint">Valid until</span>
            <p className="mt-0.5 text-ink">{formatDateTime(result.valid_until)}</p>
          </div>
          <div className="md:col-span-2">
            <span className="text-ink-faint">Provider result</span>
            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-surface p-3 text-[11px] leading-5 text-ink">
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
