/**
 * Compliance work — the compliance working day (frontend-plan §8.8), for COMPLIANCE
 * and ADMIN only (`compliance.queue`; the module does not exist for anyone else).
 *
 * The rail on the left is the worklists, computed by the server on every read:
 *
 * - **Awaiting review** — checks nobody has picked up (`?view=awaiting`); the case
 *   header offers **Assign to me**;
 * - **My reviews** — the reviews this user holds, under review, waiting on
 *   information or with their proposal out for approval (`?view=mine`);
 * - **Awaiting your signature** — proposals this user may approve: not their own, not
 *   one they review, not a company they are RM of, and a high-risk Clear only for a
 *   senior approver (`/background-check/proposals?status=open&awaiting=me`);
 * - **Re-KYC due**;
 * - for ADMIN and holders of `compliance:assign` only: **In review (everyone)**,
 *   **Overdue** and **Needs attention** (no one can approve it, returned twice, or a
 *   deactivated reviewer).
 *
 * Each row shows how long it has waited and whether it is due soon or overdue, in
 * business time. The selected case is kept in the URL (`?case=`), and the right side is
 * the company's Background check tab — the same component the company record shows —
 * where the reviewer is claimed, released or reassigned and proposals approved.
 */

import { lazy, Suspense, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { Button, buttonClasses, EmptyLine, PageHeader, Skeleton } from '@/components';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime } from '@/lib/format';
import { useHasPermission } from '@/platform/access';

import { actorLabel } from '../components/actor-label';
import { proposedMoveLabel } from '../components/background-check-labels';
import { RiskChip } from '../components/RiskChip';
import { STAGE_LABEL, waitedFor } from '../components/work-item-labels';
import { DueChip, WorkItemChips } from '../components/WorkItemChips';
import {
  useChangeReviewer,
  useComplianceWork,
  useProposalsAwaitingMe,
  useReKycDue,
} from '../hooks';
import { paths } from '../paths';
import type { BackgroundCheckProposal, ComplianceWorkItem, ComplianceWorkView } from '../types';

const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

const QUEUE_LIMIT = 50;

type Section = ComplianceWorkView | 'signature' | 'rekyc';

interface Case {
  key: string;
  section: Section;
  companyId: string;
  companyName: string;
  proposal?: BackgroundCheckProposal;
  item?: ComplianceWorkItem;
}

const SECTION_TITLE: Record<Section, string> = {
  awaiting: 'Awaiting review',
  mine: 'My reviews',
  signature: 'Awaiting your signature',
  rekyc: 'Re-KYC due',
  in_review: 'In review (everyone)',
  overdue: 'Overdue',
  needs_attention: 'Needs attention',
};

const SECTION_EMPTY: Record<Section, string> = {
  awaiting: 'Every started check has a reviewer.',
  mine: 'You hold no reviews.',
  signature: 'Nothing is waiting for your signature.',
  rekyc: 'No Clear is due for Re-KYC.',
  in_review: 'No checks are under review.',
  overdue: 'Nothing is overdue.',
  needs_attention: 'Nothing needs your attention.',
};

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
  extra?: ReactNode;
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

/** "In review · waited 3h · with Priya" — never an identifier or a reason. */
function itemDetail(item: ComplianceWorkItem, section: Section): string {
  const parts = [STAGE_LABEL[item.stage], `waited ${waitedFor(item.waiting_since)}`];
  if (section !== 'mine' && item.reviewer_name) parts.push(`with ${item.reviewer_name}`);
  if (item.stage === 'approval' && item.proposed_by_name) parts.push(`by ${item.proposed_by_name}`);
  return parts.join(' · ');
}

function SectionBlock({
  section,
  loading,
  failed,
  children,
  count,
}: {
  section: Section;
  loading: boolean;
  failed: boolean;
  count: number;
  children: ReactNode;
}) {
  return (
    <section aria-label={SECTION_TITLE[section]}>
      <h2 className="flex items-baseline justify-between text-heading font-semibold text-ink">
        {SECTION_TITLE[section]}
        <span className="text-secondary font-normal tabular-nums text-ink-3">{count}</span>
      </h2>
      {loading ? (
        <Skeleton className="mt-2 h-12" />
      ) : failed ? (
        <p role="alert" className="mt-2 text-secondary text-negative">
          Couldn't load this list.
        </p>
      ) : count === 0 ? (
        <EmptyLine>{SECTION_EMPTY[section]}</EmptyLine>
      ) : (
        <ul className="mt-2 space-y-1">{children}</ul>
      )}
    </section>
  );
}

/** "Assign to me" for a case from Awaiting review. */
function ClaimButton({ companyId }: { companyId: string }) {
  const change = useChangeReviewer(companyId);
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="primary"
        loading={change.isPending}
        onClick={() => change.mutate({ kind: 'CLAIM' })}
      >
        Assign to me
      </Button>
      {change.isError && (
        <span role="alert" className="text-caption text-negative">
          {change.error instanceof ApiError ? change.error.message : 'Could not take the review.'}
        </span>
      )}
    </div>
  );
}

export function ApprovalsPage() {
  const lead = useHasPermission('compliance:assign');
  const awaiting = useComplianceWork('awaiting');
  const mine = useComplianceWork('mine');
  const inReview = useComplianceWork('in_review', lead);
  const overdue = useComplianceWork('overdue', lead);
  const attention = useComplianceWork('needs_attention', lead);
  const proposals = useProposalsAwaitingMe({ limit: QUEUE_LIMIT, enabled: true });
  const due = useReKycDue({ limit: QUEUE_LIMIT, enabled: true });
  const [params, setParams] = useSearchParams();

  const work: [ComplianceWorkView, typeof awaiting][] = [
    ['awaiting', awaiting],
    ['mine', mine],
    ...(lead
      ? ([
          ['needs_attention', attention],
          ['overdue', overdue],
          ['in_review', inReview],
        ] as [ComplianceWorkView, typeof awaiting][])
      : []),
  ];

  const workCases = (view: ComplianceWorkView, items: ComplianceWorkItem[]): Case[] =>
    items.map((item) => ({
      key: `${view}-${item.company_id}`,
      section: view,
      companyId: item.company_id,
      companyName: item.company_name ?? 'Unnamed company',
      item,
    }));

  const cases: Case[] = [
    ...workCases('awaiting', awaiting.data?.items ?? []),
    ...workCases('mine', mine.data?.items ?? []),
    ...(proposals.data?.proposals ?? []).map((proposal) => ({
      key: `p-${proposal.id}`,
      section: 'signature' as const,
      companyId: proposal.company_id,
      companyName: proposal.company_name ?? 'Unnamed company',
      proposal,
    })),
    ...(due.data?.companies ?? []).map((row) => ({
      key: `d-${row.company_id}`,
      section: 'rekyc' as const,
      companyId: row.company_id,
      companyName: row.company_name ?? 'Unnamed company',
    })),
    ...(lead
      ? [
          ...workCases('needs_attention', attention.data?.items ?? []),
          ...workCases('overdue', overdue.data?.items ?? []),
          ...workCases('in_review', inReview.data?.items ?? []),
        ]
      : []),
  ];
  const selectedKey = params.get('case') ?? cases[0]?.key ?? null;
  const selected = cases.find((entry) => entry.key === selectedKey) ?? cases[0] ?? null;

  const select = (key: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set('case', key);
        return next;
      },
      { replace: true },
    );
  };

  const loading = awaiting.isLoading && mine.isLoading && proposals.isLoading && due.isLoading;

  const workSection = (view: ComplianceWorkView, query: typeof awaiting) => (
    <SectionBlock
      key={view}
      section={view}
      loading={query.isLoading}
      failed={query.isError}
      count={query.data?.total ?? 0}
    >
      {(query.data?.items ?? []).map((item) => (
        <QueueRow
          key={item.company_id}
          selected={selected?.key === `${view}-${item.company_id}`}
          onSelect={() => select(`${view}-${item.company_id}`)}
          title={item.company_name ?? 'Unnamed company'}
          detail={itemDetail(item, view)}
          extra={<WorkItemChips item={item} />}
        />
      ))}
    </SectionBlock>
  );

  return (
    <div>
      <PageHeader
        title="Compliance work"
        description="Checks waiting for a reviewer, your reviews, decisions waiting for a second signature, and companies due for Re-KYC. Choose a case to open its background check."
      />
      <div className="grid gap-4 xl:grid-cols-[22.5rem_minmax(0,1fr)] xl:items-start">
        <nav aria-label="Review queue" className="space-y-6 rounded border border-line bg-surface p-4 xl:sticky xl:top-0 xl:h-fit">
          {work.slice(0, 2).map(([view, query]) => workSection(view, query))}
          <SectionBlock
            section="signature"
            loading={proposals.isLoading}
            failed={proposals.isError}
            count={proposals.data?.total ?? 0}
          >
            {(proposals.data?.proposals ?? []).map((proposal) => (
              <QueueRow
                key={proposal.id}
                selected={selected?.key === `p-${proposal.id}`}
                onSelect={() => select(`p-${proposal.id}`)}
                title={proposal.company_name ?? 'Unnamed company'}
                detail={`${proposedMoveLabel(proposal.to_value)} · by ${actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, ${formatDateTime(proposal.proposed_at)}`}
                extra={
                  <>
                    {proposal.risk_rating && <RiskChip risk={proposal.risk_rating} />}
                    <DueChip
                      dueAt={proposal.due_at}
                      isOverdue={proposal.is_overdue}
                      isDueSoon={proposal.is_due_soon}
                    />
                  </>
                }
              />
            ))}
          </SectionBlock>
          <SectionBlock
            section="rekyc"
            loading={due.isLoading}
            failed={due.isError}
            count={due.data?.total ?? 0}
          >
            {(due.data?.companies ?? []).map((row) => (
              <QueueRow
                key={row.company_id}
                selected={selected?.key === `d-${row.company_id}`}
                onSelect={() => select(`d-${row.company_id}`)}
                title={row.company_name ?? 'Unnamed company'}
                detail={`${row.is_expired ? 'Clear expired' : 'Clear expires'} ${formatDate(row.expires_at)}`}
              />
            ))}
          </SectionBlock>
          {work.slice(2).map(([view, query]) => workSection(view, query))}
        </nav>

        <section aria-label="Case" className="min-w-0">
          {selected ? (
            <>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded border border-line bg-surface px-4 py-3">
                <div className="min-w-0">
                  <p className="text-caption text-ink-3">{SECTION_TITLE[selected.section]}</p>
                  <p className="truncate text-title font-semibold text-ink">{selected.companyName}</p>
                  <p className="text-secondary text-ink-2">
                    {selected.section === 'signature'
                      ? 'Approve or reject it in the status card below.'
                      : selected.section === 'rekyc'
                        ? 'Start the cycle below.'
                        : selected.section === 'awaiting'
                          ? 'Nobody is reviewing this yet.'
                          : 'The background check is below.'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {selected.section === 'awaiting' && <ClaimButton companyId={selected.companyId} />}
                  <Link to={paths.company(selected.companyId)} className={buttonClasses()}>
                    Open company
                  </Link>
                </div>
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
