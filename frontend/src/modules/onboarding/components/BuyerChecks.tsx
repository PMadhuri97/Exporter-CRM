/**
 * Checks on a deal's buyer — **owner: Developer 4B** (verification-and-screening.md §6, phase 4B-5).
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
 * Mounted on the deal page, for staff, once the deal has a buyer. On a closed deal
 * the server stops offering `can_record_result` (D17); existing checks stay
 * reviewable.
 *
 * **Legacy (Developer 1, plan P4-5).** Checks are company-keyed now: a buyer company's
 * checks are recorded on its own background-check panel, and a deal shows that company
 * through `CompanyComplianceSummary` — the one compliance summary (task 1.20; mounted
 * by Developer 2's task 2.4 once a deal names a buyer company). This list remains only
 * for a deal whose buyer is still a `deal_buyer` row, the one place that buyer's
 * sanctions and AML can be recorded, until the deal-buyer migration maps it to a
 * company (P4-6) and `deal_buyer` writes are retired (P4-10), when it is removed.
 */

import { useState } from 'react';

import { Icon } from '@/design/icons';
import { formatDateTime, humanize } from '@/lib/format';

import { useVerificationResults } from '../hooks';
import type { BuyerSnapshot, VerificationResult } from '../types';

import { EvidenceList } from './EvidenceList';
import { ManualResultForm } from './ManualResultForm';
import { ReviewChain, ReviewDialog } from './ReviewDialog';
import { BUYER_CHECK_TYPES, provenanceLabel } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

const SECONDARY_BUTTON =
  'rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:bg-paper disabled:opacity-50';

export function BuyerChecks({ dealId, dealBuyerId }: { dealId: string; dealBuyerId: string }) {
  const query = useVerificationResults('BUYER', dealBuyerId);
  const [recording, setRecording] = useState(false);
  const results = query.data?.results ?? [];
  const capabilities = query.data?.capabilities;

  return (
    <section
      data-testid="buyer-checks"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Icon.backgroundCheck size={18} className="text-ink" />
            <h2 className="font-semibold text-ink">Buyer checks</h2>
          </div>
          <p className="mt-1 text-sm text-ink-2">
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
          <p className="text-sm text-ink-2">Loading buyer checks…</p>
        ) : query.isError ? (
          <p role="alert" className="text-sm text-negative">
            Buyer checks could not be loaded.
          </p>
        ) : results.length === 0 ? (
          <p className="text-sm text-ink-2">No checks have been recorded on this buyer yet.</p>
        ) : (
          <ul className="divide-y divide-line">
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
      <p className="mt-1 text-xs text-ink-3">
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
    <div data-testid="buyer-snapshot" className="mt-3 rounded-lg bg-paper p-3 text-xs">
      <p className="text-ink-3">Checked against the buyer as recorded at the time</p>
      <dl className="mt-1 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        <div>
          <dt className="inline text-ink-3">Name </dt>
          <dd className="inline text-ink">{snapshot.name}</dd>
        </div>
        <div>
          <dt className="inline text-ink-3">Country </dt>
          <dd className="inline text-ink">{snapshot.country}</dd>
        </div>
        <div>
          <dt className="inline text-ink-3">Registration no. </dt>
          <dd className="inline break-all text-ink">{snapshot.registration_number ?? '—'}</dd>
        </div>
        <div>
          <dt className="inline text-ink-3">Tax id </dt>
          <dd className="inline break-all text-ink">{snapshot.tax_id ?? '—'}</dd>
        </div>
      </dl>
    </div>
  );
}
