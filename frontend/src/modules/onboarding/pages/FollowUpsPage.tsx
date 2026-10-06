/**
 * The Follow-ups screen.
 *
 * What we owe companies next, and whether we did it. **The whole team's list**:
 * no owner filter is applied by default, and the "mine" filter is a
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

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  Card,
  EmptyLine,
  Input,
  PageHeader,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Segmented,
  Select,
  Skeleton,
  Tag,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@/components';
import { Icon } from '@/design/icons';
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
    <Tag
      dot
      tone={row.state === 'OVERDUE' ? 'negative' : row.state === 'DONE' ? 'positive' : 'progress'}
      className="shrink-0"
      data-testid="follow-up-state"
    >
      {humanize(row.state)}
    </Tag>
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
      className="space-y-3"
      data-extension="complete-follow-up"
    >
      <p className="text-body font-semibold text-ink">{row.subject}</p>
      <div className="grid gap-3">
        <label className="text-caption font-medium text-ink-2">
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
          <label className="text-caption font-medium text-ink-2">
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
      <label className="block text-caption font-medium text-ink-2">
        Note
        <Textarea
          className="mt-1 min-h-20 resize-y"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What happened?"
        />
      </label>
      {needsNextDue && (
        <p className="text-caption text-ink-3">
          Rescheduling logs a new follow-up for the new date. This one stays on the
          record with the date it was promised for — an activity is never edited.
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button size="sm" onClick={onDone}>
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
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3" data-testid="follow-up-row">
      <div className="flex w-36 shrink-0 flex-col items-start gap-1">
        <StateBadge row={row} />
        <span className={`text-secondary ${row.state === 'OVERDUE' ? 'text-negative' : 'text-ink-2'}`}>
          Due {formatDateTime(row.due_at)}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-body font-semibold text-ink">{row.subject}</p>
        <Link
          to={paths.company(row.customer_id)}
          className="text-secondary text-accent underline-offset-2 hover:underline"
        >
          {row.exporter_display_name ?? 'Unnamed company'}
        </Link>
        <span className="text-secondary text-ink-3"> · Logged by {actorLabel(row.actor_name, row.actor_id)}</span>
        {row.notes && <p className="mt-1 whitespace-pre-wrap text-secondary text-ink-2">{row.notes}</p>}
        {row.completion && (
          <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded bg-sunken px-3 py-2">
            <span className="inline-flex items-center gap-1 text-body font-semibold text-ink">
              <Icon.done size={14} aria-hidden /> {humanize(row.completion.outcome)}
            </span>
            <span className="text-secondary text-ink-3">
              by {actorLabel(row.completion.completed_by_name, row.completion.completed_by)} on{' '}
              {formatDateTime(row.completion.completed_at)}
            </span>
            {row.completion.next_due_at && (
              <span className="text-secondary font-semibold text-attention">
                moved to {formatDateTime(row.completion.next_due_at)}
              </span>
            )}
            {row.completion.note && <p className="w-full text-body text-ink-2">{row.completion.note}</p>}
          </div>
        )}
      </div>
      {!row.completion && isStaff && (
        <Popover open={completing} onOpenChange={setCompleting}>
          <PopoverTrigger asChild>
            <Button size="sm" data-complete>
              Mark done
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80">
            <CompleteForm row={row} onDone={() => setCompleting(false)} />
          </PopoverContent>
        </Popover>
      )}
    </li>
  );
}

function CheckBackRow({ row }: { row: CheckBack }) {
  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3" data-testid="check-back-row">
      <Icon.pause size={16} className="mt-0.5 shrink-0 text-ink-3" />
      <div className="min-w-0 flex-1">
        <Link
          to={paths.company(row.customer_id, 'conversation')}
          className="inline-flex items-center gap-1 font-semibold text-accent underline-offset-2 hover:underline"
        >
          {row.exporter_display_name ?? 'Unnamed company'}
          <Icon.caretRight size={13} />
        </Link>
        <p className="mt-0.5 text-body text-ink-2">
          Said not now. Pick the conversation back up on this company's page.
        </p>
      </div>
      <p
        className={`text-caption font-medium ${row.is_overdue ? 'text-negative' : 'text-attention'}`}
      >
        Check back {formatDate(row.check_back_on)}
      </p>
    </div>
  );
}

/** Today, as the `YYYY-MM-DD` of the viewer's day. */
function localDay(offsetDays = 0): string {
  const day = new Date();
  day.setDate(day.getDate() + offsetDays);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
}

type Bucket = 'Overdue' | 'Today' | 'This week' | 'Later' | 'Done';
const BUCKETS: Bucket[] = ['Overdue', 'Today', 'This week', 'Later', 'Done'];

/**
 * Which time bucket a row reads under (frontend-plan §8.7). Overdue and Done are the
 * server's `state` — never worked out here; the rest only place an open row by its
 * due date, which is presentation, not a rule.
 */
function bucketOf(row: FollowUp): Bucket {
  if (row.state === 'DONE') return 'Done';
  if (row.state === 'OVERDUE') return 'Overdue';
  const due = row.due_at ? formatDayKey(row.due_at) : null;
  if (due === null || due > localDay(6)) return 'Later';
  return due === localDay() ? 'Today' : 'This week';
}

function formatDayKey(value: string): string {
  const day = new Date(value);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
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
      className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3"
      data-testid="follow-ups-pager"
    >
      <span className="text-body tabular-nums text-ink-2">
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
  const [whose, setWhose] = useState<'MINE' | 'TEAM'>('TEAM');
  const mineOnly = whose === 'MINE';
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

  const rows = query.data?.follow_ups ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Follow-ups"
        description="What we owe companies next, across every company."
        actions={
          <Segmented
            label="Whose follow-ups"
            value={whose}
            onValueChange={(next) => {
              setWhose(next);
              setOffset(0);
            }}
            options={[
              { value: 'MINE', label: 'Mine' },
              { value: 'TEAM', label: 'Team' },
            ]}
          />
        }
      />

      <Tabs value={tab} onValueChange={(next) => selectTab(next as TabKey)} variant="pill">
        <TabsList aria-label="Follow-up state">
          {TABS.map((item) => (
            <TabsTrigger key={item.key} value={item.key}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22.5rem] xl:items-start">
        <div className="flex min-w-0 flex-col gap-4" data-extension="follow-ups">
          {query.isLoading ? (
            <Card>
              <div className="space-y-3">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </div>
            </Card>
          ) : query.isError ? (
            <Card>
              <p className="text-body text-negative">Could not load follow-ups. {query.error.message}</p>
            </Card>
          ) : rows.length > 0 ? (
            <>
              {BUCKETS.map((bucket) => {
                const inBucket = rows.filter((row) => bucketOf(row) === bucket);
                if (inBucket.length === 0) return null;
                return (
                  <Card key={bucket} as="h2" title={bucket} count={inBucket.length} flush aria-label={bucket}>
                    <ul className="divide-y divide-line border-t border-line">
                      {inBucket.map((row) => (
                        <FollowUpRow key={row.activity_id} row={row} isStaff={isStaff} />
                      ))}
                    </ul>
                  </Card>
                );
              })}
              <Pager
                offset={offset}
                shown={rows.length}
                total={query.data?.follow_ups_total ?? 0}
                onChange={setOffset}
              />
            </>
          ) : (
            <Card>
              <EmptyLine className="py-0">
                {tab === 'overdue'
                  ? 'Nothing is overdue. '
                  : tab === 'done'
                    ? 'Nothing has been recorded as dealt with yet. '
                    : 'No follow-ups here. '}
                A follow-up is an activity logged with a due date, on a company's page.
              </EmptyLine>
            </Card>
          )}
        </div>

        {(tab === 'overdue' || tab === 'all') && (
          <Card
            as="h2"
            data-extension="check-backs"
            title={tab === 'overdue' ? 'Check-backs due' : 'Check-backs'}
            count={query.data?.check_backs_total}
            description="Companies that said not now. Not completed here — move the conversation on the company's page and the check-back clears itself."
            flush
          >
            {query.isLoading ? (
              <div className="px-4 pb-4">
                <Skeleton className="h-12" />
              </div>
            ) : query.isError ? (
              <p className="px-4 pb-4 text-body text-negative">Could not load check-backs. {query.error.message}</p>
            ) : query.data && query.data.check_backs.length > 0 ? (
              <div className="divide-y divide-line border-t border-line">
                {query.data.check_backs.map((row) => (
                  <CheckBackRow key={row.customer_id} row={row} />
                ))}
              </div>
            ) : (
              <EmptyLine className="px-4 pb-3">
                {tab === 'overdue' ? 'No check-back is due yet.' : 'No company is parked waiting for a check-back.'}
              </EmptyLine>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
