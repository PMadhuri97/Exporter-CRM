/**
 * Approvals — the compliance working day (frontend-plan §8.8), for COMPLIANCE and
 * ADMIN only (`compliance.queue`; the module does not exist for anyone else).
 *
 * The queue on the left: decisions another officer proposed and this user may sign
 * (`GET /background-check/proposals?status=open&awaiting=me`), then companies whose
 * Clear is due for Re-KYC (`GET /background-check/due`), as a split view (§6.13):
 * the selected case is kept in the URL (`?case=`). The case on the right is the
 * company's Background check tab — the same component the company record shows, so
 * the two never drift apart; *Approve* and *Reject* are in its status card.
 * "In review" (companies mid-check) waits for the backend to serve it and is not shown until then.
 */

import { lazy, Suspense } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { buttonClasses, EmptyLine, PageHeader, Skeleton } from '@/components';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime } from '@/lib/format';

import { actorLabel } from '../components/actor-label';
import { proposedMoveLabel } from '../components/background-check-labels';
import { RiskChip } from '../components/RiskChip';
import { useProposalsAwaitingMe, useReKycDue } from '../hooks';
import { paths } from '../paths';
import type { BackgroundCheckProposal } from '../types';

const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

const QUEUE_LIMIT = 50;

interface Case {
  key: string;
  companyId: string;
  companyName: string;
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
        // The selected item, as in a split view (§6.13): a blue tint and a bar.
        className={cn(
          'relative w-full rounded px-3 py-2.5 text-left transition-colors duration-quick',
          selected
            ? 'bg-accent-tint before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-r before:bg-accent'
            : 'hover:bg-sunken',
        )}
      >
        <span className={cn('block truncate text-body font-semibold', selected ? 'text-accent' : 'text-ink')}>
          {title}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-caption text-ink-3">
          {detail}
          {extra}
        </span>
      </button>
    </li>
  );
}

export function ApprovalsPage() {
  const proposals = useProposalsAwaitingMe({ limit: QUEUE_LIMIT, enabled: true });
  const due = useReKycDue({ limit: QUEUE_LIMIT, enabled: true });
  const [params, setParams] = useSearchParams();

  const cases: Case[] = [
    ...(proposals.data?.proposals ?? []).map((proposal) => ({
      key: `p-${proposal.id}`,
      companyId: proposal.company_id,
      companyName: proposal.company_name ?? 'Unnamed company',
      proposal,
    })),
    ...(due.data?.companies ?? []).map((row) => ({
      key: `d-${row.company_id}`,
      companyId: row.company_id,
      companyName: row.company_name ?? 'Unnamed company',
    })),
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

  const loading = proposals.isLoading || due.isLoading;

  return (
    <div>
      <PageHeader
        title="Approvals"
        description="Decisions waiting for a second signature, and companies due for Re-KYC. Choose a case to open its background check."
      />
      <div className="grid gap-4 xl:grid-cols-[22.5rem_minmax(0,1fr)] xl:items-start">
        <nav aria-label="Review queue" className="space-y-6 rounded border border-line bg-surface p-4 xl:sticky xl:top-0 xl:h-fit">
          {loading ? (
            <div className="space-y-2" aria-hidden>
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : (
            <>
              <section aria-label="Awaiting your signature">
                <h2 className="flex items-baseline justify-between text-heading font-semibold text-ink">
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
                <h2 className="flex items-baseline justify-between text-heading font-semibold text-ink">
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
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded border border-line bg-surface px-4 py-3">
                <div className="min-w-0">
                  <p className="text-caption text-ink-3">
                    {selected.proposal ? 'Proposed decision' : 'Re-KYC due'}
                  </p>
                  <p className="truncate text-title font-semibold text-ink">{selected.companyName}</p>
                  <p className="text-secondary text-ink-2">
                    {selected.proposal ? 'Approve or reject it in the status card below.' : 'Start the cycle below.'}
                  </p>
                </div>
                <Link to={paths.company(selected.companyId)} className={buttonClasses()}>
                  Open company
                </Link>
              </div>
              <Suspense fallback={<Skeleton className="h-60 rounded" />}>
                <BackgroundCheckPanel key={selected.companyId} customerId={selected.companyId} isStaff />
              </Suspense>
            </>
          ) : (
            !loading && (
              <div className="rounded border border-line bg-surface px-4 py-3">
                <EmptyLine className="py-0">The queue is empty. Nothing needs a compliance decision right now.</EmptyLine>
              </div>
            )
          )}
        </section>
      </div>

    </div>
  );
}
