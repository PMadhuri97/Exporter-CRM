/**
 * The ledger — the company's story, from the shared history log (architecture §3.1,
 * L1-11; drawn as frontend-plan §6.5 lays out).
 *
 * Days are separated by a dated rule; each event has its time, its lane (the row's
 * dimension) and one line saying what changed. **Rows the server wrote together —
 * the same `occurred_at` — are one event** (they were one transaction, architecture
 * §8): they render as one entry with sub-lines, honestly labelled "same moment", and
 * their order inside it is not presented as a sequence. Lanes are drawn in ink: a
 * dimension is not a state, so it gets no colour. The lane chips are the dimensions
 * actually seen — a role the server sends no background-check rows never sees that
 * chip — and filtering is the route's own `?dimension=`, done by the server.
 *
 * Every recorded change — journey, each gauge, marker, profile edits, deals —
 * newest first, with who, when and why. Nothing is ever edited, so there is
 * nothing to act on here: it is a record.
 *
 * Values are shown as the server recorded them. A profile edit's before and
 * after come from the row's `details`, already masked on the server for roles
 * that may not see tax identifiers; nothing here unmasks or re-derives them.
 *
 * Each row says what changed, not only the value it reached. Where a row is about
 * one thing of several — a buyer's details, one screening item, one criterion, one
 * check — its `details` name it, with the keys the contracts guarantee
 * (`history-row.md` §3): the item's and criterion's labels come from the same
 * server-served catalogue and criteria the Background check and Qualification tabs
 * use, falling back to the key. Who acted is shown by name (`actor_name`).
 */

import { useEffect, useMemo, useState } from 'react';

import { format } from 'date-fns';

import { Button, EmptyLine, ErrorState, Skeleton } from '@/components';
import { Icon, type IconComponent } from '@/design/icons';
import { cn } from '@/lib/cn';
import { humanize } from '@/lib/format';

import { useCompanyHistory, useDealHistory, useQualification, useScreeningReview } from '../hooks';
import type { HistoryDimension, HistoryEntry, HistoryList } from '../types';

import { actorLabel } from './actor-label';
import { cycleKindLabel, proposedMoveLabel } from './background-check-labels';
import { verificationTypeLabel } from './verification-labels';

const PAGE_SIZE = 25;

const DIMENSION_LOOK: Record<string, { label: string; icon: IconComponent }> = {
  journey: { label: 'Journey', icon: Icon.journey },
  qualification: { label: 'Qualification', icon: Icon.qualification },
  conversation: { label: 'Conversation', icon: Icon.conversation },
  background_check: { label: 'Background check', icon: Icon.backgroundCheck },
  deal: { label: 'Deal', icon: Icon.deal },
  marker: { label: 'Relationship', icon: Icon.marker },
  profile: { label: 'Profile', icon: Icon.profile },
  verification: { label: 'Verification', icon: Icon.backgroundCheck },
  screening: { label: 'Screening', icon: Icon.checklist },
  // The five F1 dimensions (`history-row.md` §2), added once for every lane.
  check_cycle: { label: 'Check cycle', icon: Icon.backgroundCheck },
  background_check_approval: { label: 'Approval', icon: Icon.shield },
  gst_registration: { label: 'GST registration', icon: Icon.branch },
  trade: { label: 'Trade', icon: Icon.trade },
  pipeline: { label: 'Pipeline', icon: Icon.explore },
};

const FALLBACK_LOOK = { label: 'Change', icon: Icon.history };

/** The filters offered, in the order a reader thinks about a company. */
/** Every lane, in the order the chips list them; only the ones seen are offered. */
const LANES: HistoryDimension[] = [
  'journey',
  'qualification',
  'conversation',
  'deal',
  'trade',
  'background_check',
  'background_check_approval',
  'check_cycle',
  'verification',
  'screening',
  'marker',
  'profile',
  'gst_registration',
  'pipeline',
];

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value)) return value.join(', ') || null;
  return String(value);
}

/** Labels for the keys a row's `details` name, from what the server serves. */
interface HistoryLabels {
  screeningItem: (key: string) => string;
  criterion: (key: string) => string;
}

const KEY_LABELS: HistoryLabels = { screeningItem: humanize, criterion: humanize };

const BUYER_FIELD_LABEL: Record<string, string> = {
  name: 'name',
  country: 'country',
  registration_number: 'registration number',
  tax_id: 'tax ID',
  contact_email: 'contact email',
  contact_phone: 'contact phone',
};

/** `from → to`, or just `to` for a value set at creation. */
function Move({ entry }: { entry: HistoryEntry }) {
  return (
    <>
      {entry.from_value ? (
        <span className="text-ink-2">{humanize(entry.from_value)} → </span>
      ) : null}
      <span className="font-medium">{humanize(entry.to_value)}</span>
    </>
  );
}

/** What a buyer change did: the deal's stage does not move, so `from → to` says nothing. */
function BuyerSummary({ entry }: { entry: HistoryEntry }) {
  const buyer = text(entry.details?.buyer_name);
  const changed = Array.isArray(entry.details?.changed) ? (entry.details.changed as string[]) : [];
  const fields = changed.map((field) => BUYER_FIELD_LABEL[field] ?? humanize(field).toLowerCase());
  if (entry.details?.created === true) {
    return (
      <p className="text-sm text-ink">
        <span className="font-medium">Buyer recorded</span>
        {buyer && <span className="text-ink-2">: {buyer}</span>}
      </p>
    );
  }
  return (
    <p className="text-sm text-ink">
      <span className="font-medium">Buyer updated</span>
      <span className="text-ink-2">
        {fields.length > 0 ? `: ${fields.join(', ')}` : ' — nothing changed'}
        {buyer && ` (${buyer})`}
      </span>
    </p>
  );
}

/**
 * Rows whose `from → to` says nothing on its own: a buyer or branch row carries the
 * deal's stage, an invoice row its currency, a branch row its state. Each line is
 * built from the details keys the server writes for that event, and a row that lacks
 * them falls back to the plain move.
 */
function eventLine(entry: HistoryEntry): { label: string; value?: string | null } | null {
  const details = entry.details ?? {};
  const state = text(details.state_name) ?? text(details.state_code);
  switch (entry.event_type) {
    case 'deal_buyer_company_set':
      return { label: 'Buyer company recorded', value: text(details.buyer_name) };
    case 'deal_invoicing_branch_set':
      return details.gst_registration_id
        ? { label: 'Invoicing branch recorded', value: state }
        : { label: 'Invoicing branch cleared' };
    case 'trade_invoice_recorded': {
      const number = text(details.invoice_number);
      const amount = text(details.amount);
      const currency = text(details.currency);
      return {
        label: number ? `Invoice ${number} recorded` : 'Invoice recorded',
        value: amount && currency ? `${amount} ${currency}` : null,
      };
    }
    case 'trade_outcome_recorded': {
      const proof = text(details.proof_status);
      const status = humanize(text(details.payment_status) ?? entry.to_value);
      return {
        label: entry.from_value ? 'Payment outcome corrected' : 'Payment outcome recorded',
        value: proof ? `${status} (${humanize(proof).toLowerCase()})` : status,
      };
    }
    case 'gst_registration_added':
      return { label: 'Branch added', value: state };
    case 'gst_registration_reactivated':
      return { label: 'Branch reactivated', value: state };
    case 'gst_registration_deactivated':
      return { label: 'Branch deactivated', value: state };
    case 'gst_registration_flagged':
      return { label: 'Branch flagged', value: state };
    case 'gst_registration_unflagged':
      return { label: 'Branch flag lifted', value: state };
    case 'pipeline_initial':
      return entry.to_value === 'NOT_IN_PIPELINE'
        ? { label: "Created as a deal's buyer", value: 'not in the pipeline' }
        : null;
    default:
      return null;
  }
}

/** The thing a row is about, when it is one of several: an item, a criterion, a check. */
function subjectOf(entry: HistoryEntry, labels: HistoryLabels): string | null {
  const details = entry.details ?? {};
  if (entry.dimension === 'screening' && typeof details.item_key === 'string') {
    return labels.screeningItem(details.item_key);
  }
  if (entry.event_type === 'qualification_result' && typeof details.criterion_key === 'string') {
    return labels.criterion(details.criterion_key);
  }
  if (entry.dimension === 'verification' && typeof details.verification_type === 'string') {
    const type = details.verification_type;
    const check = type === 'BUYER' ? 'Buyer check' : `${verificationTypeLabel(type)} check`;
    const onBuyer = details.entity_type === 'BUYER' && type !== 'BUYER';
    const subject = onBuyer ? `Buyer ${check.charAt(0).toLowerCase()}${check.slice(1)}` : check;
    return entry.event_type === 'verification_reviewed' ? `${subject} reviewed` : subject;
  }
  // Developer 1's dimensions: a proposal's status means nothing without the move it
  // proposes ("Clear proposal: Open → Approved"), and a cycle row names its kind.
  if (entry.dimension === 'background_check_approval' && typeof details.to_value === 'string') {
    return `${proposedMoveLabel(details.to_value)} proposal`;
  }
  if (entry.dimension === 'check_cycle' && typeof details.kind === 'string') {
    return `${cycleKindLabel(details.kind)} — check cycle`;
  }
  return null;
}

/** What changed, in one line. */
function Summary({ entry, labels }: { entry: HistoryEntry; labels: HistoryLabels }) {
  if (entry.event_type === 'deal_buyer_changed') return <BuyerSummary entry={entry} />;
  const line = eventLine(entry);
  if (line) {
    return (
      <p className="text-sm text-ink">
        <span className="font-medium">{line.label}</span>
        {line.value && <span className="text-ink-2">: {line.value}</span>}
      </p>
    );
  }
  if (entry.dimension === 'profile') {
    const field = text(entry.details?.field) ?? entry.to_value;
    const before = text(entry.details?.from);
    const after = text(entry.details?.to);
    return (
      <p className="text-sm text-ink">
        <span className="font-medium">{humanize(field)}</span>
        {' changed'}
        {before && <span className="text-ink-2"> from {before}</span>}
        {after ? <span className="text-ink-2"> to {after}</span> : <span className="text-ink-2"> (cleared)</span>}
      </p>
    );
  }
  const subject = subjectOf(entry, labels);
  // Screening items are questions: "Has the website been reviewed? Passed", not "?:".
  const separator = subject?.endsWith('?') ? ' ' : ': ';
  return (
    <p className="text-sm text-ink">
      {subject && `${subject}${separator}`}
      <Move entry={entry} />
    </p>
  );
}

/** One row of an event: lane, what changed, why, and who. */
function LedgerLine({ entry, labels }: { entry: HistoryEntry; labels: HistoryLabels }) {
  const look = DIMENSION_LOOK[entry.dimension] ?? FALLBACK_LOOK;
  const Glyph = look.icon;
  const checkBack = text(entry.details?.check_back_on);

  return (
    <li className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[11rem_1fr]" data-testid="history-row">
      <p className="flex items-center gap-2 text-secondary text-ink-3">
        <Glyph size={15} className="shrink-0" aria-hidden />
        {look.label}
      </p>
      <div className="min-w-0">
        <Summary entry={entry} labels={labels} />
        {checkBack && <p className="text-secondary text-attention">Check back {checkBack}</p>}
        {entry.reason && <p className="mt-0.5 text-secondary text-ink-2">“{entry.reason}”</p>}
        <p className="mt-0.5 text-caption text-ink-3">By {actorLabel(entry.actor_name, entry.actor_id)}</p>
      </div>
    </li>
  );
}

interface LedgerEvent {
  at: string;
  entries: HistoryEntry[];
}

interface LedgerDay {
  day: string;
  events: LedgerEvent[];
}

/** Server order kept; consecutive rows sharing `occurred_at` become one event. */
function toDays(entries: HistoryEntry[]): LedgerDay[] {
  const days: LedgerDay[] = [];
  for (const entry of entries) {
    const day = format(new Date(entry.occurred_at), 'd MMM yyyy');
    let current = days[days.length - 1];
    if (!current || current.day !== day) {
      current = { day, events: [] };
      days.push(current);
    }
    const last = current.events[current.events.length - 1];
    if (last && last.at === entry.occurred_at) last.entries.push(entry);
    else current.events.push({ at: entry.occurred_at, entries: [entry] });
  }
  return days;
}

function Ledger({ entries, labels }: { entries: HistoryEntry[]; labels: HistoryLabels }) {
  return (
    <div className="space-y-6">
      {toDays(entries).map(({ day, events }) => (
        <section key={day} aria-label={day}>
          <h3 className="flex items-center gap-3 text-caption font-medium text-ink-3">
            {day}
            <span aria-hidden className="h-px flex-1 bg-line" />
          </h3>
          <ol className="mt-3 space-y-4">
            {events.map((event) => (
              <li
                key={event.at + event.entries[0]!.id}
                className="grid gap-x-4 sm:grid-cols-[3.5rem_1fr]"
              >
                <time className="pt-px text-secondary tabular-nums text-ink-3" dateTime={event.at}>
                  {format(new Date(event.at), 'HH:mm')}
                </time>
                <div className="min-w-0">
                  {event.entries.length > 1 && (
                    <p className="mb-1 text-caption text-ink-3">
                      Same moment — {event.entries.length} changes recorded together
                    </p>
                  )}
                  <ol
                    className={cn(
                      'space-y-3',
                      event.entries.length > 1 && 'border-l border-line pl-3',
                    )}
                  >
                    {event.entries.map((entry) => (
                      <LedgerLine key={entry.id} entry={entry} labels={labels} />
                    ))}
                  </ol>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/**
 * The screening catalogue's and the criteria's labels, fetched only when the page
 * holds a row that needs them — and usually already cached by the tab that shows them.
 */
function useHistoryLabels(customerId: string, entries: HistoryEntry[]): HistoryLabels {
  const needsScreening = entries.some((entry) => entry.dimension === 'screening');
  const needsCriteria = entries.some((entry) => entry.event_type === 'qualification_result');
  const screening = useScreeningReview(needsScreening ? customerId : undefined);
  const qualification = useQualification(needsCriteria ? customerId : undefined);
  return useMemo(() => {
    const items = new Map((screening.data?.catalogue ?? []).map((item) => [item.key, item.label]));
    const criteria = new Map(
      (qualification.data?.standings ?? []).map(({ criterion }) => [criterion.key, criterion.label]),
    );
    return {
      screeningItem: (key) => items.get(key) ?? humanize(key),
      criterion: (key) => criteria.get(key) ?? humanize(key),
    };
  }, [screening.data, qualification.data]);
}

function HistoryBody({
  query,
  offset,
  onOffsetChange,
  emptyText,
  labels = KEY_LABELS,
}: {
  query: {
    data?: HistoryList;
    isLoading: boolean;
    isError: boolean;
    isFetching: boolean;
    refetch: () => unknown;
  };
  offset: number;
  onOffsetChange: (offset: number) => void;
  emptyText: string;
  labels?: HistoryLabels;
}) {
  if (query.isLoading) {
    return (
      <div className="space-y-4" aria-hidden>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="grid grid-cols-[3.5rem_11rem_1fr] gap-4">
            <Skeleton className="h-4" />
            <Skeleton className="h-4" />
            <Skeleton className="h-10" />
          </div>
        ))}
      </div>
    );
  }
  if (query.isError) {
    return <ErrorState title="Couldn't load the history." onRetry={() => void query.refetch()} />;
  }
  const entries = query.data?.entries ?? [];
  const total = query.data?.total ?? 0;
  if (entries.length === 0) return <EmptyLine>{emptyText}</EmptyLine>;

  return (
    <>
      <div className={cn(query.isFetching && 'opacity-60 transition-opacity duration-pop')}>
        <Ledger entries={entries} labels={labels} />
      </div>
      {total > PAGE_SIZE && (
        <div className="mt-6 flex items-center justify-between border-t border-line pt-3">
          <span className="text-secondary tabular-nums text-ink-3">
            {offset + 1}–{offset + entries.length} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={offset === 0}
              onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </Button>
            <Button
              size="sm"
              disabled={offset + entries.length >= total}
              onClick={() => onOffsetChange(offset + PAGE_SIZE)}
            >
              Older
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

/** Everything that happened to one company, filterable by dimension. */
export function CompanyHistory({ customerId }: { customerId: string }) {
  const [dimension, setDimension] = useState<HistoryDimension | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const query = useCompanyHistory(customerId, { dimension, limit: PAGE_SIZE, offset });
  const labels = useHistoryLabels(customerId, query.data?.entries ?? []);
  // The lanes this viewer has been sent rows for: a chip is never offered for a
  // dimension the server does not send this role.
  const [seen, setSeen] = useState<ReadonlySet<string>>(new Set());
  const pageDimensions = (query.data?.entries ?? []).map((entry) => entry.dimension).join(',');
  useEffect(() => {
    if (!pageDimensions) return;
    setSeen((previous) => {
      const next = new Set(previous);
      pageDimensions.split(',').forEach((value) => next.add(value));
      return next.size === previous.size ? previous : next;
    });
  }, [pageDimensions]);
  const lanes = LANES.filter((lane) => seen.has(lane) || lane === dimension);

  const choose = (next: HistoryDimension | undefined) => {
    setDimension(next);
    setOffset(0);
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-1.5" role="group" aria-label="Filter history">
        {[undefined, ...lanes].map((value) => {
          const active = value === dimension;
          return (
            <button
              key={value ?? 'all'}
              type="button"
              aria-pressed={active}
              onClick={() => choose(value)}
              className={cn(
                'rounded-md border px-2.5 py-1 text-secondary font-medium transition-colors duration-quick',
                active
                  ? 'border-ink bg-ink text-paper'
                  : 'border-line-strong text-ink-2 hover:border-ink-3 hover:text-ink',
              )}
            >
              {value ? (DIMENSION_LOOK[value]?.label ?? humanize(value)) : 'Everything'}
            </button>
          );
        })}
      </div>
      <HistoryBody
        query={query}
        offset={offset}
        onOffsetChange={setOffset}
        emptyText={dimension ? 'Nothing recorded for this yet.' : 'Nothing has been recorded for this company yet.'}
        labels={labels}
      />
    </div>
  );
}

/** One deal's own changes: its stages, its buyer and its handover. */
export function DealHistory({ dealId }: { dealId: string }) {
  const [offset, setOffset] = useState(0);
  const query = useDealHistory(dealId, { limit: PAGE_SIZE, offset });
  return (
    <HistoryBody
      query={query}
      offset={offset}
      onOffsetChange={setOffset}
      emptyText="Nothing has been recorded for this deal yet."
    />
  );
}
