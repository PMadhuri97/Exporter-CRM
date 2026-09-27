/**
 * The conversation: the gauge, contacts, and the activity log — **owner:
 * Developer 3A** (architecture §9.3, L3-03, L3-04a, L3-11a-i).
 *
 * The sales relationship: how the conversation is going, who we talk to, and what
 * was said or done.
 *
 * **This file is written once, in Phase 1, and closed** (phase agreement §6.3).
 * Phase 2's only business on this screen is `components/OpenDealPrompt.tsx`, its
 * own file, and the same is true of whoever lands seam S2's button. That is why the
 * gauge section below delegates to two components rather than rendering the prompt
 * inline: a panel that stays closed has to put everything still-open behind a
 * seam.
 *
 * **The gauge query lives here, not in the shell.** The shell hands this panel
 * contacts and activities as props — see below for why that is deliberate and must
 * stay — but it knows nothing about the conversation gauge, and Developer 3 does
 * not edit `ExporterDetailPage.tsx`. So the gauge calls its own hook here. That
 * costs nothing the props were buying: the profile, contacts and activities still
 * start together on the first render, and the gauge is a fourth request alongside
 * them rather than a second round trip after them, because this panel is mounted
 * with the rest of the page.
 *
 * `AddContactForm`, `ContactRow`, `ActivityForm` and `ActivityRow` were
 * defined inline in `ExporterDetailPage.tsx` and moved here whole, because
 * every one of them is about contacts or activities and none is reusable
 * elsewhere. `FormPanel`, `DetailRow` and `EmptySection` went the other way,
 * to `@/components`, because they are about layout rather than this domain.
 *
 * **Why this panel takes its data as props instead of calling its own hooks.**
 * The obvious split — move `useExporterContacts` and `useExporterActivities`
 * in here — changes behaviour. The page calls all three queries before its
 * early returns, so profile, contacts and activities start together on the
 * first render. A panel that is only mounted once the profile has resolved
 * cannot start its fetches until then, turning one round trip into two. The
 * existing page test catches it: it awaits the profile heading and then
 * expects the contacts empty state synchronously.
 *
 * So the contact and activity query calls and the pagination state stay in the
 * shell, exactly where the page already had them, and this panel is presentational
 * **for those two**. The trade is deliberate: identical behaviour now, at the cost
 * of the shell still holding some of Developer 3's state until the two of you decide
 * to move it — see the phase report's note on U1.
 *
 * The gauge is the exception, and not an inconsistency: the shell was never given
 * that query to hold, and adding it there would mean editing a file Developer 3 does
 * not own to buy timing the gauge does not need. Nothing renders before the gauge
 * resolves except the gauge's own skeleton.
 *
 * Markup, classes, toasts and the `data-extension` hooks for contacts and
 * activities are byte-identical to what the page rendered before; the gauge
 * section is new.
 */

import {
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Mail,
  MessageSquarePlus,
  Phone,
  Plus,
  Star,
  UserRound,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { EmptySection, FormPanel } from '@/components';
import { formatDate, formatDateTime, humanize } from '@/lib/format';

import { ConversationGaugeControl, OpenDealPrompt } from '../../components';
import {
  useAddExporterContact,
  useConversationHistory,
  useExporterConversation,
  useLogExporterActivity,
} from '../../hooks';
import type {
  AddExporterContactRequest,
  ExporterActivity,
  ExporterActivityType,
  ExporterContact,
  HistoryEntry,
  LogExporterActivityRequest,
} from '../../types';

// Private to this panel. Exporting them tripped `react-refresh/only-export-components`
// (a typed array literal is not a "constant export" as that rule counts them), and
// the shell has no use for the list — it owns the page size, which lives there.
const ACTIVITY_TYPES: ExporterActivityType[] = [
  'CALL',
  'MEETING',
  'EMAIL',
  'NOTE',
  'TASK',
  'FOLLOW_UP',
];

function AddContactForm({
  customerId,
  onDone,
}: {
  customerId: string;
  onDone: () => void;
}) {
  const mutation = useAddExporterContact(customerId);
  const [form, setForm] = useState<AddExporterContactRequest>({
    name: '',
    role: null,
    email: null,
    phone: null,
    department: null,
    is_primary: false,
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    try {
      await mutation.mutateAsync({
        ...form,
        name: form.name.trim(),
        role: form.role?.trim() || null,
        email: form.email?.trim() || null,
        phone: form.phone?.trim() || null,
        department: form.department?.trim() || null,
      });
      toast.success('Contact added');
      onDone();
    } catch {
      toast.error('Could not add contact');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs font-medium text-ink-muted">
          Name *
          <input
            className="input mt-1"
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
            required
          />
        </label>
        <label className="text-xs font-medium text-ink-muted">
          Role / title
          <input
            className="input mt-1"
            value={form.role ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-muted">
          Email
          <input
            type="email"
            className="input mt-1"
            value={form.email ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-muted">
          Phone
          <input
            className="input mt-1"
            value={form.phone ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-muted md:col-span-2">
          Department
          <input
            className="input mt-1"
            value={form.department ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, department: event.target.value }))}
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-ink-muted">
        <input
          type="checkbox"
          checked={form.is_primary}
          onChange={(event) => setForm((prev) => ({ ...prev, is_primary: event.target.checked }))}
          className="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500"
        />
        Make this the primary contact
      </label>
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={mutation.isPending || !form.name.trim()}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? 'Adding…' : 'Add contact'}
        </button>
      </div>
    </form>
  );
}

function ContactRow({ contact }: { contact: ExporterContact }) {
  return (
    <div className="flex items-start gap-3 border-b border-border py-3 last:border-b-0">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-ink-muted">
        <UserRound size={17} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-ink">{contact.name}</p>
          {contact.is_primary_contact && (
            <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-900">
              <Star size={11} /> Primary
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-ink-muted">
          {[contact.role, contact.department].filter(Boolean).join(' · ') || 'No role added'}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-faint">
          {contact.email && (
            <a href={`mailto:${contact.email}`} className="inline-flex items-center gap-1 hover:text-ink">
              <Mail size={12} /> {contact.email}
            </a>
          )}
          {contact.phone && (
            <a href={`tel:${contact.phone}`} className="inline-flex items-center gap-1 hover:text-ink">
              <Phone size={12} /> {contact.phone}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function ActivityForm({
  customerId,
  onDone,
}: {
  customerId: string;
  onDone: () => void;
}) {
  const mutation = useLogExporterActivity(customerId);
  const [type, setType] = useState<ExporterActivityType>('NOTE');
  const [subject, setSubject] = useState('');
  const [notes, setNotes] = useState('');
  const [dueAt, setDueAt] = useState('');

  const dueAllowed = type === 'TASK' || type === 'FOLLOW_UP';

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!subject.trim()) return;
    const payload: LogExporterActivityRequest = {
      activity_type: type,
      subject: subject.trim(),
      notes: notes.trim() || null,
      due_at: dueAllowed && dueAt ? new Date(dueAt).toISOString() : null,
    };
    try {
      await mutation.mutateAsync(payload);
      toast.success('Activity logged');
      onDone();
    } catch {
      toast.error('Could not log activity');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-[180px_1fr]">
        <label className="text-xs font-medium text-ink-muted">
          Activity type
          <select
            className="input mt-1"
            value={type}
            onChange={(event) => setType(event.target.value as ExporterActivityType)}
          >
            {ACTIVITY_TYPES.map((value) => (
              <option key={value} value={value}>{humanize(value)}</option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-muted">
          Subject *
          <input
            className="input mt-1"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="What happened or needs to happen?"
            required
          />
        </label>
      </div>
      <label className="block text-xs font-medium text-ink-muted">
        Notes
        <textarea
          className="input mt-1 min-h-24 resize-y"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional context"
        />
      </label>
      {dueAllowed && (
        <label className="block max-w-xs text-xs font-medium text-ink-muted">
          Due date and time
          <input
            type="datetime-local"
            className="input mt-1"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
          />
        </label>
      )}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={mutation.isPending || !subject.trim()}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? 'Saving…' : 'Log activity'}
        </button>
      </div>
    </form>
  );
}

function ActivityRow({ activity }: { activity: ExporterActivity }) {
  return (
    <div className="grid gap-2 border-b border-border py-4 last:border-b-0 md:grid-cols-[130px_1fr_auto]">
      <div>
        <span className="inline-flex rounded-full bg-surface-sunken px-2 py-1 text-xs font-medium text-ink-muted">
          {humanize(activity.activity_type)}
        </span>
      </div>
      <div className="min-w-0">
        <p className="font-medium text-ink">{activity.subject}</p>
        {activity.notes && <p className="mt-1 whitespace-pre-wrap text-sm text-ink-muted">{activity.notes}</p>}
        {activity.due_at && (
          <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-status-review">
            <CalendarClock size={13} /> Due {formatDateTime(activity.due_at)}
          </p>
        )}
      </div>
      <div className="text-left text-xs text-ink-faint md:text-right">
        <p>{formatDateTime(activity.occurred_at)}</p>
        <p className="mt-1">Actor {activity.actor_id}</p>
      </div>
    </div>
  );
}

function ConversationHistoryRow({ entry }: { entry: HistoryEntry }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border py-2.5 last:border-b-0">
      <p className="text-sm text-ink">
        {entry.from_value ? `${humanize(entry.from_value)} → ` : ''}
        <span className="font-medium">{humanize(entry.to_value)}</span>
      </p>
      {/* The check-back date the move set, as the server recorded it. Read from
          `details` rather than re-derived: the history row is the record of what
          was promised at the time, which the company's current date is not. */}
      {typeof entry.details?.check_back_on === 'string' && (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-status-review">
          <CalendarClock size={12} /> Check back {formatDate(entry.details.check_back_on)}
        </span>
      )}
      <span className="ml-auto text-xs text-ink-faint">
        {formatDateTime(entry.occurred_at)}
      </span>
      {entry.reason && (
        <p className="w-full text-sm text-ink-muted">{entry.reason}</p>
      )}
    </div>
  );
}

/**
 * The gauge, its check-back date, its moves and its history.
 *
 * Every rule is the server's. This renders `allowed_moves` as served and shows
 * `journey` when that list is empty, because "the gauge does not apply to a lead
 * yet" and "your role may not move it" are different sentences and the screen must
 * not guess which — the server tells it the journey, so it can say the true one.
 */
function ConversationSection({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  const conversation = useExporterConversation(customerId);
  const history = useConversationHistory(customerId);

  return (
    <section
      className="rounded-lg border border-border bg-surface p-5 shadow-card xl:col-span-2"
      data-extension="conversation-gauge"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-ink">Conversation</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            How the sales conversation is going — on its own, beside the journey.
          </p>
        </div>
        {conversation.data && (
          <span
            className="inline-flex items-center rounded-full bg-surface-sunken px-2.5 py-1 text-sm font-medium text-ink"
            data-testid="conversation-chip"
          >
            {humanize(conversation.data.conversation)}
          </span>
        )}
      </div>

      {conversation.isLoading ? (
        <div className="h-20 animate-pulse rounded bg-surface-sunken" />
      ) : conversation.isError ? (
        <p className="text-sm text-status-failed">
          Could not load the conversation. {conversation.error.message}
        </p>
      ) : conversation.data ? (
        <div className="space-y-4">
          {conversation.data.check_back_on && (
            <p className="inline-flex items-center gap-1.5 text-sm font-medium text-status-review">
              <CalendarClock size={14} /> Check back on{' '}
              {formatDate(conversation.data.check_back_on)}
            </p>
          )}

          {conversation.data.conversation === 'READY_NOW' && (
            <OpenDealPrompt customerId={customerId} isStaff={isStaff} />
          )}

          {isStaff && conversation.data.allowed_moves.length === 0 ? (
            <p className="text-sm text-ink-muted">
              {conversation.data.journey === 'LEAD'
                ? 'The conversation gauge applies once this company is a prospect.'
                : 'No conversation moves are available to you.'}
            </p>
          ) : (
            <ConversationGaugeControl
              customerId={customerId}
              moves={conversation.data.allowed_moves}
            />
          )}

          <div className="border-t border-border pt-3">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              History
            </h3>
            {history.isLoading ? (
              <div className="h-12 animate-pulse rounded bg-surface-sunken" />
            ) : history.isError ? (
              <p className="text-sm text-status-failed">
                Could not load the conversation history. {history.error.message}
              </p>
            ) : history.data && history.data.entries.length > 0 ? (
              <div>
                {history.data.entries.map((entry) => (
                  <ConversationHistoryRow key={entry.id} entry={entry} />
                ))}
              </div>
            ) : (
              <EmptySection>
                No conversation changes recorded yet.
              </EmptySection>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function ConversationPanel({
  customerId,
  contacts,
  contactsLoading,
  activities,
  activitiesLoading,
  activitiesFetching,
  activityType,
  onActivityTypeChange,
  activityPage,
  onActivityPageChange,
  hasNextActivityPage,
  isStaff,
}: {
  customerId: string;
  contacts: ExporterContact[];
  contactsLoading: boolean;
  activities: ExporterActivity[];
  activitiesLoading: boolean;
  activitiesFetching: boolean;
  activityType: ExporterActivityType | '';
  onActivityTypeChange: (value: ExporterActivityType | '') => void;
  activityPage: number;
  onActivityPageChange: (page: number) => void;
  /** Whether a further page exists. Decided by the shell, which owns the page
   * size and therefore the only thing the answer depends on. */
  hasNextActivityPage: boolean;
  /** DEVELOPER reads the CRM but writes nothing, so it gets no action buttons. */
  isStaff: boolean;
}) {
  const [showContactForm, setShowContactForm] = useState(false);
  const [showActivityForm, setShowActivityForm] = useState(false);

  return (
    <div className="grid gap-5 xl:grid-cols-[0.9fr_1.6fr]">
      {/* The gauge first: it is the answer to "how is this going", which is what
          someone opening this tab came for. Contacts and the activity log are the
          evidence behind it. */}
      <ConversationSection customerId={customerId} isStaff={isStaff} />

      <section className="rounded-lg border border-border bg-surface p-5 shadow-card" data-extension="contacts">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-ink">Contacts</h2>
            <p className="mt-0.5 text-sm text-ink-muted">People connected to this exporter.</p>
          </div>
          {isStaff && (
            <button
              type="button"
              onClick={() => setShowContactForm(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink hover:bg-surface-subtle"
            >
              <Plus size={15} /> Add contact
            </button>
          )}
        </div>

        {showContactForm && <FormPanel title="Add contact" onClose={() => setShowContactForm(false)}><AddContactForm customerId={customerId} onDone={() => setShowContactForm(false)} /></FormPanel>}

        {contactsLoading ? (
          <div className="space-y-3"><div className="h-16 animate-pulse rounded bg-surface-sunken" /><div className="h-16 animate-pulse rounded bg-surface-sunken" /></div>
        ) : contacts.length === 0 ? (
          <EmptySection>No contacts yet. Add the first person you work with.</EmptySection>
        ) : (
          <div>{contacts.map((contact) => <ContactRow key={contact.id} contact={contact} />)}</div>
        )}
      </section>

      <section className="rounded-lg border border-border bg-surface p-5 shadow-card" data-extension="activities">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-ink">Activity</h2>
            <p className="mt-0.5 text-sm text-ink-muted">Append-only relationship history and follow-ups.</p>
          </div>
          {isStaff && (
            <button
              type="button"
              onClick={() => setShowActivityForm(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              <MessageSquarePlus size={15} /> Log activity
            </button>
          )}
        </div>

        {showActivityForm && <FormPanel title="Log activity" onClose={() => setShowActivityForm(false)}><ActivityForm customerId={customerId} onDone={() => { setShowActivityForm(false); onActivityPageChange(0); }} /></FormPanel>}

        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
          <label className="flex items-center gap-2 text-xs font-medium text-ink-muted">
            Filter
            <select
              value={activityType}
              onChange={(event) => { onActivityTypeChange(event.target.value as ExporterActivityType | ''); onActivityPageChange(0); }}
              className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-brand-500"
            >
              <option value="">All activity</option>
              {ACTIVITY_TYPES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
            </select>
          </label>
          <span className="text-xs text-ink-faint">Page {activityPage + 1}</span>
        </div>

        {activitiesLoading ? (
          <div className="space-y-3"><div className="h-20 animate-pulse rounded bg-surface-sunken" /><div className="h-20 animate-pulse rounded bg-surface-sunken" /></div>
        ) : activities.length === 0 ? (
          <EmptySection>{activityPage > 0 ? 'No more activities on this page.' : activityType ? `No ${humanize(activityType).toLowerCase()} activity yet.` : 'No activity logged yet.'}</EmptySection>
        ) : (
          <div>{activities.map((activity) => <ActivityRow key={activity.id} activity={activity} />)}</div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onActivityPageChange(Math.max(0, activityPage - 1))}
            disabled={activityPage === 0 || activitiesFetching}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft size={14} /> Previous
          </button>
          <button
            type="button"
            onClick={() => onActivityPageChange(activityPage + 1)}
            disabled={!hasNextActivityPage || activitiesFetching}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      </section>
    </div>
  );
}
