/**
 * The Follow-ups screen — **owner: Developer 3A, Phase 2** (L3-11a-ii).
 *
 * What we owe companies next, and whether we did it. **The whole team's list**
 * (decision D2): no owner filter is applied by default, and the "mine" filter is a
 * convenience, not a permission — the server would serve the same rows either way.
 *
 * **Two sections, because there are two different things.** A *follow-up* is an
 * activity somebody promised to do, dealt with by recording a completion. A
 * *check-back* is a company parked at `NOT_NOW`, dealt with by moving the
 * conversation gauge on its own page. They are not merged into one list: only one of
 * them has a completion, only one has an activity, and a single list would invite
 * someone to try completing a check-back, which is not a thing.
 *
 * **Nothing about state is computed here.** `state` and `is_overdue` come from the
 * server, which derives them from whether a completion row exists — there is no
 * status column on an activity, and there must never be one (architecture §9.3's
 * first "Watch out for"). This page renders what it is told; the one thing it decides
 * is which tab is selected.
 *
 * Reached from the sidebar's `Follow-ups` row at `/follow-ups`, and from the Home
 * page's cards.
 */

import {
  CalendarClock,
  CheckCheck,
  ChevronRight,
  ClipboardList,
  PauseCircle,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  Chip,
  EmptySection,
  Input,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@/components';
import { formatDate, formatDateTime, humanize } from '@/lib/format';
import { useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';

import { actorLabel } from '../components';
import { useCompleteFollowUp, useFollowUps } from '../hooks';
import { paths } from '../paths';
import type { CheckBack, FollowUp, FollowUpOutcome, FollowUpState } from '../types';

/** The tabs, and the `state` each one asks the server for.
 *
 * `undefined` is "all three" — the server's own default — rather than a fourth value,
 * so the page never has to describe a state the API does not have. A keyed record
 * rather than an array lookup: `TABS[0]` would be `| undefined` under
 * `noUncheckedIndexedAccess`, and a fallback for a tab that cannot be missing is
 * dead code pretending to be safety.
 */
type TabKey = 'overdue' | 'outstanding' | 'done' | 'all';

const TAB_STATE: Record<TabKey, FollowUpState | undefined> = {
  overdue: 'OVERDUE',
  outstanding: 'OUTSTANDING',
  done: 'DONE',
  all: undefined,
};

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overdue', label: 'Overdue' },
  { key: 'outstanding', label: 'Outstanding' },
  { key: 'done', label: 'Done' },
  { key: 'all', label: 'All' },
];

/** The outcomes a person may record. Not a copy of a server rule: these are the four
 * values of the enum the API already declares, and the rules about which of them
 * needs a next due date are enforced on the server and shown as it words them. */
const OUTCOMES: FollowUpOutcome[] = ['DONE', 'NO_ANSWER', 'RESCHEDULED', 'CANCELLED'];

function StateBadge({ row }: { row: FollowUp }) {
  return (
    <Chip
      dot
      tone={row.state === 'OVERDUE' ? 'danger' : row.state === 'DONE' ? 'success' : 'info'}
      className="shrink-0"
      data-testid="follow-up-state"
    >
      {humanize(row.state)}
    </Chip>
  );
}

function CompleteForm({
  row,
  onDone,
}: {
  row: FollowUp;
  onDone: () => void;
}) {
  const mutation = useCompleteFollowUp(row.customer_id);
  const [outcome, setOutcome] = useState<FollowUpOutcome>('DONE');
  const [note, setNote] = useState('');
  const [nextDueAt, setNextDueAt] = useState('');

  // The one rule this form mirrors, because it decides which field to render at all.
  // The server enforces it and refuses either mistake; this only avoids asking for a
  // date that would be rejected, or hiding one that is required.
  const needsNextDue = outcome === 'RESCHEDULED';

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    mutation.mutate(
      {
        activityId: row.activity_id,
        payload: {
          outcome,
          note: note.trim() || null,
          next_due_at: needsNextDue && nextDueAt ? new Date(nextDueAt).toISOString() : null,
        },
      },
      {
        onSuccess: () => {
          toast.success(
            needsNextDue
              ? 'Follow-up rescheduled — a new one has been logged'
              : `Follow-up recorded as ${humanize(outcome).toLowerCase()}`,
          );
          onDone();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <form
      onSubmit={submit}
      className="mt-3 space-y-3 rounded-lg border border-border bg-surface-subtle p-3"
      data-extension="complete-follow-up"
    >
      <div className="grid gap-3 md:grid-cols-[180px_1fr]">
        <label className="text-xs font-medium text-ink-muted">
          Outcome
          <Select
            className="mt-1"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as FollowUpOutcome)}
            aria-label="Outcome"
          >
            {OUTCOMES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
        </label>
        {needsNextDue && (
          <label className="text-xs font-medium text-ink-muted">
            New due date and time
            <Input
              type="datetime-local"
              className="mt-1"
              value={nextDueAt}
              onChange={(event) => setNextDueAt(event.target.value)}
              required
            />
          </label>
        )}
      </div>
      <label className="block text-xs font-medium text-ink-muted">
        Note
        <Textarea
          className="mt-1 min-h-20 resize-y"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What happened?"
        />
      </label>
      {needsNextDue && (
        <p className="text-xs text-ink-faint">
          Rescheduling logs a new follow-up for the new date. This one stays on the
          record with the date it was promised for — an activity is never edited.
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
          Record
        </Button>
      </div>
    </form>
  );
}

function FollowUpRow({ row, isStaff }: { row: FollowUp; isStaff: boolean }) {
  const [completing, setCompleting] = useState(false);

  return (
    <div className="border-b border-border py-4 first:pt-1 last:border-b-0" data-testid="follow-up-row">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <StateBadge row={row} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{row.subject}</p>
          <Link
            to={paths.company(row.customer_id)}
            className="mt-0.5 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink"
          >
            {row.exporter_display_name ?? 'Unnamed company'}
            <ChevronRight size={13} />
          </Link>
          {row.notes && (
            <p className="mt-1 whitespace-pre-wrap text-sm text-ink-muted">{row.notes}</p>
          )}
        </div>
        <div className="text-left text-xs text-ink-faint md:text-right">
          <p
            className={`inline-flex items-center gap-1 font-medium ${
              row.state === 'OVERDUE' ? 'text-status-failed' : ''
            }`}
          >
            <CalendarClock size={12} /> Due {formatDateTime(row.due_at)}
          </p>
          <p className="mt-1">Logged by {actorLabel(row.actor_name, row.actor_id)}</p>
        </div>
      </div>

      {row.completion ? (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg bg-surface-sunken px-3 py-2">
          <span className="inline-flex items-center gap-1 text-sm font-medium text-ink">
            <CheckCheck size={13} /> {humanize(row.completion.outcome)}
          </span>
          <span className="text-xs text-ink-faint">
            by {row.completion.completed_by ?? 'the platform'} on{' '}
            {formatDateTime(row.completion.completed_at)}
          </span>
          {row.completion.next_due_at && (
            <span className="text-xs font-medium text-status-review">
              moved to {formatDateTime(row.completion.next_due_at)}
            </span>
          )}
          {row.completion.note && (
            <p className="w-full text-sm text-ink-muted">{row.completion.note}</p>
          )}
        </div>
      ) : (
        isStaff &&
        (completing ? (
          <CompleteForm row={row} onDone={() => setCompleting(false)} />
        ) : (
          <Button size="sm" className="mt-2" onClick={() => setCompleting(true)}>
            Record outcome
          </Button>
        ))
      )}
    </div>
  );
}

function CheckBackRow({ row }: { row: CheckBack }) {
  return (
    <div
      className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-border py-3 first:pt-1 last:border-b-0"
      data-testid="check-back-row"
    >
      <PauseCircle size={16} className="mt-0.5 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        <Link
          to={paths.company(row.customer_id, 'conversation')}
          className="inline-flex items-center gap-1 font-medium text-ink hover:text-brand-600"
        >
          {row.exporter_display_name ?? 'Unnamed company'}
          <ChevronRight size={13} />
        </Link>
        <p className="mt-0.5 text-sm text-ink-muted">
          Said not now. Pick the conversation back up on this company's page.
        </p>
      </div>
      <p
        className={`text-xs font-medium ${row.is_overdue ? 'text-status-failed' : 'text-status-review'}`}
      >
        Check back {formatDate(row.check_back_on)}
      </p>
    </div>
  );
}

/** Rows per page. The server's default, stated here so the pager and the request
 * agree on it rather than both assuming. */
const PAGE_SIZE = 50;

/**
 * Previous / next over the follow-ups, from the server's `follow_ups_total`.
 *
 * The list is soonest-due first, so without paging the Done and All tabs would only
 * ever show their oldest 50 rows and recent work would be unreachable. Renders
 * nothing when everything fits on one page.
 */
function Pager({
  offset,
  shown,
  total,
  onChange,
}: {
  offset: number;
  shown: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= PAGE_SIZE && offset === 0) return null;
  return (
    <div
      className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3"
      data-testid="follow-ups-pager"
    >
      <span className="text-sm tabular-nums text-ink-muted">
        {offset + 1}–{offset + shown} of {total}
      </span>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </Button>
        <Button
          size="sm"
          disabled={offset + shown >= total}
          onClick={() => onChange(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function FollowUpsPage() {
  // Non-nullable: `useCurrentUser` throws outside an authenticated tree, and this
  // page only renders inside `ProtectedRoute`.
  const currentUser = useCurrentUser();
  // DEVELOPER reads the CRM and writes nothing, so it gets no "Record outcome"
  // button. The server refuses it too — this only avoids offering it. The same
  // capability every screen asks, so no two can disagree about who is staff.
  const isStaff = useCan('crm.write');

  const [tab, setTab] = useState<TabKey>('overdue');
  const [mineOnly, setMineOnly] = useState(false);
  const [offset, setOffset] = useState(0);

  // A new tab or filter is a new list, so it starts from its first page.
  const selectTab = (next: TabKey) => {
    setTab(next);
    setOffset(0);
  };

  const query = useFollowUps({
    state: TAB_STATE[tab],
    // A convenience, not a permission: the list is the whole team's, and the server
    // serves everyone's rows unless asked to narrow them.
    actorId: mineOnly ? String(currentUser.id) : undefined,
    // Check-backs have no state, so they are the same set on every tab. Fetched only
    // on the tabs where showing the same rows four times would not be noise — and on
    // Overdue only the ones that are due, so a company parked until next quarter is
    // not listed beside work that is late.
    includeCheckBacks: tab === 'overdue' || tab === 'all',
    checkBacksDueOnly: tab === 'overdue',
    limit: PAGE_SIZE,
    offset,
  });

  // Completing the last row on a later page leaves that page empty. Step back to the
  // last page that has rows rather than telling the user there is nothing here.
  const total = query.data?.follow_ups_total;
  useEffect(() => {
    if (total !== undefined && offset > 0 && offset >= total) {
      setOffset(Math.max(0, Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE));
    }
  }, [total, offset]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Follow-ups"
        description="What we owe companies next, across every company — the whole team's list."
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs value={tab} onValueChange={(next) => selectTab(next as TabKey)} variant="pill">
          <TabsList aria-label="Follow-up state">
            {TABS.map((item) => (
              <TabsTrigger key={item.key} value={item.key}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <label className="flex items-center gap-2 text-sm text-ink-muted">
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(event) => {
              setMineOnly(event.target.checked);
              setOffset(0);
            }}
            className="h-4 w-4 rounded border-border-strong accent-brand-600"
          />
          Only the ones I logged
        </label>
      </div>

      <Panel
        data-extension="follow-ups"
        title={
          <span className="inline-flex items-center gap-2">
            <ClipboardList size={16} className="text-ink-faint" />
            Follow-ups
          </span>
        }
        actions={
          query.data && (
            <span className="text-sm tabular-nums text-ink-faint">{query.data.follow_ups_total}</span>
          )
        }
      >
        {query.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        ) : query.isError ? (
          <p className="text-sm text-status-failed">
            Could not load follow-ups. {query.error.message}
          </p>
        ) : query.data && query.data.follow_ups.length > 0 ? (
          <div>
            {query.data.follow_ups.map((row) => (
              <FollowUpRow key={row.activity_id} row={row} isStaff={isStaff} />
            ))}
            <Pager
              offset={offset}
              shown={query.data.follow_ups.length}
              total={query.data.follow_ups_total}
              onChange={setOffset}
            />
          </div>
        ) : (
          <EmptySection>
            {tab === 'overdue'
              ? 'Nothing is overdue. '
              : tab === 'done'
                ? 'Nothing has been recorded as dealt with yet. '
                : 'No follow-ups here. '}
            A follow-up is an activity logged with a due date, on a company's page.
          </EmptySection>
        )}
      </Panel>

      {(tab === 'overdue' || tab === 'all') && (
        <Panel
          data-extension="check-backs"
          title={
            <span className="inline-flex items-center gap-2">
              <PauseCircle size={16} className="text-ink-faint" />
              {tab === 'overdue' ? 'Check-backs due' : 'Check-backs'}
            </span>
          }
          actions={
            query.data && (
              <span className="text-sm tabular-nums text-ink-faint">{query.data.check_backs_total}</span>
            )
          }
        >
          <p className="mb-3 text-sm text-ink-muted">
            Companies that said not now
            {tab === 'overdue' ? ', due to be picked up today or earlier' : ''}. These are
            not completed here — move the conversation on the company's page and the
            check-back clears itself.
          </p>

          {query.isLoading ? (
            <Skeleton className="h-12" />
          ) : query.isError ? (
            <p className="text-sm text-status-failed">
              Could not load check-backs. {query.error.message}
            </p>
          ) : query.data && query.data.check_backs.length > 0 ? (
            <div>
              {query.data.check_backs.map((row) => (
                <CheckBackRow key={row.customer_id} row={row} />
              ))}
            </div>
          ) : (
            <EmptySection>
              {tab === 'overdue'
                ? 'No check-back is due yet.'
                : 'No company is parked waiting for a check-back.'}
            </EmptySection>
          )}
        </Panel>
      )}
    </div>
  );
}
