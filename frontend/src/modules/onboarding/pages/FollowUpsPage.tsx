/**
 * The Follow-ups screen — **owner: Developer 3A, Phase 2** (L3-11a-ii).
 *
 * What we owe exporters next, and whether we did it. **The whole team's list**
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
 * Reached from the sidebar's `Follow-ups` row, whose `status` flips from `'soon'` in
 * the same commit as this file, so navigation never points at a page that renders
 * nothing.
 */

import {
  CalendarClock,
  CheckCheck,
  ChevronRight,
  ClipboardList,
  PauseCircle,
} from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { EmptySection } from '@/components';
import { formatDate, formatDateTime, humanize } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';

import { useCompleteFollowUp, useFollowUps } from '../hooks';
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
  const classes =
    row.state === 'OVERDUE'
      ? 'bg-status-failed/10 text-status-failed'
      : row.state === 'DONE'
        ? 'bg-status-passed/10 text-status-passed'
        : 'bg-status-pending/10 text-status-pending';
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
      data-testid="follow-up-state"
    >
      {humanize(row.state)}
    </span>
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
          <select
            className="input mt-1"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as FollowUpOutcome)}
            aria-label="Outcome"
          >
            {OUTCOMES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </select>
        </label>
        {needsNextDue && (
          <label className="text-xs font-medium text-ink-muted">
            New due date and time
            <input
              type="datetime-local"
              className="input mt-1"
              value={nextDueAt}
              onChange={(event) => setNextDueAt(event.target.value)}
              required
            />
          </label>
        )}
      </div>
      <label className="block text-xs font-medium text-ink-muted">
        Note
        <textarea
          className="input mt-1 min-h-20 resize-y"
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
        <button
          type="button"
          onClick={onDone}
          className="rounded-lg px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-sunken"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? 'Saving…' : 'Record'}
        </button>
      </div>
    </form>
  );
}

function FollowUpRow({ row, isStaff }: { row: FollowUp; isStaff: boolean }) {
  const [completing, setCompleting] = useState(false);

  return (
    <div className="border-b border-border py-4 last:border-b-0" data-testid="follow-up-row">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <StateBadge row={row} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{row.subject}</p>
          <Link
            to={`/exporters/${row.customer_id}`}
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
          <p className="inline-flex items-center gap-1 font-medium">
            <CalendarClock size={12} /> Due {formatDateTime(row.due_at)}
          </p>
          <p className="mt-1">Logged by {row.actor_id}</p>
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
          <button
            type="button"
            onClick={() => setCompleting(true)}
            className="mt-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Record outcome
          </button>
        ))
      )}
    </div>
  );
}

function CheckBackRow({ row }: { row: CheckBack }) {
  return (
    <div
      className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-border py-3 last:border-b-0"
      data-testid="check-back-row"
    >
      <PauseCircle size={16} className="mt-0.5 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        <Link
          to={`/exporters/${row.customer_id}`}
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

export function FollowUpsPage() {
  // Non-nullable: `useCurrentUser` throws outside an authenticated tree, and this
  // page only renders inside `ProtectedRoute`.
  const currentUser = useCurrentUser();
  // DEVELOPER reads the CRM and writes nothing, so it gets no "Record outcome"
  // button. The server refuses it too — this only avoids offering it. Same
  // expression as `ExporterDetailPage`'s, so the two screens cannot disagree about
  // who is staff.
  const isStaff = currentUser.role !== 'DEVELOPER';

  const [tab, setTab] = useState<TabKey>('overdue');
  const [mineOnly, setMineOnly] = useState(false);

  const query = useFollowUps({
    state: TAB_STATE[tab],
    // A convenience, not a permission: the list is the whole team's, and the server
    // serves everyone's rows unless asked to narrow them.
    actorId: mineOnly ? String(currentUser.id) : undefined,
    // Check-backs have no state, so they are the same set on every tab. Fetched only
    // on the tabs where showing the same rows four times would not be noise.
    includeCheckBacks: tab === 'overdue' || tab === 'all',
  });

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-ink">Follow-ups</h1>
        <p className="mt-1 text-sm text-ink-muted">
          What we owe exporters next, across every company — the whole team's list.
        </p>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Follow-up state">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={tab === item.key}
              onClick={() => setTab(item.key)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                tab === item.key
                  ? 'bg-brand-50 text-brand-600'
                  : 'text-ink-muted hover:bg-surface-sunken hover:text-ink'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-muted">
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(event) => setMineOnly(event.target.checked)}
            className="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500"
          />
          Only the ones I logged
        </label>
      </div>

      <section
        className="rounded-lg border border-border bg-surface p-5 shadow-card"
        data-extension="follow-ups"
      >
        <div className="mb-3 flex items-center gap-2 border-b border-border pb-3">
          <ClipboardList size={16} className="text-ink-faint" />
          <h2 className="font-semibold text-ink">Follow-ups</h2>
          {query.data && (
            <span className="text-sm text-ink-faint">{query.data.follow_ups_total}</span>
          )}
        </div>

        {query.isLoading ? (
          <div className="space-y-3">
            <div className="h-20 animate-pulse rounded bg-surface-sunken" />
            <div className="h-20 animate-pulse rounded bg-surface-sunken" />
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
      </section>

      {(tab === 'overdue' || tab === 'all') && (
        <section
          className="rounded-lg border border-border bg-surface p-5 shadow-card"
          data-extension="check-backs"
        >
          <div className="mb-3 flex items-center gap-2 border-b border-border pb-3">
            <PauseCircle size={16} className="text-ink-faint" />
            <h2 className="font-semibold text-ink">Check-backs</h2>
            {query.data && (
              <span className="text-sm text-ink-faint">{query.data.check_backs_total}</span>
            )}
          </div>
          <p className="mb-3 text-sm text-ink-muted">
            Companies that said not now. These are not completed here — move the
            conversation on the company's page and the check-back clears itself.
          </p>

          {query.isLoading ? (
            <div className="h-12 animate-pulse rounded bg-surface-sunken" />
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
            <EmptySection>No company is parked waiting for a check-back.</EmptySection>
          )}
        </section>
      )}
    </div>
  );
}
