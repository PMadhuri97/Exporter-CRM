/**
 * Compliance work — the compliance working day, for COMPLIANCE
 * and ADMIN only (`compliance.queue`; the module does not exist for anyone else).
 *
 * **One list at a time.** Tabs across the top, each with its count:
 *
 * - **Awaiting review** — checks nobody has picked up (`?view=awaiting`);
 * - **My reviews** — the reviews this user holds: under review, waiting on information,
 *   or with their proposal out for approval (`?view=mine`);
 * - **To approve** — proposals this user may approve: not their own, not one they
 *   review, not a company they are RM of, and a high-risk Clear only for a senior
 *   approver (`/background-check/proposals?status=open&awaiting=me`);
 * - **Re-KYC due**;
 * - **True matches** — proposed sanctions true matches awaiting a second officer, and
 *   **Re-screen due** — companies whose latest screening is out of date; the right
 *   side is the company's sanctions screening;
 * - **Bank details** — bank accounts waiting for approval or verification, for holders
 *   of `exporters:approve_bank_accounts`; the right side is the company's bank accounts;
 * - **Team**, for ADMIN and holders of `compliance:assign` only: everyone's reviews,
 *   the overdue and what needs attention, as a filter within the tab.
 *
 * The list is on the left and the chosen company's Background check on the right —
 * the same component the company record shows. Both the tab and the company are in the
 * URL (`?tab=`, `?company=`). The selection is the **company**, not its row: taking a
 * review (**Assign to me**, on the reviewer line of the case) moves it from *Awaiting
 * review* to *My reviews*, and the page follows it there with the same company open,
 * rather than jumping to the top of a list.
 *
 * Every list is computed by the server on read, with business-time deadlines.
 *
 * **Newest first, except where the oldest is the most urgent.** Most tabs open with what
 * arrived most recently at the top, by the date that put the row on its list: when a
 * review started waiting, a company was last screened, a bank account last changed. The
 * two lists the server pages (To approve, Re-KYC due) open oldest first instead — the
 * longest-waiting proposal and the longest-expired Clear — and are fetched in that
 * order, so with more than one request's worth waiting those are the rows read, and
 * the list says how many of the total it shows. Sorting by company sorts only the rows
 * read. The Sort menu turns any tab round or sorts by company name; the choice is in
 * the URL (`?sort=`, `?order=`) and holds across tabs.
 */

import { lazy, Suspense, useEffect, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  buttonClasses,
  EmptyLine,
  PageHeader,
  Segmented,
  Skeleton,
  SortMenu,
  type SortColumn,
  type SortState,
  useSortParams,
} from '@/components';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime } from '@/lib/format';
import { useHasPermission } from '@/platform/access';

import { actorLabel } from '../components/actor-label';
import { proposedMoveLabel } from '../components/background-check-labels';
import { RiskChip } from '../components/RiskChip';
import { STAGE_LABEL, waitedFor } from '../components/work-item-labels';
import { DueChip, WorkItemChips } from '../components/WorkItemChips';
import { BANK_STATUS_LABEL } from '../components/bank-account-labels';
import { BankAccountsSection } from '../components/BankAccountsSection';
import { SanctionsPanel } from '../components/SanctionsPanel';
import {
  useComplianceWork,
  usePendingBankAccounts,
  usePendingTrueMatches,
  useProposalsAwaitingMe,
  useReKycDue,
  useRescreenDue,
} from '../hooks';
import { paths } from '../paths';
import type { ComplianceWorkItem } from '../types';

const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

/** The most one request returns; the paged lists are read in full up to it. */
const QUEUE_LIMIT = 100;

type Tab = 'awaiting' | 'mine' | 'approve' | 'rekyc' | 'truematch' | 'rescreen' | 'bank' | 'team';
type SortKey = 'date' | 'name';
type TeamView = 'in_review' | 'overdue' | 'needs_attention';

const TAB_LABEL: Record<Tab, string> = {
  awaiting: 'Awaiting review',
  mine: 'My reviews',
  approve: 'To approve',
  rekyc: 'Re-KYC due',
  truematch: 'True matches',
  rescreen: 'Re-screen due',
  bank: 'Bank details',
  team: 'Team',
};

const TEAM_LABEL: Record<TeamView, string> = {
  needs_attention: 'Needs attention',
  overdue: 'Overdue',
  in_review: 'Everyone’s reviews',
};

const EMPTY: Record<Tab, string> = {
  awaiting: 'Every started check has a reviewer.',
  mine: 'You hold no reviews. Take one from Awaiting review.',
  approve: 'Nothing is waiting for your signature.',
  rekyc: 'No Clear is due for Re-KYC.',
  truematch: 'No sanctions true match is waiting for confirmation.',
  rescreen: 'Every screened company is up to date.',
  bank: 'No bank account is waiting for approval or verification.',
  team: 'Nothing here.',
};

/** What each tab's date is: the moment that put the row on its list. */
const DATE_LABEL: Record<Tab, string> = {
  awaiting: 'Waiting since',
  mine: 'Waiting since',
  team: 'Waiting since',
  approve: 'Proposed',
  rekyc: 'Clear expires',
  truematch: 'Proposed',
  rescreen: 'Last screened',
  bank: 'Last change',
};

const DEFAULT_SORT: SortState<SortKey> = { key: 'date', order: 'desc' };
/** To approve and Re-KYC due: the most urgent row is the one that has waited longest. */
const PAGED_DEFAULT_SORT: SortState<SortKey> = { key: 'date', order: 'asc' };
const PAGED_TABS: readonly Tab[] = ['approve', 'rekyc'];

function defaultSortFor(tab: Tab): SortState<SortKey> {
  return PAGED_TABS.includes(tab) ? PAGED_DEFAULT_SORT : DEFAULT_SORT;
}

function sortColumns(tab: Tab): SortColumn<SortKey>[] {
  return [
    { key: 'date', label: DATE_LABEL[tab], firstOrder: 'desc' },
    { key: 'name', label: 'Company', firstOrder: 'asc' },
  ];
}

/** One row of the list: the company, then one line of what it is waiting for. */
interface Row {
  companyId: string;
  companyName: string;
  detail: string;
  extra?: ReactNode;
  /** When it reached the list (`DATE_LABEL`); what the list sorts by. */
  at: string | null;
}

/** The later of two timestamps, either possibly missing. */
function later(a: string | null | undefined, b: string | null | undefined): string | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return Date.parse(a) >= Date.parse(b) ? a : b;
}

/** Rows in the chosen order. A row with no date sorts last either way; ties go A–Z. */
function sortRows(rows: Row[], sort: SortState<SortKey>): Row[] {
  const direction = sort.order === 'asc' ? 1 : -1;
  const byName = (a: Row, b: Row) =>
    a.companyName.localeCompare(b.companyName, undefined, { sensitivity: 'base' });
  return [...rows].sort((a, b) => {
    if (sort.key === 'name') return direction * byName(a, b) || 0;
    if (!a.at || !b.at) return a.at ? -1 : b.at ? 1 : byName(a, b);
    return direction * (Date.parse(a.at) - Date.parse(b.at)) || byName(a, b);
  });
}

function workRow(item: ComplianceWorkItem, showReviewer: boolean): Row {
  const parts = [STAGE_LABEL[item.stage], `waited ${waitedFor(item.waiting_since)}`];
  if (showReviewer && item.reviewer_name) parts.push(`with ${item.reviewer_name}`);
  if (item.stage === 'approval' && item.proposed_by_name) parts.push(`by ${item.proposed_by_name}`);
  return {
    companyId: item.company_id,
    companyName: item.company_name ?? 'Unnamed company',
    detail: parts.join(' · '),
    extra: <WorkItemChips item={item} />,
    at: item.waiting_since,
  };
}

function ListRow({ row, selected, onSelect }: { row: Row; selected: boolean; onSelect: () => void }) {
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
          {row.companyName}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-caption text-ink-3">
          {row.detail}
          {row.extra}
        </span>
      </button>
    </li>
  );
}

export function ApprovalsPage() {
  const lead = useHasPermission('compliance:assign');
  const approvesBank = useHasPermission('exporters:approve_bank_accounts');
  const [params, setParams] = useSearchParams();
  const tabs: Tab[] = [
    'awaiting',
    'mine',
    'approve',
    'rekyc',
    'truematch',
    'rescreen',
    ...(approvesBank ? (['bank'] as Tab[]) : []),
    ...(lead ? (['team'] as Tab[]) : []),
  ];
  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && tabs.includes(requested) ? requested : 'awaiting';
  const teamRequested = params.get('team') as TeamView | null;
  const teamView: TeamView =
    teamRequested && teamRequested in TEAM_LABEL ? teamRequested : 'needs_attention';
  const columns = sortColumns(tab);
  // Written by `update` below, with the selection, in one change to the URL.
  const [sort] = useSortParams(columns, defaultSortFor(tab));
  // The paged lists are read whichever tab is open (for their counts), in the order
  // their own tab shows: oldest first unless newest first was chosen, so the rows read
  // are the most urgent ones. A sort by company sorts the oldest that were read.
  const [pagedSort] = useSortParams(sortColumns('approve'), PAGED_DEFAULT_SORT);
  const pagedOrder = pagedSort.key === 'date' && pagedSort.order === 'desc' ? 'newest' : 'oldest';
  const rescreenOrder = sort.key === 'date' && sort.order === 'asc' ? 'oldest' : 'newest';

  // Every tab's list is read, so each tab can show its count.
  const awaiting = useComplianceWork('awaiting');
  const mine = useComplianceWork('mine');
  const team = useComplianceWork(teamView, lead);
  const proposals = useProposalsAwaitingMe({ limit: QUEUE_LIMIT, enabled: true, order: pagedOrder });
  const due = useReKycDue({ limit: QUEUE_LIMIT, enabled: true, order: pagedOrder });
  const bank = usePendingBankAccounts(approvesBank);
  const trueMatches = usePendingTrueMatches();
  const rescreen = useRescreenDue(true, sort.key === 'name' ? 'name' : rescreenOrder);

  const update = (changes: Record<string, string | null>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );

  const rowsFor = (which: Tab): Row[] => sortRows(unsortedRowsFor(which), sort);

  const unsortedRowsFor = (which: Tab): Row[] => {
    switch (which) {
      case 'awaiting':
        return (awaiting.data?.items ?? []).map((item) => workRow(item, false));
      case 'mine':
        return (mine.data?.items ?? []).map((item) => workRow(item, false));
      case 'team':
        return (team.data?.items ?? []).map((item) => workRow(item, true));
      case 'approve':
        return (proposals.data?.proposals ?? []).map((proposal) => ({
          companyId: proposal.company_id,
          companyName: proposal.company_name ?? 'Unnamed company',
          detail: `${proposedMoveLabel(proposal.to_value)} · by ${actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, ${formatDateTime(proposal.proposed_at)}`,
          extra: (
            <>
              {proposal.risk_rating && <RiskChip risk={proposal.risk_rating} />}
              <DueChip dueAt={proposal.due_at} isOverdue={proposal.is_overdue} isDueSoon={proposal.is_due_soon} />
            </>
          ),
          at: proposal.proposed_at,
        }));
      case 'rekyc':
        return (due.data?.companies ?? []).map((row) => ({
          companyId: row.company_id,
          companyName: row.company_name ?? 'Unnamed company',
          detail: `${row.is_expired ? 'Clear expired' : 'Clear expires'} ${formatDate(row.expires_at)}`,
          at: row.expires_at,
        }));
      case 'truematch': {
        const byCompany = new Map<string, Row>();
        for (const match of trueMatches.data?.matches ?? []) {
          const known = byCompany.get(match.company_id);
          if (known) {
            // One row per company, dated by its most recent proposal.
            known.at = later(known.at, match.hit.current.decided_at);
            continue;
          }
          byCompany.set(match.company_id, {
            companyId: match.company_id,
            companyName: match.company_name ?? 'Unnamed company',
            detail: `${match.subject_name} · ${match.hit.matched_name} (${match.hit.list_code})${
              match.hit.current.decided_by_name ? ` · by ${match.hit.current.decided_by_name}` : ''
            }`,
            at: match.hit.current.decided_at,
          });
        }
        return [...byCompany.values()];
      }
      case 'rescreen':
        return (rescreen.data?.companies ?? []).map((row) => ({
          companyId: row.company_id,
          companyName: row.company_name ?? 'Unnamed company',
          detail:
            row.reasons[0] +
            (row.reasons.length > 1 ? ` (+${row.reasons.length - 1} more)` : '') +
            (row.last_screened_at ? ` · screened ${formatDate(row.last_screened_at)}` : ''),
          at: row.last_screened_at ?? null,
        }));
      case 'bank': {
        // One row per company, however many of its accounts are waiting.
        const byCompany = new Map<string, Row>();
        for (const account of bank.data?.accounts ?? []) {
          const changed = [account.approved_at, account.rejected_at, account.verified_at].reduce(
            later,
            account.created_at,
          );
          const known = byCompany.get(account.customer_id);
          if (known) {
            known.at = later(known.at, changed);
            continue;
          }
          byCompany.set(account.customer_id, {
            companyId: account.customer_id,
            companyName: account.company_name ?? 'Unnamed company',
            detail: `${BANK_STATUS_LABEL[account.status]} · ${account.bank_name} ${account.currency}${account.proposed_by_name ? ` · by ${account.proposed_by_name}` : ''}`,
            at: changed,
          });
        }
        return [...byCompany.values()];
      }
    }
  };

  const queryFor: Record<Tab, { isLoading: boolean; isError: boolean }> = {
    awaiting,
    mine,
    team,
    approve: proposals,
    rekyc: due,
    truematch: trueMatches,
    rescreen,
    bank,
  };
  const countFor: Record<Tab, number | undefined> = {
    awaiting: awaiting.data?.total,
    mine: mine.data?.total,
    approve: proposals.data?.total,
    rekyc: due.data?.total,
    truematch: trueMatches.data?.matches.length,
    rescreen: rescreen.data?.total,
    bank: bank.data?.accounts.length,
    team: undefined,
  };

  const rows = rowsFor(tab);
  const query = queryFor[tab];
  // A paged list with more waiting than one request returns says so.
  const total = countFor[tab];
  const truncated = PAGED_TABS.includes(tab) && total !== undefined && total > rows.length;
  // The chosen company stays chosen while its row moves between lists (a claim, an
  // approval): the case is the company, and its name is found in whichever list has it.
  const chosenId = params.get('company') ?? rows[0]?.companyId ?? null;
  const chosenName =
    tabs.flatMap(rowsFor).find((row) => row.companyId === chosenId)?.companyName ?? 'Company';
  const awaitingIds = new Set((awaiting.data?.items ?? []).map((item) => item.company_id));
  const mineIds = new Set((mine.data?.items ?? []).map((item) => item.company_id));

  // The chosen company is written to the URL, so it survives its row moving.
  useEffect(() => {
    if (!params.get('company') && rows[0]) update({ company: rows[0].companyId });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs when the list's first row arrives
  }, [rows[0]?.companyId]);

  // Taking a review (on the reviewer line below) moves it from Awaiting review to My
  // reviews: the page follows it there, with the same company open.
  useEffect(() => {
    if (tab === 'awaiting' && chosenId && !awaitingIds.has(chosenId) && mineIds.has(chosenId)) {
      update({ tab: 'mine' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the two lists changing
  }, [tab, chosenId, awaiting.data, mine.data]);

  return (
    <div>
      <PageHeader title="Compliance work" />
      <Segmented
        label="Compliance worklists"
        value={tab}
        onValueChange={(next) => update({ tab: next, company: null })}
        options={tabs.map((value) => ({
          value,
          label: TAB_LABEL[value],
          count: countFor[value] !== undefined && countFor[value]! > 0 ? countFor[value] : undefined,
        }))}
        className="mb-4"
      />

      <div className="grid gap-4 xl:grid-cols-[22.5rem_minmax(0,1fr)] xl:items-start">
        <nav
          aria-label={TAB_LABEL[tab]}
          className="rounded border border-line bg-surface p-3 xl:sticky xl:top-0 xl:h-fit"
        >
          {tab === 'team' && (
            <Segmented
              size="sm"
              label="Team view"
              value={teamView}
              onValueChange={(next) => update({ team: next, company: null })}
              options={(Object.keys(TEAM_LABEL) as TeamView[]).map((value) => ({
                value,
                label: TEAM_LABEL[value],
              }))}
              className="mb-3"
            />
          )}
          <div className="mb-2 flex justify-end">
            <SortMenu
              columns={columns}
              value={sort}
              onChange={(next) => update({ sort: next.key, order: next.order, company: null })}
            />
          </div>
          {query.isLoading ? (
            <div className="space-y-2" aria-hidden>
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : query.isError ? (
            <p role="alert" className="text-secondary text-negative">
              Couldn't load this list.
            </p>
          ) : rows.length === 0 ? (
            <EmptyLine className="py-2">{EMPTY[tab]}</EmptyLine>
          ) : (
            <>
              <ul className="space-y-1">
                {rows.map((row) => (
                  <ListRow
                    key={row.companyId}
                    row={row}
                    selected={row.companyId === chosenId}
                    onSelect={() => update({ company: row.companyId })}
                  />
                ))}
              </ul>
              {truncated && (
                <p className="mt-2 text-caption text-ink-3" data-testid="list-truncated">
                  Showing {rows.length} of {total}: the{' '}
                  {pagedOrder === 'newest'
                    ? 'most recent'
                    : tab === 'rekyc'
                      ? 'longest expired'
                      : 'longest waiting'}
                  {sort.key === 'name' ? ', sorted by company' : ''}.
                </p>
              )}
            </>
          )}
        </nav>

        <section aria-label="Case" className="min-w-0">
          {chosenId ? (
            <>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded border border-line bg-surface px-4 py-3">
                <p className="min-w-0 truncate text-title font-semibold text-ink">{chosenName}</p>
                <Link to={paths.company(chosenId)} className={buttonClasses()}>
                  Open company
                </Link>
              </div>
              {tab === 'bank' ? (
                <BankAccountsSection key={chosenId} customerId={chosenId} />
              ) : tab === 'truematch' || tab === 'rescreen' ? (
                <SanctionsPanel key={chosenId} customerId={chosenId} />
              ) : (
                <Suspense fallback={<Skeleton className="h-60 rounded" />}>
                  <BackgroundCheckPanel key={chosenId} customerId={chosenId} isStaff />
                </Suspense>
              )}
            </>
          ) : (
            !query.isLoading && (
              <div className="rounded border border-line bg-surface px-4 py-3">
                <EmptyLine className="py-0">Choose a company from the list to open its background check.</EmptyLine>
              </div>
            )
          )}
        </section>
      </div>
    </div>
  );
}
