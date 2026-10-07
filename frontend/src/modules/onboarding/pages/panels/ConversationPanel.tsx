/**
 * The Activity tab (frontend-plan §8.5): the conversation path, then the activity
 * timeline with its composer (§6.8), as in the Salesforce activity timeline and the
 * Dynamics timeline. Contacts are in the record's right column
 * (`CompanyRelatedCards`).
 *
 * **The gauge query lives here, not in the shell.** The page knows nothing about the
 * conversation gauge, so the gauge calls its own hook here; it costs no round trip,
 * because this panel is mounted with the rest of the page.
 *
 * **Why the activity list comes in as props.** The page calls the activity query
 * before its early returns, so the profile and the activities start together on the
 * first render. A panel that is only mounted once the profile has resolved could not
 * start its fetch until then, turning one round trip into two. So the query and its
 * paging stay in the page, and this panel is presentational for them.
 *
 * The `data-extension` hooks for the gauge and the activities are stable.
 */

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  EmptyLine,
  Input,
  Panel,
  Select,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@/components';
import { Icon, type IconComponent } from '@/design/icons';
import { formatDate, formatDateTime, humanize, nowForDateTimeInput } from '@/lib/format';

import { CONVERSATION_STATUS, ConversationPath, OpenDealPrompt, actorLabel } from '../../components';
import { ConversationBadge } from '../../components/StatusBadge';
import {
  useConversationHistory,
  useExporterConversation,
  useFollowUps,
  useLogExporterActivity,
} from '../../hooks';
import type {
  ExporterActivity,
  ExporterActivityType,
  ExporterConversation,
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

const ACTIVITY_LABEL: Record<ExporterActivityType, string> = {
  CALL: 'Call',
  MEETING: 'Meeting',
  EMAIL: 'Email',
  NOTE: 'Note',
  TASK: 'Task',
  FOLLOW_UP: 'Follow-up',
};

/** The composer's button, a verb and an object (frontend-plan §5.7). */
const ACTIVITY_VERB: Record<ExporterActivityType, string> = {
  CALL: 'Log call',
  MEETING: 'Log meeting',
  EMAIL: 'Log email',
  NOTE: 'Add note',
  TASK: 'Add task',
  FOLLOW_UP: 'Add follow-up',
};

const ACTIVITY_ICON: Record<ExporterActivityType, IconComponent> = {
  CALL: Icon.phone,
  MEETING: Icon.calendar,
  EMAIL: Icon.email,
  NOTE: Icon.edit,
  TASK: Icon.checklist,
  FOLLOW_UP: Icon.followUp,
};

/**
 * The activity composer (frontend-plan §6.8), as in the Salesforce activity
 * composer: a tab per kind, a subject, an optional body, and a due date for a task
 * or a follow-up. Staff only. The server decides what is valid; a refusal is a toast
 * in its words and the draft stays.
 */
function ActivityComposer({
  customerId,
  onLogged,
  focusRequested,
  onFocusHandled,
}: {
  customerId: string;
  onLogged: () => void;
  focusRequested: boolean;
  onFocusHandled?: () => void;
}) {
  const mutation = useLogExporterActivity(customerId);
  const [type, setType] = useState<ExporterActivityType>('CALL');
  const [subject, setSubject] = useState('');
  const [notes, setNotes] = useState('');
  const [dueAt, setDueAt] = useState('');
  const subjectRef = useRef<HTMLInputElement>(null);
  const dueAllowed = type === 'TASK' || type === 'FOLLOW_UP';

  useEffect(() => {
    if (!focusRequested) return;
    setType('CALL');
    subjectRef.current?.focus();
    onFocusHandled?.();
  }, [focusRequested, onFocusHandled]);

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
      setSubject('');
      setNotes('');
      setDueAt('');
      onLogged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not log activity');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="activity-composer">
      <Tabs value={type} onValueChange={(next) => setType(next as ExporterActivityType)}>
        <TabsList aria-label="Kind of activity">
          {ACTIVITY_TYPES.map((value) => (
            <TabsTrigger key={value} value={value}>
              {ACTIVITY_LABEL[value]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <label className="block text-caption text-ink-3">
        Subject *
        <Input
          ref={subjectRef}
          className="mt-1"
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
          placeholder={type === 'CALL' ? 'Called about bank statements' : 'What happened or needs to happen?'}
          required
        />
      </label>
      <label className="block text-caption text-ink-3">
        Notes
        <Textarea
          className="mt-1 min-h-16 resize-y"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional"
        />
      </label>
      <div className="flex flex-wrap items-end justify-between gap-3">
        {dueAllowed ? (
          <label className="block w-56 text-caption text-ink-3">
            Due
            {/* The calendar does not offer a moment that has already passed: the server
                refuses a follow-up that would arrive overdue, and an error after the
                fact is a worse way to learn it than a date that cannot be picked. */}
            <Input
              type="datetime-local"
              className="mt-1"
              min={nowForDateTimeInput()}
              value={dueAt}
              onChange={(event) => setDueAt(event.target.value)}
            />
          </label>
        ) : (
          <span />
        )}
        <Button type="submit" variant="primary" disabled={!subject.trim()} loading={mutation.isPending}>
          {ACTIVITY_VERB[type]}
        </Button>
      </div>
    </form>
  );
}

function ActivityItem({ activity }: { activity: ExporterActivity }) {
  const Glyph = ACTIVITY_ICON[activity.activity_type] ?? Icon.activity;
  return (
    <li className="flex gap-3 py-3">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-tint text-accent" aria-hidden>
        <Glyph size={16} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-body font-semibold text-ink">{activity.subject}</p>
          <span className="text-secondary text-ink-3">{formatDateTime(activity.occurred_at)}</span>
        </div>
        <p className="text-secondary text-ink-2">
          {ACTIVITY_LABEL[activity.activity_type] ?? humanize(activity.activity_type)} · {actorLabel(activity.actor_name, activity.actor_id)}
        </p>
        {activity.notes && <p className="mt-1 whitespace-pre-wrap text-body text-ink-2">{activity.notes}</p>}
        {activity.due_at && (
          <p className="mt-1 inline-flex items-center gap-1 text-secondary font-semibold text-attention">
            <Icon.followUp size={14} aria-hidden /> Due {formatDateTime(activity.due_at)}
          </p>
        )}
      </div>
    </li>
  );
}

/** The month an activity falls in, as the timeline groups them: "October 2026". */
function monthOf(value: string): string {
  return new Date(value).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

/** Open follow-ups on this company, soonest first: the timeline's *Upcoming*. */
function UpcomingFollowUps({ customerId }: { customerId: string }) {
  const query = useFollowUps({ customerId, state: 'OUTSTANDING', includeCheckBacks: false, limit: 20 });
  const items = [...(query.data?.follow_ups ?? [])].sort((a, b) => (a.due_at ?? '').localeCompare(b.due_at ?? ''));
  if (query.isLoading || query.isError || items.length === 0) return null;
  return (
    <section aria-label="Upcoming">
      <h4 className="text-caption font-semibold text-ink-3">Upcoming</h4>
      <ul className="divide-y divide-line">
        {items.map((item) => (
          <li key={item.activity_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <span className="flex min-w-0 items-center gap-2">
              <Icon.followUp size={16} className="shrink-0 text-ink-3" aria-hidden />
              <span className="truncate text-body text-ink">{item.subject}</span>
            </span>
            <span className="flex items-center gap-2">
              {item.is_overdue && <Badge tone="negative">Overdue</Badge>}
              {item.due_at && <span className="text-secondary text-ink-3">Due {formatDateTime(item.due_at)}</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A conversation value in the screen's words ("Spoke to them"), whatever the row holds. */
function conversationLabel(value: string): string {
  return CONVERSATION_STATUS[value as ExporterConversation]?.label ?? humanize(value);
}

function ConversationHistoryRow({ entry }: { entry: HistoryEntry }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-line py-2.5 last:border-b-0">
      <p className="text-body text-ink">
        {entry.from_value ? `${conversationLabel(entry.from_value)} → ` : ''}
        <span className="font-semibold">{conversationLabel(entry.to_value)}</span>
      </p>
      {/* The check-back date the move set, as the server recorded it. Read from
          `details` rather than re-derived: the history row is the record of what
          was promised at the time, which the company's current date is not. */}
      {typeof entry.details?.check_back_on === 'string' && (
        <span className="inline-flex items-center gap-1 text-caption font-medium text-attention">
          <Icon.followUp size={12} /> Check back {formatDate(entry.details.check_back_on)}
        </span>
      )}
      <span className="ml-auto text-caption text-ink-3">
        {formatDateTime(entry.occurred_at)}
      </span>
      {entry.reason && (
        <p className="w-full text-body text-ink-2">{entry.reason}</p>
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
      as="h3"
      data-extension="conversation-gauge"
      title="Conversation"
      description="How the sales conversation is going — on its own, beside the journey."
      actions={
        conversation.data && (
          <span data-testid="conversation-chip">
            <ConversationBadge value={conversation.data.conversation} checkBackOn={conversation.data.check_back_on} />
          </span>
        )
      }
    >
      {conversation.isLoading ? (
        <Skeleton className="h-20" />
      ) : conversation.isError ? (
        <p className="text-body text-negative">
          Could not load the conversation. {conversation.error.message}
        </p>
      ) : conversation.data ? (
        <div className="space-y-4">
          {conversation.data.check_back_on && (
            <p className="inline-flex items-center gap-1.5 text-body font-medium text-attention">
              <Icon.followUp size={14} /> Check back on{' '}
              {formatDate(conversation.data.check_back_on)}
            </p>
          )}

          {conversation.data.conversation === 'READY_NOW' && (
            <OpenDealPrompt customerId={customerId} isStaff={isStaff} />
          )}

          {/* The track always shows where the conversation stands; only the moves the
              server listed are buttons on it (frontend-plan §6.5). */}
          <ConversationPath
            customerId={customerId}
            value={conversation.data.conversation}
            checkBackOn={conversation.data.check_back_on}
            moves={conversation.data.allowed_moves}
          />
          {isStaff && conversation.data.allowed_moves.length === 0 && (
            <p className="text-body text-ink-2">
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
              <p className="text-body text-negative">
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
  activities: ExporterActivity[];
  activitiesLoading: boolean;
  activitiesFetching: boolean;
  activityType: ExporterActivityType | '';
  onActivityTypeChange: (value: ExporterActivityType | '') => void;
  activityPage: number;
  onActivityPageChange: (page: number) => void;
  /** Whether a further page exists. Decided by the page, which owns the page size. */
  hasNextActivityPage: boolean;
  /** Developer reads the CRM but writes nothing, so it gets no composer. */
  isStaff: boolean;
  /** The header's *Log a call*: focus the composer once, then say it was handled. */
  logRequested?: boolean;
  onLogHandled?: () => void;
}) {
  // Past activity, grouped by month, newest first (§6.8).
  const months: { month: string; items: ExporterActivity[] }[] = [];
  for (const activity of activities) {
    const month = monthOf(activity.occurred_at);
    const last = months[months.length - 1];
    if (last && last.month === month) last.items.push(activity);
    else months.push({ month, items: [activity] });
  }

  return (
    <div className="flex flex-col gap-4">
      {/* The conversation first: it is the answer to "how is this going", which is
          what someone opening this tab came for. The activity is the evidence. */}
      <ConversationSection customerId={customerId} isStaff={isStaff} />

      <Panel
        as="h3"
        data-extension="activities"
        title="Activity"
        description="Calls, meetings, emails, notes and follow-ups. Nothing here is edited later."
      >
        <div className="space-y-5">
          {isStaff && (
            <ActivityComposer
              customerId={customerId}
              onLogged={() => onActivityPageChange(0)}
              focusRequested={logRequested}
              onFocusHandled={onLogHandled}
            />
          )}

          <UpcomingFollowUps customerId={customerId} />

          <section aria-label="Past activity">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-caption font-semibold text-ink-3">Past activity</h4>
              <label className="flex items-center gap-2 text-caption text-ink-3">
                Show
                <Select
                  value={activityType}
                  onChange={(event) => {
                    onActivityTypeChange(event.target.value as ExporterActivityType | '');
                    onActivityPageChange(0);
                  }}
                  className="h-7 w-auto"
                >
                  <option value="">All activity</option>
                  {ACTIVITY_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {ACTIVITY_LABEL[value]}
                    </option>
                  ))}
                </Select>
              </label>
            </div>

            {activitiesLoading ? (
              <div className="mt-2 space-y-3">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </div>
            ) : activities.length === 0 ? (
              <EmptyLine>
                {activityPage > 0
                  ? 'No more activities on this page.'
                  : activityType
                    ? `No ${ACTIVITY_LABEL[activityType].toLowerCase()} activity yet.`
                    : 'No activity logged yet.'}
              </EmptyLine>
            ) : (
              months.map((group) => (
                <div key={group.month} className="mt-3">
                  <p className="border-b border-line pb-1 text-secondary font-semibold text-ink-2">{group.month}</p>
                  <ul className="divide-y divide-line">
                    {group.items.map((activity) => (
                      <ActivityItem key={activity.id} activity={activity} />
                    ))}
                  </ul>
                </div>
              ))
            )}

            {(activityPage > 0 || hasNextActivityPage) && (
              <div className="mt-3 flex justify-end gap-2">
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
                  Show earlier <Icon.caretRight size={14} aria-hidden />
                </Button>
              </div>
            )}
          </section>
        </div>
      </Panel>
    </div>
  );
}
