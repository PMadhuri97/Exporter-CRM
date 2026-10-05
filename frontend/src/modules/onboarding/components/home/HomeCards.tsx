/**
 * The Home page's cards — domain views composed by `src/pages/HomePage.tsx`.
 *
 * Built only from routes that already exist: the follow-ups list (which also
 * carries due check-backs) and the company search. There is no stats endpoint,
 * so the stage counts are the length of one capped search per stage, shown as
 * "200+" when the cap is hit — the same honesty the pipeline's "100+" uses.
 *
 * The compliance engine adds two: "Proposals awaiting
 * me" — background-check decisions proposed by another officer, approvable from here in
 * two clicks (Approve, then confirm) — and "Re-KYC due", the companies whose Clear has
 * expired or soon will. Both are server lists (`GET /background-check/proposals`,
 * `GET /background-check/due`); the page mounts each for the roles the server admits.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  Count,
  EmptyLine,
  Input,
  LINK_CLASSES,
  Panel,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Segmented,
  Skeleton,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate, formatDateTime } from '@/lib/format';

import { JOURNEY_LABEL, JOURNEY_STAGES } from '../../constants';
import {
  useCompleteFollowUp,
  useCriteria,
  useDealRequiredDocuments,
  useExporterProfiles,
  useFollowUps,
  useProposalsAwaitingMe,
  useReKycDue,
} from '../../hooks';
import { paths } from '../../paths';
import type {
  BackgroundCheckProposal,
  BackgroundCheckProposalAction,
  CheckBack,
  ExporterJourney,
  FollowUp,
  FollowUpOutcome,
} from '../../types';
import { JourneyDots } from '../CompanyChips';
import { actorLabel } from '../actor-label';
import { proposedMoveLabel } from '../background-check-labels';
import { ProposalResolveDialog } from '../ProposalResolveDialog';
import { RiskChip } from '../RiskChip';

const PREVIEW = 5;
const COUNT_CAP = 200;

function ViewAll({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className={`inline-flex items-center gap-1 text-secondary ${LINK_CLASSES}`}>
      {label}
      <Icon.forward size={14} aria-hidden />
    </Link>
  );
}

const OUTCOMES: { value: FollowUpOutcome; label: string }[] = [
  { value: 'DONE', label: 'Done' },
  { value: 'NO_ANSWER', label: 'No answer' },
  { value: 'RESCHEDULED', label: 'Rescheduled' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

/**
 * "Done" on a follow-up (frontend-plan §8.2, §8.7): a popover holding the outcome,
 * an optional note and — for a reschedule only — the new date. The server records
 * the completion; a reschedule logs a new follow-up rather than moving this one.
 */
export function CompleteFollowUp({ followUp }: { followUp: FollowUp }) {
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<FollowUpOutcome>('DONE');
  const [note, setNote] = useState('');
  const [nextDue, setNextDue] = useState('');
  const mutation = useCompleteFollowUp(followUp.customer_id);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="secondary" className="h-7 px-2.5" aria-label={`Done: ${followUp.subject}`}>
          Done
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate(
              {
                activityId: followUp.activity_id,
                payload: {
                  outcome,
                  note: note.trim() || null,
                  next_due_at: outcome === 'RESCHEDULED' && nextDue ? new Date(nextDue).toISOString() : null,
                },
              },
              {
                onSuccess: () => {
                  toast.success('Follow-up recorded');
                  setOpen(false);
                },
                onError: (error) => toast.error(error.message),
              },
            );
          }}
        >
          <p className="text-body font-medium text-ink">{followUp.subject}</p>
          <Segmented label="Outcome" size="sm" value={outcome} onValueChange={setOutcome} options={OUTCOMES} />
          {outcome === 'RESCHEDULED' && (
            <label className="block text-caption font-medium text-ink-2">
              New due date
              <Input type="date" className="mt-1" value={nextDue} onChange={(e) => setNextDue(e.target.value)} required />
            </label>
          )}
          <Input aria-label="Note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex justify-end">
            <Button type="submit" size="sm" variant="primary" loading={mutation.isPending}>
              Record
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}

type UpNextItem =
  | { kind: 'follow-up'; at: string; row: FollowUp }
  | { kind: 'check-back'; at: string; row: CheckBack };

/**
 * Up next (frontend-plan §8.2): overdue follow-ups and due check-backs as **one**
 * time-ordered queue — still two kinds, each labelled. A follow-up can be marked done
 * here (staff); a check-back cannot be "completed" at all: it clears when the
 * conversation moves, so it opens the conversation instead (the rule from
 * `FollowUpsPage`). Mine shows only what this user logged; Team, everyone's.
 */
export function UpNextCard({ userId, canComplete = false }: { userId: string; canComplete?: boolean }) {
  const [mine, setMine] = useState(canComplete);
  const query = useFollowUps({
    state: 'OVERDUE',
    actorId: mine ? userId : undefined,
    includeCheckBacks: true,
    checkBacksDueOnly: true,
    limit: PREVIEW,
  });
  const items: UpNextItem[] = [
    ...(query.data?.follow_ups ?? []).map((row) => ({ kind: 'follow-up' as const, at: row.due_at ?? row.occurred_at, row })),
    ...(query.data?.check_backs ?? []).map((row) => ({ kind: 'check-back' as const, at: row.check_back_on, row })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  return (
    <Panel
      title={
        <span className="inline-flex items-center gap-2">
          Up next
          {query.data && (
            <span
              className={`rounded-sm px-1.5 py-0.5 text-caption tabular-nums ${
                query.data.follow_ups_total > 0 ? 'bg-negative-tint text-negative' : 'bg-sunken text-ink-2'
              }`}
              data-testid="overdue-count"
              title="Overdue follow-ups"
            >
              {query.data.follow_ups_total}
            </span>
          )}
        </span>
      }
      actions={
        <div className="inline-flex gap-0.5 rounded-md bg-sunken p-0.5 text-caption font-medium" role="group" aria-label="Whose follow-ups">
          {[
            { value: true, label: 'Mine' },
            { value: false, label: 'Team' },
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={mine === option.value}
              onClick={() => setMine(option.value)}
              className={`rounded px-2.5 py-1 ${
                mine === option.value ? 'bg-surface text-ink ring-1 ring-line-strong' : 'text-ink-2 hover:text-ink'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      }
    >
      {query.isLoading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : query.isError ? (
        <p role="alert" className="text-body text-negative">Couldn't load what is next.</p>
      ) : items.length === 0 ? (
        <EmptyLine>{mine ? 'Nothing you logged is overdue, and no check-back is due.' : 'Nothing is overdue across the team.'}</EmptyLine>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) =>
            item.kind === 'follow-up' ? (
              <li key={`f-${item.row.activity_id}`} className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 py-2.5" data-testid="up-next-follow-up">
                <span className="inline-flex items-center gap-1.5 text-caption font-medium text-negative">
                  <Icon.followUp size={13} aria-hidden />
                  {formatDate(item.row.due_at)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-body font-medium text-ink">{item.row.subject}</span>
                  <Link to={paths.company(item.row.customer_id)} className="text-secondary text-ink-3 hover:text-ink">
                    {item.row.exporter_display_name ?? 'Unnamed company'}
                  </Link>
                </span>
                {canComplete ? <CompleteFollowUp followUp={item.row} /> : <span />}
              </li>
            ) : (
              <li key={`c-${item.row.customer_id}`} className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 py-2.5" data-testid="up-next-check-back">
                <span className={`inline-flex items-center gap-1.5 text-caption font-medium ${item.row.is_overdue ? 'text-negative' : 'text-attention'}`}>
                  <Icon.pause size={13} aria-hidden />
                  {formatDate(item.row.check_back_on)}
                </span>
                <span className="min-w-0">
                  <span className="block text-body text-ink-2">Check back — they said "not now"</span>
                  <Link
                    to={paths.company(item.row.customer_id, 'conversation')}
                    className="text-secondary font-medium text-ink hover:underline"
                  >
                    {item.row.exporter_display_name ?? 'Unnamed company'}
                  </Link>
                </span>
                <span />
              </li>
            ),
          )}
        </ul>
      )}
      <div className="mt-3">
        <ViewAll to={paths.followUps} label="The whole agenda" />
      </div>
    </Panel>
  );
}

function StageCount({ journey }: { journey: ExporterJourney }) {
  const query = useExporterProfiles({ journey, limit: COUNT_CAP });
  const count = query.data?.profiles.length;

  return (
    <Link
      to={`${paths.companies}?journey=${journey}`}
      className="group block"
      data-testid={`stage-count-${journey}`}
    >
      {query.isLoading ? (
        <Skeleton className="h-10 w-16" />
      ) : query.isError || count === undefined ? (
        <span className="font-display text-display-xl text-ink-3">—</span>
      ) : (
        <Count value={count} cap={COUNT_CAP} className="group-hover:underline group-hover:decoration-1 group-hover:underline-offset-4" />
      )}
      <span className="mt-1 flex items-center gap-1.5 text-secondary text-ink-3">
        <JourneyDots journey={journey} />
        {JOURNEY_LABEL[journey]}s
      </span>
    </Link>
  );
}

/** How many companies sit at each journey stage — three serif numerals, capped honestly. */
export function PipelineSummaryCard() {
  return (
    <Panel title="Pipeline" actions={<ViewAll to={paths.board} label="Board" />}>
      <div className="grid grid-cols-3 gap-4">
        {JOURNEY_STAGES.map((journey) => (
          <StageCount key={journey} journey={journey} />
        ))}
      </div>
    </Panel>
  );
}

/** The administrator's setup at a glance: what the rules are, one line each. */
export function SetupCard() {
  const criteria = useCriteria();
  const required = useDealRequiredDocuments();
  const activeCriteria = (criteria.data?.criteria ?? []).filter((criterion) => criterion.active).length;
  const activeRules = (required.data?.requirements ?? []).filter((rule) => rule.active).length;
  return (
    <Panel title="Setup">
      <ul className="space-y-1.5 text-body text-ink-2">
        <li>
          <Link to={paths.qualificationCriteria} className="hover:text-ink">
            {criteria.data ? `${activeCriteria} active qualification criteria` : 'Qualification criteria'}
          </Link>
        </li>
        <li>
          <Link to={paths.dealRequiredDocuments} className="hover:text-ink">
            {required.data ? `${activeRules} document ${activeRules === 1 ? 'rule' : 'rules'} for a handover` : 'Required documents'}
          </Link>
        </li>
      </ul>
    </Panel>
  );
}

// ── Maker-checker and Re-KYC due ───────────────────────────

function CountChip({ count, alert, testId }: { count: number; alert: boolean; testId: string }) {
  return (
    <span
      className={`rounded-sm px-2 py-0.5 text-xs tabular-nums ${
        alert && count > 0 ? 'bg-negative-tint text-negative' : 'bg-sunken text-ink-2'
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
            className="truncate text-sm font-medium text-ink hover:text-ink"
          >
            {proposal.company_name ?? 'Unnamed company'}
          </Link>
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
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
              <Button
                key={candidate}
                size="sm"
                className="h-7 px-2.5"
                variant={candidate === 'APPROVE' ? 'primary' : 'secondary'}
                onClick={() => setAction(candidate)}
              >
                {candidate === 'APPROVE' ? 'Approve' : 'Reject'}
              </Button>
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
          <Icon.backgroundCheck size={15} className="text-ink-3" />
          Awaiting your signature
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
        <p role="alert" className="text-sm text-negative">
          Couldn't load the proposals awaiting approval.
        </p>
      ) : rows.length === 0 ? (
        <EmptyLine>No background-check decision is waiting for your approval.</EmptyLine>
      ) : (
        <ul className="divide-y divide-line">
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
          <Icon.flagged size={15} className="text-ink-3" />
          Re-KYC due
          {query.data && <CountChip count={query.data.total} alert testId="rekyc-due-count" />}
        </span>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-16" />
      ) : query.isError ? (
        <p role="alert" className="text-sm text-negative">
          Couldn't load the companies due for Re-KYC.
        </p>
      ) : rows.length === 0 ? (
        <EmptyLine>
          No Clear has expired or expires before{' '}
          {query.data ? formatDate(query.data.before) : 'the Re-KYC window ends'}.
        </EmptyLine>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li
              key={row.company_id}
              data-testid="rekyc-due-row"
              className="flex items-center justify-between gap-3 py-2.5 first:pt-0"
            >
              <span className="flex min-w-0 items-center gap-2">
                <Link
                  to={paths.company(row.company_id, 'background-check')}
                  className="min-w-0 truncate text-sm font-medium text-ink hover:text-ink"
                >
                  {row.company_name ?? 'Unnamed company'}
                </Link>
                {/* A renewal for a company that exists only as a buyer is not a
                    lead's, and should not read as one. */}
                {row.pipeline_status === 'NOT_IN_PIPELINE' ? (
                  <span className="shrink-0 text-xs text-ink-2">Buyer only</span>
                ) : null}
              </span>
              <span
                className={`shrink-0 text-xs font-medium ${
                  row.is_expired ? 'text-negative' : 'text-attention'
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
