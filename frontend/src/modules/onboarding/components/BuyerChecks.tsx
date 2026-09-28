/**
 * Checks on a deal's buyer — **owner: Developer 4B** (4b-task.md §5.7, phase 4B-5).
 *
 * A buyer check is recorded against the buyer (`deal_buyer.id`), never the company,
 * and never moves the company's background check (architecture §3.5, decision 9).
 * Each check keeps the buyer's identity as it was when the check was recorded
 * (`subject_snapshot`), because the deal's buyer can later be edited in place. The
 * server masks the snapshot's registration number and tax id for roles that may not
 * see them; this component shows exactly what it is sent.
 *
 * What the viewer may do comes from the server (`capabilities`), never from a role
 * comparison here. Recording and reviewing use the same `ManualResultForm` and
 * `ReviewDialog` as the company workspace: the buyer's evidence documents are its
 * deal's.
 *
 * **Not mounted, and not exported from `components/index.ts`.** Developer 3 mounts it
 * on the deal page after the merge (one import, one element).
 */

import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { formatDateTime, humanize } from '@/lib/format';

import { useVerificationResults } from '../hooks';
import type { BuyerSnapshot, VerificationResult } from '../types';

import { EvidenceList } from './EvidenceList';
import { ManualResultForm } from './ManualResultForm';
import { ReviewChain, ReviewDialog } from './ReviewDialog';
import { BUYER_CHECK_TYPES, provenanceLabel } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

const SECONDARY_BUTTON =
  'rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:bg-surface-subtle disabled:opacity-50';

export function BuyerChecks({ dealId, dealBuyerId }: { dealId: string; dealBuyerId: string }) {
  const query = useVerificationResults('BUYER', dealBuyerId);
  const [recording, setRecording] = useState(false);
  const results = query.data?.results ?? [];
  const capabilities = query.data?.capabilities;

  return (
    <section
      data-testid="buyer-checks"
      className="rounded-lg border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-brand-600" />
            <h2 className="font-semibold text-ink">Buyer checks</h2>
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            Checks on this deal&apos;s buyer. They never change the company&apos;s background
            check.
          </p>
        </div>
        {capabilities?.can_record_result && !recording && (
          <button type="button" className={SECONDARY_BUTTON} onClick={() => setRecording(true)}>
            Record a check
          </button>
        )}
      </div>

      {recording && capabilities?.can_record_result && (
        <ManualResultForm
          entityType="BUYER"
          entityReference={dealBuyerId}
          checkTypes={BUYER_CHECK_TYPES}
          documentOwner={{ kind: 'deal', id: dealId }}
          onClose={() => setRecording(false)}
        />
      )}

      <div className="mt-4">
        {query.isLoading ? (
          <p className="text-sm text-ink-muted">Loading buyer checks…</p>
        ) : query.isError ? (
          <p role="alert" className="text-sm text-red-700">
            Buyer checks could not be loaded.
          </p>
        ) : results.length === 0 ? (
          <p className="text-sm text-ink-muted">No checks have been recorded on this buyer yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {results.map((result) => (
              <BuyerCheckRow
                key={result.id}
                result={result}
                dealBuyerId={dealBuyerId}
                canReview={capabilities?.can_review ?? false}
                onStale={() => void query.refetch()}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function BuyerCheckRow({
  result,
  dealBuyerId,
  canReview,
  onStale,
}: {
  result: VerificationResult;
  dealBuyerId: string;
  canReview: boolean;
  onStale: () => void;
}) {
  return (
    <li data-testid="buyer-check" className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-ink">{humanize(result.verification_type)}</span>
        <VerificationStatusChip value={result.status} />
        {result.risk_level && <VerificationStatusChip value={result.risk_level} />}
        {result.review_status && <VerificationStatusChip value={result.review_status} />}
      </div>
      <p className="mt-1 text-xs text-ink-faint">
        {result.is_placeholder ? 'Placeholder · no provider ran this check' : provenanceLabel(result)}
        {' · '}
        {formatDateTime(result.performed_at)}
      </p>
      {result.subject_snapshot && <SubjectSnapshot snapshot={result.subject_snapshot} />}
      <EvidenceList note={result.evidence_note} refs={result.evidence_refs} />
      <ReviewChain reviews={result.reviews} />
      <ReviewDialog
        result={result}
        entityType="BUYER"
        entityReference={dealBuyerId}
        canReview={canReview}
        onStale={onStale}
      />
    </li>
  );
}

function SubjectSnapshot({ snapshot }: { snapshot: BuyerSnapshot }) {
  return (
    <div data-testid="buyer-snapshot" className="mt-3 rounded-lg bg-surface-subtle p-3 text-xs">
      <p className="text-ink-faint">Checked against the buyer as recorded at the time</p>
      <dl className="mt-1 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        <div>
          <dt className="inline text-ink-faint">Name </dt>
          <dd className="inline text-ink">{snapshot.name}</dd>
        </div>
        <div>
          <dt className="inline text-ink-faint">Country </dt>
          <dd className="inline text-ink">{snapshot.country}</dd>
        </div>
        <div>
          <dt className="inline text-ink-faint">Registration no. </dt>
          <dd className="inline break-all text-ink">{snapshot.registration_number ?? '—'}</dd>
        </div>
        <div>
          <dt className="inline text-ink-faint">Tax id </dt>
          <dd className="inline break-all text-ink">{snapshot.tax_id ?? '—'}</dd>
        </div>
      </dl>
    </div>
  );
}
