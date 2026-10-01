/**
 * The company's story, from the shared history log (architecture §3.1, L1-11).
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

import {
  BadgeCheck,
  Briefcase,
  Compass,
  Flag,
  Handshake,
  History as HistoryIcon,
  Landmark,
  ListChecks,
  MessageSquare,
  PencilLine,
  Route,
  Shield,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button, EmptySection, ErrorState, Skeleton } from '@/components';
import { cn } from '@/lib/cn';
import { formatDateTime, humanize } from '@/lib/format';

import { useCompanyHistory, useDealHistory, useQualification, useScreeningReview } from '../hooks';
import type { HistoryDimension, HistoryEntry, HistoryList } from '../types';

import { actorLabel } from './actor-label';
import { verificationTypeLabel } from './verification-labels';

const PAGE_SIZE = 25;

const DIMENSION_LOOK: Record<string, { label: string; icon: LucideIcon; tone: string }> = {
  journey: { label: 'Journey', icon: Route, tone: 'text-journey-prospect bg-journey-prospect/10' },
  qualification: { label: 'Qualification', icon: BadgeCheck, tone: 'text-status-passed bg-status-passed/10' },
  conversation: { label: 'Conversation', icon: MessageSquare, tone: 'text-status-info bg-status-info/10' },
  background_check: { label: 'Background check', icon: ShieldCheck, tone: 'text-status-review bg-status-review/10' },
  deal: { label: 'Deal', icon: Briefcase, tone: 'text-brand-600 bg-brand-50' },
  marker: { label: 'Relationship', icon: Flag, tone: 'text-marker-paused bg-marker-paused/10' },
  profile: { label: 'Profile', icon: PencilLine, tone: 'text-ink-muted bg-surface-sunken' },
  verification: { label: 'Verification', icon: ShieldCheck, tone: 'text-ink-muted bg-surface-sunken' },
  screening: { label: 'Screening', icon: ListChecks, tone: 'text-ink-muted bg-surface-sunken' },
  // The five F1 dimensions (`history-row.md` §2), added once for every lane.
  check_cycle: { label: 'Check cycle', icon: ShieldCheck, tone: 'text-status-review bg-status-review/10' },
  background_check_approval: { label: 'Approval', icon: Shield, tone: 'text-status-review bg-status-review/10' },
  gst_registration: { label: 'GST registration', icon: Landmark, tone: 'text-ink-muted bg-surface-sunken' },
  trade: { label: 'Trade', icon: Handshake, tone: 'text-brand-600 bg-brand-50' },
  pipeline: { label: 'Pipeline', icon: Compass, tone: 'text-ink-muted bg-surface-sunken' },
};

const FALLBACK_LOOK = { label: 'Change', icon: HistoryIcon, tone: 'text-ink-muted bg-surface-sunken' };

/** The filters offered, in the order a reader thinks about a company. */
const FILTERS: HistoryDimension[] = [
  'journey',
  'qualification',
  'conversation',
  'deal',
  'marker',
  'profile',
  'verification',
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
        <span className="text-ink-muted">{humanize(entry.from_value)} → </span>
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
        {buyer && <span className="text-ink-muted">: {buyer}</span>}
      </p>
    );
  }
  return (
    <p className="text-sm text-ink">
      <span className="font-medium">Buyer updated</span>
      <span className="text-ink-muted">
        {fields.length > 0 ? `: ${fields.join(', ')}` : ' — nothing changed'}
        {buyer && ` (${buyer})`}
      </span>
    </p>
  );
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
  return null;
}

/** What changed, in one line. */
function Summary({ entry, labels }: { entry: HistoryEntry; labels: HistoryLabels }) {
  if (entry.event_type === 'deal_buyer_changed') return <BuyerSummary entry={entry} />;
  if (entry.dimension === 'profile') {
    const field = text(entry.details?.field) ?? entry.to_value;
    const before = text(entry.details?.from);
    const after = text(entry.details?.to);
    return (
      <p className="text-sm text-ink">
        <span className="font-medium">{humanize(field)}</span>
        {' changed'}
        {before && <span className="text-ink-muted"> from {before}</span>}
        {after ? <span className="text-ink-muted"> to {after}</span> : <span className="text-ink-muted"> (cleared)</span>}
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

function HistoryRow({ entry, labels }: { entry: HistoryEntry; labels: HistoryLabels }) {
  const look = DIMENSION_LOOK[entry.dimension] ?? FALLBACK_LOOK;
  const Icon = look.icon;
  const checkBack = text(entry.details?.check_back_on);

  return (
    <li className="group relative flex gap-3 pb-5 last:pb-0" data-testid="history-row">
      <span
        aria-hidden
        className="absolute left-[0.9375rem] top-8 h-[calc(100%-2rem)] w-px bg-border group-last:hidden"
      />
      <span
        className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full', look.tone)}
      >
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{look.label}</p>
          <time className="text-xs tabular-nums text-ink-faint" dateTime={entry.occurred_at}>
            {formatDateTime(entry.occurred_at)}
          </time>
        </div>
        <Summary entry={entry} labels={labels} />
        {checkBack && <p className="text-xs text-status-review">Check back {checkBack}</p>}
        {entry.reason && <p className="mt-1 text-sm text-ink-muted">“{entry.reason}”</p>}
        <p className="mt-1 text-xs text-ink-faint">By {actorLabel(entry.actor_name, entry.actor_id)}</p>
      </div>
    </li>
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
  query: { data?: HistoryList; isLoading: boolean; isError: boolean; isFetching: boolean; refetch: () => unknown };
  offset: number;
  onOffsetChange: (offset: number) => void;
  emptyText: string;
  labels?: HistoryLabels;
}) {
  if (query.isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="h-8 w-8 rounded-full" />
            <Skeleton className="h-12 flex-1" />
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
  if (entries.length === 0) return <EmptySection>{emptyText}</EmptySection>;

  return (
    <>
      <ol className={cn(query.isFetching && 'opacity-60 transition-opacity')}>
        {entries.map((entry) => (
          <HistoryRow key={entry.id} entry={entry} labels={labels} />
        ))}
      </ol>
      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
          <span className="text-sm tabular-nums text-ink-muted">
            {offset + 1}–{offset + entries.length} of {total}
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={offset === 0} onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}>
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

  const choose = (next: HistoryDimension | undefined) => {
    setDimension(next);
    setOffset(0);
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-1.5" role="group" aria-label="Filter history">
        {[undefined, ...FILTERS].map((value) => {
          const active = value === dimension;
          return (
            <button
              key={value ?? 'all'}
              type="button"
              aria-pressed={active}
              onClick={() => choose(value)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                active
                  ? 'border-ink bg-ink text-surface'
                  : 'border-border text-ink-muted hover:border-border-strong hover:text-ink',
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
