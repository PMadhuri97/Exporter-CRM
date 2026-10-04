/**
 * Review — the compliance working day (frontend-plan §8.8), for COMPLIANCE and
 * ADMIN only (`compliance.queue`; the module does not exist for anyone else).
 *
 * The queue on the left: decisions another officer proposed and this user may sign
 * (`GET /background-check/proposals?status=open&awaiting=me`), then companies whose
 * Clear is due for Re-KYC (`GET /background-check/due`). The case on the right is
 * the company's Background check chapter — the same component the dossier shows, so
 * the two never drift apart. `j` / `k` move through the queue; `a` / `x` approve or
 * reject the selected proposal, each through the same confirmation as anywhere else.
 * "In review" (companies mid-check) waits for ask A4 and is not shown until then.
 */

import { lazy, Suspense, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { EmptyLine, PageHeader, Skeleton } from '@/components';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime } from '@/lib/format';
import { usePageShortcuts } from '@/platform/shell';

import { actorLabel } from '../components/actor-label';
import { proposedMoveLabel } from '../components/background-check-labels';
import { ProposalResolveDialog } from '../components/ProposalResolveDialog';
import { RiskChip } from '../components/RiskChip';
import { useProposalsAwaitingMe, useReKycDue } from '../hooks';
import { paths } from '../paths';
import type { BackgroundCheckProposal, BackgroundCheckProposalAction } from '../types';

const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

const QUEUE_LIMIT = 50;

interface Case {
  key: string;
  companyId: string;
  proposal?: BackgroundCheckProposal;
}

function QueueRow({
  selected,
  onSelect,
  title,
  detail,
  extra,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  detail: string;
  extra?: React.ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'relative w-full rounded-md px-3 py-2.5 text-left transition-colors duration-quick',
          selected ? 'bg-surface ring-1 ring-ink' : 'hover:bg-sunken',
        )}
      >
        <span className="block truncate text-body font-medium text-ink">{title}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-caption text-ink-3">
          {detail}
          {extra}
        </span>
      </button>
    </li>
  );
}

export function ReviewPage() {
  const proposals = useProposalsAwaitingMe({ limit: QUEUE_LIMIT, enabled: true });
  const due = useReKycDue({ limit: QUEUE_LIMIT, enabled: true });
  const [params, setParams] = useSearchParams();
  const [resolving, setResolving] = useState<BackgroundCheckProposalAction | null>(null);

  const cases: Case[] = [
    ...(proposals.data?.proposals ?? []).map((proposal) => ({
      key: `p-${proposal.id}`,
      companyId: proposal.company_id,
      proposal,
    })),
    ...(due.data?.companies ?? []).map((row) => ({ key: `d-${row.company_id}`, companyId: row.company_id })),
  ];
  const selectedKey = params.get('case') ?? cases[0]?.key ?? null;
  const selected = cases.find((entry) => entry.key === selectedKey) ?? cases[0] ?? null;

  const select = (entry: Case | undefined) => {
    if (!entry) return;
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set('case', entry.key);
        return next;
      },
      { replace: true },
    );
  };
  const step = (by: number) => {
    const at = cases.findIndex((entry) => entry.key === selected?.key);
    select(cases[Math.max(0, Math.min(cases.length - 1, at + by))]);
  };
  const offered = (selected?.proposal?.allowed_actions ?? []).filter((action) => action !== 'WITHDRAW');
  usePageShortcuts([
    { key: 'j', label: 'Next case', run: () => step(1) },
    { key: 'k', label: 'Previous case', run: () => step(-1) },
    ...(offered.includes('APPROVE')
      ? [{ key: 'a', label: 'Approve the selected proposal', run: () => setResolving('APPROVE' as const) }]
      : []),
    ...(offered.includes('REJECT')
      ? [{ key: 'x', label: 'Reject the selected proposal', run: () => setResolving('REJECT' as const) }]
      : []),
  ]);

  const loading = proposals.isLoading || due.isLoading;

  return (
    <div>
      <PageHeader
        title="Review"
        description="Decisions waiting for a second signature, and companies due for Re-KYC. Choose a case to open its background check."
      />
      <div className="grid gap-8 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <nav aria-label="Review queue" className="space-y-6 xl:sticky xl:top-0 xl:h-fit">
          {loading ? (
            <div className="space-y-2" aria-hidden>
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : (
            <>
              <section aria-label="Awaiting your signature">
                <h2 className="flex items-baseline justify-between text-lead font-semibold text-ink">
                  Awaiting your signature
                  <span className="text-secondary font-normal tabular-nums text-ink-3">
                    {proposals.data?.total ?? 0}
                  </span>
                </h2>
                {proposals.isError ? (
                  <p role="alert" className="mt-2 text-secondary text-negative">Couldn't load the proposals.</p>
                ) : (proposals.data?.proposals ?? []).length === 0 ? (
                  <EmptyLine>Nothing is waiting for your signature.</EmptyLine>
                ) : (
                  <ul className="mt-2 space-y-1">
                    {(proposals.data?.proposals ?? []).map((proposal) => (
                      <QueueRow
                        key={proposal.id}
                        selected={selected?.key === `p-${proposal.id}`}
                        onSelect={() => select(cases.find((entry) => entry.key === `p-${proposal.id}`))}
                        title={proposal.company_name ?? 'Unnamed company'}
                        detail={`${proposedMoveLabel(proposal.to_value)} · by ${actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, ${formatDateTime(proposal.proposed_at)}`}
                        extra={proposal.risk_rating ? <RiskChip risk={proposal.risk_rating} /> : null}
                      />
                    ))}
                  </ul>
                )}
              </section>
              <section aria-label="Re-KYC due">
                <h2 className="flex items-baseline justify-between text-lead font-semibold text-ink">
                  Re-KYC due
                  <span className="text-secondary font-normal tabular-nums text-ink-3">{due.data?.total ?? 0}</span>
                </h2>
                {due.isError ? (
                  <p role="alert" className="mt-2 text-secondary text-negative">Couldn't load the Re-KYC list.</p>
                ) : (due.data?.companies ?? []).length === 0 ? (
                  <EmptyLine>No Clear is due for Re-KYC.</EmptyLine>
                ) : (
                  <ul className="mt-2 space-y-1">
                    {(due.data?.companies ?? []).map((row) => (
                      <QueueRow
                        key={row.company_id}
                        selected={selected?.key === `d-${row.company_id}`}
                        onSelect={() => select(cases.find((entry) => entry.key === `d-${row.company_id}`))}
                        title={row.company_name ?? 'Unnamed company'}
                        detail={`${row.is_expired ? 'Clear expired' : 'Clear expires'} ${formatDate(row.expires_at)}`}
                      />
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </nav>

        <section aria-label="Case" className="min-w-0">
          {selected ? (
            <>
              <p className="mb-4 flex flex-wrap items-center justify-between gap-3 text-secondary text-ink-3">
                <span>
                  {selected.proposal ? 'A proposed decision — approve or reject it below, or press a / x.' : 'Re-KYC due — start the cycle below.'}
                </span>
                <Link to={paths.company(selected.companyId)} className="font-medium text-ink underline underline-offset-[3px]">
                  Open the company
                </Link>
              </p>
              {/* a / x: the same approve-or-reject step, with its confirmation. */}
              {resolving && selected.proposal && (
                <div className="mb-6">
                  <ProposalResolveDialog
                    proposal={selected.proposal}
                    action={resolving}
                    onDone={() => setResolving(null)}
                    onCancel={() => setResolving(null)}
                  />
                </div>
              )}
              <Suspense fallback={<Skeleton className="h-60 rounded-xl" />}>
                <BackgroundCheckPanel key={selected.companyId} customerId={selected.companyId} isStaff />
              </Suspense>
            </>
          ) : (
            !loading && <EmptyLine>The queue is empty. Nothing needs a compliance decision right now.</EmptyLine>
          )}
        </section>
      </div>

    </div>
  );
}
