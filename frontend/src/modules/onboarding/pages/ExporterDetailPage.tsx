import { format } from 'date-fns';
import {
  ArrowLeft,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Mail,
  MessageSquarePlus,
  Phone,
  Plus,
  Star,
  UserRound,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { useCurrentUser } from '@/platform/auth';
import { MaskedValue } from '@/platform/mask';

import {
  DocumentRequirementsSection,
  LifecycleMoveControl,
  StageChip,
  VerificationSection,
} from '../components';
import {
  useAddExporterContact,
  useExporterActivities,
  useExporterContacts,
  useExporterProfileDetail,
  useLogExporterActivity,
} from '../hooks';
import type {
  AddExporterContactRequest,
  ExporterActivity,
  ExporterActivityType,
  ExporterContact,
  ExporterProfileDetail,
  LogExporterActivityRequest,
} from '../types';

const ACTIVITY_TYPES: ExporterActivityType[] = [
  'CALL',
  'MEETING',
  'EMAIL',
  'NOTE',
  'TASK',
  'FOLLOW_UP',
];
const ACTIVITY_PAGE_SIZE = 8;

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  return format(new Date(value), 'dd MMM yyyy');
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return format(new Date(value), 'dd MMM yyyy, HH:mm');
}

function displayName(profile: ExporterProfileDetail): string {
  return profile.onboarding_history[0]?.legal_name ?? 'Unnamed exporter';
}

function humanize(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-4 border-b border-border py-3 last:border-b-0">
      <dt className="text-sm text-ink-faint">{label}</dt>
      <dd className="min-w-0 text-sm text-ink">{children}</dd>
    </div>
  );
}

function EmptySection({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-6 text-center text-sm text-ink-muted">
      {children}
    </div>
  );
}

function FormPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-4 rounded-lg border border-border bg-surface-subtle p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-ink-faint hover:bg-surface-sunken hover:text-ink"
          aria-label={`Close ${title}`}
        >
          <X size={16} />
        </button>
      </div>
      {children}
    </div>
  );
}

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

export function ExporterDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const currentUser = useCurrentUser();
  const { data: profile, isLoading, isError } = useExporterProfileDetail(customerId);
  const [showContactForm, setShowContactForm] = useState(false);
  const [showActivityForm, setShowActivityForm] = useState(false);
  const [activityType, setActivityType] = useState<ExporterActivityType | ''>('');
  const [activityPage, setActivityPage] = useState(0);

  const contactQuery = useExporterContacts(customerId);
  const activityParams = useMemo(
    () => ({
      activityType: activityType || undefined,
      limit: ACTIVITY_PAGE_SIZE,
      offset: activityPage * ACTIVITY_PAGE_SIZE,
    }),
    [activityType, activityPage],
  );
  const activityQuery = useExporterActivities(customerId, activityParams);

  if (!customerId) {
    return <p className="text-sm text-status-failed">Exporter id is missing.</p>;
  }

  if (isLoading) {
    return (
      <div className="space-y-5" aria-label="Loading exporter">
        <div className="h-8 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="h-36 animate-pulse rounded-lg border border-border bg-surface" />
        <div className="h-64 animate-pulse rounded-lg border border-border bg-surface" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center shadow-card">
        <p className="font-medium text-ink">Couldn't load this exporter.</p>
        <p className="mt-1 text-sm text-ink-muted">The record may no longer exist or the request failed.</p>
        <Link to="/exporters" className="mt-4 inline-block text-sm font-medium text-brand-600 underline">
          Back to exporters
        </Link>
      </div>
    );
  }

  const isOwner = profile.relationship_manager_user_id === currentUser.id;
  // DEVELOPER reads the CRM (masked) but writes nothing and cannot load
  // verification results — the backend refuses those with 403.
  const isStaff = currentUser.role !== 'DEVELOPER';
  const name = displayName(profile);
  const contacts = contactQuery.data?.contacts ?? profile.contacts;
  const activities = activityQuery.data?.activities ?? [];
  const hasNextActivityPage = activities.length === ACTIVITY_PAGE_SIZE;

  return (
    <div className="space-y-5">
      <div>
        <Link
          to="/exporters"
          className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
        >
          <ArrowLeft size={15} />
          Exporters
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold text-ink">{name}</h1>
              <StageChip status={profile.lifecycle_status} showDetail />
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              Added {formatDate(profile.date_added)}
              {profile.relationship_manager ? ` · Owner: ${profile.relationship_manager}` : ''}
            </p>
          </div>
          <LifecycleMoveControl
            customerId={customerId}
            currentStatus={profile.lifecycle_status}
          />
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
          <h2 className="font-semibold text-ink">Exporter profile</h2>
          <dl className="mt-2">
            <DetailRow label="PAN"><MaskedValue value={profile.pan} isOwner={isOwner} /></DetailRow>
            <DetailRow label="GSTIN"><MaskedValue value={profile.gstin} isOwner={isOwner} /></DetailRow>
            <DetailRow label="IEC"><MaskedValue value={profile.iec} isOwner={isOwner} /></DetailRow>
            <DetailRow label="Source">{humanize(profile.source)}</DetailRow>
            <DetailRow label="Industry">{profile.industry ?? '—'}</DetailRow>
            <DetailRow label="Established">{profile.year_established ?? '—'}</DetailRow>
            <DetailRow label="Website">
              {profile.website ? (
                <a href={profile.website} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-brand-600 hover:underline">
                  <span className="truncate">{profile.website}</span><ExternalLink size={13} className="shrink-0" />
                </a>
              ) : '—'}
            </DetailRow>
          </dl>
        </section>

        <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
          <h2 className="font-semibold text-ink">Business footprint</h2>
          <dl className="mt-2">
            <DetailRow label="Export markets">{profile.export_markets?.length ? profile.export_markets.join(', ') : '—'}</DetailRow>
            <DetailRow label="Products">{profile.products?.length ? profile.products.join(', ') : '—'}</DetailRow>
            <DetailRow label="Created">{formatDate(profile.created_at)}</DetailRow>
            <DetailRow label="Last updated">{formatDate(profile.updated_at)}</DetailRow>
          </dl>
        </section>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.6fr]">
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

          {contactQuery.isLoading ? (
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

          {showActivityForm && <FormPanel title="Log activity" onClose={() => setShowActivityForm(false)}><ActivityForm customerId={customerId} onDone={() => { setShowActivityForm(false); setActivityPage(0); }} /></FormPanel>}

          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
            <label className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              Filter
              <select
                value={activityType}
                onChange={(event) => { setActivityType(event.target.value as ExporterActivityType | ''); setActivityPage(0); }}
                className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-brand-500"
              >
                <option value="">All activity</option>
                {ACTIVITY_TYPES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
              </select>
            </label>
            <span className="text-xs text-ink-faint">Page {activityPage + 1}</span>
          </div>

          {activityQuery.isLoading ? (
            <div className="space-y-3"><div className="h-20 animate-pulse rounded bg-surface-sunken" /><div className="h-20 animate-pulse rounded bg-surface-sunken" /></div>
          ) : activities.length === 0 ? (
            <EmptySection>{activityPage > 0 ? 'No more activities on this page.' : activityType ? `No ${humanize(activityType).toLowerCase()} activity yet.` : 'No activity logged yet.'}</EmptySection>
          ) : (
            <div>{activities.map((activity) => <ActivityRow key={activity.id} activity={activity} />)}</div>
          )}

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setActivityPage((page) => Math.max(0, page - 1))}
              disabled={activityPage === 0 || activityQuery.isFetching}
              className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <button
              type="button"
              onClick={() => setActivityPage((page) => page + 1)}
              disabled={!hasNextActivityPage || activityQuery.isFetching}
              className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        </section>
      </div>

      <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-ink">Onboarding history</h2>
            <p className="mt-0.5 text-sm text-ink-muted">Requests linked to this exporter record.</p>
          </div>
          <span className="text-xs tabular-nums text-ink-faint">{profile.onboarding_history.length} total</span>
        </div>
        {profile.onboarding_history.length === 0 ? <EmptySection>No onboarding requests yet.</EmptySection> : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead><tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint"><th className="px-4 py-2.5 font-medium">Company</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Initiated</th><th className="px-4 py-2.5 font-medium">Completed</th><th className="px-4 py-2.5 font-medium">Rejection</th></tr></thead>
              <tbody className="divide-y divide-border">{profile.onboarding_history.map((entry) => <tr key={entry.onboarding_id}><td className="px-4 py-3 font-medium text-ink">{entry.legal_name}</td><td className="px-4 py-3 text-ink-muted">{humanize(entry.status)}</td><td className="px-4 py-3 text-ink-muted">{formatDate(entry.initiated_at)}</td><td className="px-4 py-3 text-ink-muted">{formatDate(entry.completed_at)}</td><td className="px-4 py-3 text-ink-muted">{entry.rejection_category ? humanize(entry.rejection_category) : '—'}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>

      {/* Not behind `isStaff`, unlike the screening workspace below. This one
          reads GitOps-managed policy, not customer data — there is no PII in a
          list of document type names — and the endpoint admits DEVELOPER for
          exactly that reason. Hiding it here would be a stricter rule than the
          backend's, enforced in the one place a user can't see it. */}
      <DocumentRequirementsSection industry={profile.industry} />

      {isStaff && <VerificationSection customerId={customerId} />}
    </div>
  );
}
