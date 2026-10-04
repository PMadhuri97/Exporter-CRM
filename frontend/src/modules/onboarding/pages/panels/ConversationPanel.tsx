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
 * of the shell still holding some of Developer 3's state until Developers 2 and 3
 * decide to move it.
 *
 * The gauge is the exception, and not an inconsistency: the shell was never given
 * that query to hold, and adding it there would mean editing a file Developer 3 does
 * not own to buy timing the gauge does not need. Nothing renders before the gauge
 * resolves except the gauge's own skeleton.
 *
 * The `data-extension` hooks for the gauge, contacts and activities are stable;
 * the markup is built from the shared primitives in `@/components`.
 */

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Tag,
  EmptyLine,
  FormPanel,
  Input,
  Panel,
  Select,
  Skeleton,
  Textarea,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate, formatDateTime, humanize } from '@/lib/format';

import { GaugeTrack, OpenDealPrompt, actorLabel } from '../../components';
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
        <label className="text-xs font-medium text-ink-2">
          Name *
          <Input
            className="mt-1"
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
            required
          />
        </label>
        <label className="text-xs font-medium text-ink-2">
          Role / title
          <Input
            className="mt-1"
            value={form.role ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-2">
          Email
          <Input
            type="email"
            className="mt-1"
            value={form.email ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-2">
          Phone
          <Input
            className="mt-1"
            value={form.phone ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
          />
        </label>
        <label className="text-xs font-medium text-ink-2 md:col-span-2">
          Department
          <Input
            className="mt-1"
            value={form.department ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, department: event.target.value }))}
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-ink-2">
        <input
          type="checkbox"
          checked={form.is_primary}
          onChange={(event) => setForm((prev) => ({ ...prev, is_primary: event.target.checked }))}
          className="h-4 w-4 rounded border-line-strong accent-ink"
        />
        Make this the primary contact
      </label>
      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          disabled={!form.name.trim()}
          loading={mutation.isPending}
        >
          Add contact
        </Button>
      </div>
    </form>
  );
}

function ContactRow({ contact }: { contact: ExporterContact }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-surface p-3.5" data-testid="person-tile">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sunken font-display text-lead text-ink-2" aria-hidden>
        {contact.name.trim().charAt(0).toUpperCase() || <Icon.person size={17} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-ink [overflow-wrap:anywhere]">{contact.name}</p>
          {contact.is_primary_contact && (
            <Tag tone="ink" icon={<Icon.primary size={11} />}>
              Primary
            </Tag>
          )}
        </div>
        <p className="mt-0.5 text-sm text-ink-2">
          {[contact.role, contact.department].filter(Boolean).join(' · ') || 'No role added'}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
          {contact.email && (
            <a href={`mailto:${contact.email}`} className="inline-flex items-center gap-1 hover:text-ink">
              <Icon.email size={12} /> {contact.email}
            </a>
          )}
          {contact.phone && (
            <a href={`tel:${contact.phone}`} className="inline-flex items-center gap-1 hover:text-ink">
              <Icon.phone size={12} /> {contact.phone}
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
        <label className="text-xs font-medium text-ink-2">
          Activity type
          <Select
            className="mt-1"
            value={type}
            onChange={(event) => setType(event.target.value as ExporterActivityType)}
          >
            {ACTIVITY_TYPES.map((value) => (
              <option key={value} value={value}>{humanize(value)}</option>
            ))}
          </Select>
        </label>
        <label className="text-xs font-medium text-ink-2">
          Subject *
          <Input
            className="mt-1"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="What happened or needs to happen?"
            required
          />
        </label>
      </div>
      <label className="block text-xs font-medium text-ink-2">
        Notes
        <Textarea
          className="mt-1 min-h-24 resize-y"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional context"
        />
      </label>
      {dueAllowed && (
        <label className="block max-w-xs text-xs font-medium text-ink-2">
          Due date and time
          <Input
            type="datetime-local"
            className="mt-1"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
          />
        </label>
      )}
      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          disabled={!subject.trim()}
          loading={mutation.isPending}
        >
          Log activity
        </Button>
      </div>
    </form>
  );
}

function ActivityRow({ activity }: { activity: ExporterActivity }) {
  return (
    <div className="grid gap-2 border-b border-line py-4 last:border-b-0 md:grid-cols-[130px_1fr_auto]">
      <div>
        <Tag>{humanize(activity.activity_type)}</Tag>
      </div>
      <div className="min-w-0">
        <p className="font-medium text-ink">{activity.subject}</p>
        {activity.notes && <p className="mt-1 whitespace-pre-wrap text-sm text-ink-2">{activity.notes}</p>}
        {activity.due_at && (
          <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-attention">
            <Icon.followUp size={13} /> Due {formatDateTime(activity.due_at)}
          </p>
        )}
      </div>
      <div className="text-left text-xs text-ink-3 md:text-right">
        <p>{formatDateTime(activity.occurred_at)}</p>
        <p className="mt-1">By {actorLabel(activity.actor_name, activity.actor_id)}</p>
      </div>
    </div>
  );
}

function ConversationHistoryRow({ entry }: { entry: HistoryEntry }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-line py-2.5 last:border-b-0">
      <p className="text-sm text-ink">
        {entry.from_value ? `${humanize(entry.from_value)} → ` : ''}
        <span className="font-medium">{humanize(entry.to_value)}</span>
      </p>
      {/* The check-back date the move set, as the server recorded it. Read from
          `details` rather than re-derived: the history row is the record of what
          was promised at the time, which the company's current date is not. */}
      {typeof entry.details?.check_back_on === 'string' && (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-attention">
          <Icon.followUp size={12} /> Check back {formatDate(entry.details.check_back_on)}
        </span>
      )}
      <span className="ml-auto text-xs text-ink-3">
        {formatDateTime(entry.occurred_at)}
      </span>
      {entry.reason && (
        <p className="w-full text-sm text-ink-2">{entry.reason}</p>
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
    <Panel
      className="xl:col-span-2"
      data-extension="conversation-gauge"
      title="Conversation"
      description="How the sales conversation is going — on its own, beside the journey."
      actions={
        conversation.data && (
          <Tag tone="progress" className="px-2.5 py-1 text-sm" data-testid="conversation-chip">
            {humanize(conversation.data.conversation)}
          </Tag>
        )
      }
    >
      {conversation.isLoading ? (
        <Skeleton className="h-20" />
      ) : conversation.isError ? (
        <p className="text-sm text-negative">
          Could not load the conversation. {conversation.error.message}
        </p>
      ) : conversation.data ? (
        <div className="space-y-4">
          {conversation.data.check_back_on && (
            <p className="inline-flex items-center gap-1.5 text-sm font-medium text-attention">
              <Icon.followUp size={14} /> Check back on{' '}
              {formatDate(conversation.data.check_back_on)}
            </p>
          )}

          {conversation.data.conversation === 'READY_NOW' && (
            <OpenDealPrompt customerId={customerId} isStaff={isStaff} />
          )}

          {/* The track always shows where the conversation stands; only the moves the
              server listed are buttons on it (frontend-plan §6.2). */}
          <GaugeTrack
            customerId={customerId}
            value={conversation.data.conversation}
            checkBackOn={conversation.data.check_back_on}
            moves={conversation.data.allowed_moves}
          />
          {isStaff && conversation.data.allowed_moves.length === 0 && (
            <p className="text-sm text-ink-2">
              {conversation.data.journey === 'LEAD'
                ? 'The conversation gauge applies once this company is a prospect.'
                : 'No conversation moves are available to you.'}
            </p>
          )}

          <div className="border-t border-line pt-3">
            <h3 className="mb-1 text-caption font-medium text-ink-3">
              History
            </h3>
            {history.isLoading ? (
              <Skeleton className="h-12" />
            ) : history.isError ? (
              <p className="text-sm text-negative">
                Could not load the conversation history. {history.error.message}
              </p>
            ) : history.data && history.data.entries.length > 0 ? (
              <div>
                {history.data.entries.map((entry) => (
                  <ConversationHistoryRow key={entry.id} entry={entry} />
                ))}
              </div>
            ) : (
              <EmptyLine>No conversation changes recorded yet.</EmptyLine>
            )}
          </div>
        </div>
      ) : null}
    </Panel>
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
  logRequested = false,
  onLogHandled,
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
  /** The dossier's `l` key: open the activity composer once, then say it was handled. */
  logRequested?: boolean;
  onLogHandled?: () => void;
}) {
  const [showContactForm, setShowContactForm] = useState(false);
  const [showActivityForm, setShowActivityForm] = useState(false);
  useEffect(() => {
    if (!logRequested) return;
    if (isStaff) setShowActivityForm(true);
    onLogHandled?.();
  }, [logRequested, isStaff, onLogHandled]);

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      {/* The gauge first: it is the answer to "how is this going", which is what
          someone opening this tab came for. Contacts and the activity log are the
          evidence behind it. */}
      <div className="xl:col-span-2">
        <ConversationSection customerId={customerId} isStaff={isStaff} />
      </div>

      <Panel
        data-extension="contacts"
        title="People"
        description="Who we deal with at this company."
        actions={
          isStaff && (
            <Button size="sm" onClick={() => setShowContactForm(true)}>
              <Icon.add size={15} aria-hidden /> Add a person
            </Button>
          )
        }
      >

        {showContactForm && <FormPanel title="Add a person" onClose={() => setShowContactForm(false)}><AddContactForm customerId={customerId} onDone={() => setShowContactForm(false)} /></FormPanel>}

        {contactsLoading ? (
          <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
        ) : contacts.length === 0 ? (
          <EmptyLine>No one recorded yet.</EmptyLine>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">{contacts.map((contact) => <ContactRow key={contact.id} contact={contact} />)}</div>
        )}
      </Panel>

      <Panel
        data-extension="activities"
        title="Thread"
        description="Calls, meetings, notes and follow-ups, newest first. Nothing here is edited later."
        actions={
          isStaff && (
            <Button size="sm" variant="primary" onClick={() => setShowActivityForm(true)}>
              <Icon.logActivity size={15} aria-hidden /> Log an activity
            </Button>
          )
        }
      >

        {showActivityForm && <FormPanel title="Log an activity" onClose={() => setShowActivityForm(false)}><ActivityForm customerId={customerId} onDone={() => { setShowActivityForm(false); onActivityPageChange(0); }} /></FormPanel>}

        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <label className="flex items-center gap-2 text-caption font-medium text-ink-2">
            Filter
            <Select
              value={activityType}
              onChange={(event) => { onActivityTypeChange(event.target.value as ExporterActivityType | ''); onActivityPageChange(0); }}
              className="w-auto py-1.5"
            >
              <option value="">All activity</option>
              {ACTIVITY_TYPES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
            </Select>
          </label>
          <span className="text-xs text-ink-3">Page {activityPage + 1}</span>
        </div>

        {activitiesLoading ? (
          <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
        ) : activities.length === 0 ? (
          <EmptyLine>{activityPage > 0 ? 'No more activities on this page.' : activityType ? `No ${humanize(activityType).toLowerCase()} activity yet.` : 'No activity logged yet.'}</EmptyLine>
        ) : (
          <div>{activities.map((activity) => <ActivityRow key={activity.id} activity={activity} />)}</div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <Button
            size="sm"
            onClick={() => onActivityPageChange(Math.max(0, activityPage - 1))}
            disabled={activityPage === 0 || activitiesFetching}
          >
            <Icon.caretLeft size={14} aria-hidden /> Newer
          </Button>
          <Button
            size="sm"
            onClick={() => onActivityPageChange(activityPage + 1)}
            disabled={!hasNextActivityPage || activitiesFetching}
          >
            Earlier <Icon.caretRight size={14} aria-hidden />
          </Button>
        </div>
      </Panel>
    </div>
  );
}
