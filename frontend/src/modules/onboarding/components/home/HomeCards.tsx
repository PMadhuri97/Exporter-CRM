/**
 * The Home page's cards — domain views composed by `src/pages/HomePage.tsx`.
 *
 * Built only from routes that already exist: the follow-ups list (which also
 * carries due check-backs) and the company search. There is no stats endpoint,
 * so the stage counts are the length of one capped search per stage, shown as
 * "200+" when the cap is hit — the same honesty the pipeline's "100+" uses.
 */

import { ArrowRight, CalendarClock, PauseCircle } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { EmptySection, LINK_CLASSES, Panel, Skeleton } from '@/components';
import { formatDate, formatDateTime } from '@/lib/format';

import { JOURNEY_LABEL, JOURNEY_STAGES } from '../../constants';
import { useExporterProfiles, useFollowUps } from '../../hooks';
import { paths } from '../../paths';
import type { ExporterJourney } from '../../types';

const PREVIEW = 5;
const COUNT_CAP = 200;

function ViewAll({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className={`inline-flex items-center gap-1 text-sm ${LINK_CLASSES}`}>
      {label}
      <ArrowRight size={14} />
    </Link>
  );
}

/** Overdue follow-ups — the team's, or only the ones this user logged. */
export function FollowUpsDueCard({ userId }: { userId: string }) {
  const [mine, setMine] = useState(true);
  const query = useFollowUps({
    state: 'OVERDUE',
    actorId: mine ? userId : undefined,
    includeCheckBacks: true,
    checkBacksDueOnly: true,
    limit: PREVIEW,
  });
  const rows = query.data?.follow_ups ?? [];

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          Overdue follow-ups
          {query.data && (
            <span
              className={`rounded-full px-2 py-0.5 text-xs tabular-nums ${
                query.data.follow_ups_total > 0
                  ? 'bg-status-failed/10 text-status-failed'
                  : 'bg-surface-sunken text-ink-muted'
              }`}
              data-testid="overdue-count"
            >
              {query.data.follow_ups_total}
            </span>
          )}
        </span>
      }
      actions={
        <div className="inline-flex rounded-lg bg-surface-sunken p-0.5 text-xs font-medium" role="group" aria-label="Whose follow-ups">
          {[
            { value: true, label: 'Mine' },
            { value: false, label: 'Team' },
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={mine === option.value}
              onClick={() => setMine(option.value)}
              className={`rounded-md px-2.5 py-1 ${
                mine === option.value ? 'bg-surface text-ink shadow-card' : 'text-ink-muted hover:text-ink'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      }
    >
      {query.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : query.isError ? (
        <p className="text-sm text-status-failed">Couldn't load follow-ups.</p>
      ) : rows.length === 0 ? (
        <EmptySection>{mine ? 'Nothing you logged is overdue.' : 'Nothing is overdue across the team.'}</EmptySection>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.activity_id} className="flex items-start justify-between gap-3 py-2.5 first:pt-0">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{row.subject}</p>
                <Link to={paths.company(row.customer_id)} className="text-xs text-ink-muted hover:text-ink">
                  {row.exporter_display_name ?? 'Unnamed company'}
                </Link>
              </div>
              <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-status-failed">
                <CalendarClock size={12} />
                {formatDateTime(row.due_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4">
        <ViewAll to={paths.followUps} label="All follow-ups" />
      </div>
    </Panel>
  );
}

/** Companies that said "not now" and are due to be picked back up. */
export function CheckBacksDueCard() {
  const query = useFollowUps({
    state: 'OVERDUE',
    includeCheckBacks: true,
    checkBacksDueOnly: true,
    limit: PREVIEW,
  });
  const rows = query.data?.check_backs ?? [];

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          Check-backs due
          {query.data && (
            <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs tabular-nums text-ink-muted">
              {query.data.check_backs_total}
            </span>
          )}
        </span>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-16" />
      ) : query.isError ? (
        <p className="text-sm text-status-failed">Couldn't load check-backs.</p>
      ) : rows.length === 0 ? (
        <EmptySection>No company is due a check-back.</EmptySection>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.customer_id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0">
              <Link
                to={paths.company(row.customer_id, 'conversation')}
                className="inline-flex min-w-0 items-center gap-2 text-sm font-medium text-ink hover:text-brand-600"
              >
                <PauseCircle size={14} className="shrink-0 text-ink-faint" />
                <span className="truncate">{row.exporter_display_name ?? 'Unnamed company'}</span>
              </Link>
              <span className={`shrink-0 text-xs font-medium ${row.is_overdue ? 'text-status-failed' : 'text-status-review'}`}>
                {formatDate(row.check_back_on)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const STAGE_ACCENT: Record<ExporterJourney, string> = {
  LEAD: 'bg-journey-lead',
  PROSPECT: 'bg-journey-prospect',
  CUSTOMER: 'bg-journey-customer',
};

function StageCount({ journey }: { journey: ExporterJourney }) {
  const query = useExporterProfiles({ journey, limit: COUNT_CAP });
  const count = query.data?.profiles.length;

  return (
    <Link
      to={`${paths.companies}?journey=${journey}`}
      className="group rounded-lg border border-border p-4 transition-colors hover:border-brand-500"
      data-testid={`stage-count-${journey}`}
    >
      <div className="flex items-center gap-2 text-sm text-ink-muted">
        <span className={`h-2 w-2 rounded-full ${STAGE_ACCENT[journey]}`} aria-hidden />
        {JOURNEY_LABEL[journey]}s
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">
        {query.isLoading ? (
          <Skeleton className="mt-1 h-7 w-12" />
        ) : query.isError ? (
          '—'
        ) : (
          <>
            {count}
            {count === COUNT_CAP ? '+' : ''}
          </>
        )}
      </div>
    </Link>
  );
}

/** How many companies sit at each journey stage (ENDED relationships excluded,
 * as in every working list). */
export function PipelineSummaryCard() {
  return (
    <Panel title="Pipeline" actions={<ViewAll to={paths.pipeline} label="Open pipeline" />}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {JOURNEY_STAGES.map((journey) => (
          <StageCount key={journey} journey={journey} />
        ))}
      </div>
    </Panel>
  );
}
