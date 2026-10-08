/**
 * Home cards for the work that follows a company's owner and reviewer — computed by
 * the server on read, like the badges:
 *
 * - **Info requested on my companies**: checks a reviewer has asked more of, on the
 *   companies this user is RM of, with what was asked for, how long it has waited and
 *   whether it is overdue. The RM records what arrived on the company's Background check.
 * - **Decisions on my companies (14 days)**: CLEAR, FLAGGED and ON_HOLD outcomes on the
 *   companies this user owns or whose outcome they proposed. No reason text.
 *
 * Staff only (the routes refuse DEVELOPER); never an identifier.
 */

import { Link } from 'react-router-dom';

import { EmptyLine, Panel, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { useInfoRequests, useRecentDecisions } from '../../hooks';
import { paths } from '../../paths';
import { BackgroundCheckGauge } from '../BackgroundCheckGauge';
import { waitedFor } from '../work-item-labels';
import { DueChip } from '../WorkItemChips';

const PREVIEW = 5;

export function InfoRequestedCard() {
  const query = useInfoRequests('me');
  const rows = (query.data?.items ?? []).slice(0, PREVIEW);
  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          <Icon.info size={15} className="text-ink-3" />
          Info requested on my companies
          {query.data && query.data.total > 0 && (
            <span className="text-secondary font-normal tabular-nums text-ink-3">{query.data.total}</span>
          )}
        </span>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-12" />
      ) : query.isError ? (
        <p role="alert" className="text-body text-negative">
          Couldn't load the information requests.
        </p>
      ) : rows.length === 0 ? (
        <EmptyLine>No reviewer is waiting on you for information.</EmptyLine>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.company_id} data-testid="info-request-row" className="py-2.5 first:pt-0">
              <div className="flex items-center justify-between gap-3">
                <Link
                  to={paths.company(row.company_id, 'background-check')}
                  className="min-w-0 truncate text-body font-medium text-ink hover:text-ink"
                >
                  {row.company_name ?? 'Unnamed company'}
                </Link>
                <span className="flex shrink-0 items-center gap-2 text-caption text-ink-3">
                  waited {waitedFor(row.waiting_since)}
                  <DueChip dueAt={row.due_at} isOverdue={row.is_overdue} isDueSoon={row.is_due_soon} />
                </span>
              </div>
              {row.info_note && <p className="mt-0.5 text-secondary text-ink-2">{row.info_note}</p>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function RecentDecisionsCard() {
  const query = useRecentDecisions(14);
  const rows = (query.data?.decisions ?? []).slice(0, PREVIEW);
  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          <Icon.backgroundCheck size={15} className="text-ink-3" />
          Decisions on my companies (14 days)
        </span>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-12" />
      ) : query.isError ? (
        <p role="alert" className="text-body text-negative">
          Couldn't load the recent decisions.
        </p>
      ) : rows.length === 0 ? (
        <EmptyLine>No decisions on your companies in the last 14 days.</EmptyLine>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li
              key={row.decision_id}
              data-testid="recent-decision-row"
              className="flex items-center justify-between gap-3 py-2.5 first:pt-0"
            >
              <Link
                to={paths.company(row.company_id, 'background-check')}
                className="min-w-0 truncate text-body font-medium text-ink hover:text-ink"
              >
                {row.company_name ?? 'Unnamed company'}
              </Link>
              <span className="flex shrink-0 items-center gap-2 text-caption text-ink-3">
                <BackgroundCheckGauge value={row.to_value} />
                {formatDate(row.decided_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
