/**
 * The Home page's cards — domain views composed by `src/pages/HomePage.tsx`.
 *
 * Built only from routes that already exist: the follow-ups list (which also
 * carries due check-backs) and the company search. There is no stats endpoint,
 * so the stage counts are the length of one capped search per stage, shown as
 * "200+" when the cap is hit — the same honesty the pipeline's "100+" uses.
 *
 * Developer 1 (compliance engine, plans P3-1c and P3-3c) adds two: "Proposals awaiting
 * me" — background-check decisions proposed by another officer, approvable from here in
 * two clicks (Approve, then confirm) — and "Re-KYC due", the companies whose Clear has
 * expired or soon will. Both are server lists (`GET /background-check/proposals`,
 * `GET /background-check/due`); the page mounts each for the roles the server admits.
 */

import { ArrowRight, CalendarClock, PauseCircle, ShieldAlert, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { EmptySection, LINK_CLASSES, Panel, Skeleton } from '@/components';
import { formatDate, formatDateTime } from '@/lib/format';

import { JOURNEY_LABEL, JOURNEY_STAGES } from '../../constants';
import {
  useExporterProfiles,
  useFollowUps,
  useProposalsAwaitingMe,
  useReKycDue,
} from '../../hooks';
import { paths } from '../../paths';
import type {
  BackgroundCheckProposal,
  BackgroundCheckProposalAction,
  ExporterJourney,
} from '../../types';
import { actorLabel } from '../actor-label';
import { proposedMoveLabel } from '../background-check-labels';
import { ProposalResolveDialog } from '../ProposalResolveDialog';
import { RiskChip } from '../RiskChip';

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

// ── Developer 1: maker-checker (P3-1c) and Re-KYC due (P3-3c) ──────────────

function CountChip({ count, alert, testId }: { count: number; alert: boolean; testId: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs tabular-nums ${
        alert && count > 0 ? 'bg-status-failed/10 text-status-failed' : 'bg-surface-sunken text-ink-muted'
      }`}
      data-testid={testId}
    >
      {count}
    </span>
  );
}

function ProposalRow({ proposal }: { proposal: BackgroundCheckProposal }) {
  const [action, setAction] = useState<BackgroundCheckProposalAction | null>(null);
  const offered = (proposal.allowed_actions ?? []).filter((a) => a !== 'WITHDRAW');

  return (
    <li data-testid="proposal-awaiting" className="py-2.5 first:pt-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={paths.company(proposal.company_id, 'background-check')}
            className="truncate text-sm font-medium text-ink hover:text-brand-600"
          >
            {proposal.company_name ?? 'Unnamed company'}
          </Link>
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
            <span className="font-medium text-ink">{proposedMoveLabel(proposal.to_value)}</span>
            {proposal.risk_rating && <RiskChip risk={proposal.risk_rating} />}
            <span>
              by {actorLabel(proposal.proposed_by_name, proposal.proposed_by)},{' '}
              {formatDateTime(proposal.proposed_at)}
            </span>
          </p>
        </div>
        {action === null && offered.length > 0 && (
          <div className="flex shrink-0 gap-1.5">
            {offered.map((candidate) => (
              <button
                key={candidate}
                type="button"
                onClick={() => setAction(candidate)}
                className={
                  candidate === 'APPROVE'
                    ? 'rounded bg-slate-900 px-2.5 py-1 text-xs text-white'
                    : 'rounded border border-border px-2.5 py-1 text-xs'
                }
              >
                {candidate === 'APPROVE' ? 'Approve' : 'Reject'}
              </button>
            ))}
          </div>
        )}
      </div>
      {action !== null && (
        <div className="mt-2">
          <ProposalResolveDialog
            proposal={proposal}
            action={action}
            onDone={() => setAction(null)}
            onCancel={() => setAction(null)}
          />
        </div>
      )}
    </li>
  );
}

/**
 * Background-check decisions another officer has proposed and this user may approve —
 * maker-checker's queue (COMPLIANCE, ADMIN). Approve, then confirm: two clicks.
 */
export function ProposalsAwaitingMeCard() {
  const query = useProposalsAwaitingMe({ limit: PREVIEW });
  const rows = query.data?.proposals ?? [];

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          <ShieldCheck size={15} className="text-ink-faint" />
          Proposals awaiting me
          {query.data && (
            <CountChip count={query.data.total} alert testId="proposals-awaiting-count" />
          )}
        </span>
      }
    >
      {query.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : query.isError ? (
        <p role="alert" className="text-sm text-status-failed">
          Couldn't load the proposals awaiting approval.
        </p>
      ) : rows.length === 0 ? (
        <EmptySection>No background-check decision is waiting for your approval.</EmptySection>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((proposal) => (
            <ProposalRow key={proposal.id} proposal={proposal} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

/**
 * Companies whose Clear has expired or expires within the Re-KYC window (COMPLIANCE
 * and ADMIN act on it; the RM reads it). An expired Clear still reads Clear — nothing
 * moves it automatically — but no longer promotes a company or lets its deals be
 * handed over, so this is where it shows.
 */
export function ReKycDueCard() {
  const query = useReKycDue({ limit: PREVIEW });
  const rows = query.data?.companies ?? [];

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          <ShieldAlert size={15} className="text-ink-faint" />
          Re-KYC due
          {query.data && <CountChip count={query.data.total} alert testId="rekyc-due-count" />}
        </span>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-16" />
      ) : query.isError ? (
        <p role="alert" className="text-sm text-status-failed">
          Couldn't load the companies due for Re-KYC.
        </p>
      ) : rows.length === 0 ? (
        <EmptySection>
          No Clear has expired or expires before{' '}
          {query.data ? formatDate(query.data.before) : 'the Re-KYC window ends'}.
        </EmptySection>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li
              key={row.company_id}
              data-testid="rekyc-due-row"
              className="flex items-center justify-between gap-3 py-2.5 first:pt-0"
            >
              <span className="flex min-w-0 items-center gap-2">
                <Link
                  to={paths.company(row.company_id, 'background-check')}
                  className="min-w-0 truncate text-sm font-medium text-ink hover:text-brand-600"
                >
                  {row.company_name ?? 'Unnamed company'}
                </Link>
                {/* R-29: a renewal for a company that exists only as a buyer is not a
                    lead's, and should not read as one. */}
                {row.pipeline_status === 'NOT_IN_PIPELINE' ? (
                  <span className="shrink-0 text-xs text-ink-muted">Buyer only</span>
                ) : null}
              </span>
              <span
                className={`shrink-0 text-xs font-medium ${
                  row.is_expired ? 'text-status-failed' : 'text-status-review'
                }`}
              >
                {row.is_expired ? 'Expired ' : 'Expires '}
                {formatDate(row.expires_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
