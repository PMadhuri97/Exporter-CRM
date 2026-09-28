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
 */

import {
  BadgeCheck,
  Briefcase,
  Flag,
  History as HistoryIcon,
  MessageSquare,
  PencilLine,
  Route,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';

import { Button, EmptySection, ErrorState, Skeleton } from '@/components';
import { cn } from '@/lib/cn';
import { formatDateTime, humanize } from '@/lib/format';

import { useCompanyHistory, useDealHistory } from '../hooks';
import type { HistoryDimension, HistoryEntry, HistoryList } from '../types';

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

/** What changed, in one line. */
function Summary({ entry }: { entry: HistoryEntry }) {
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
  return (
    <p className="text-sm text-ink">
      {entry.from_value ? (
        <span className="text-ink-muted">{humanize(entry.from_value)} → </span>
      ) : null}
      <span className="font-medium">{humanize(entry.to_value)}</span>
    </p>
  );
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
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
        <Summary entry={entry} />
        {checkBack && <p className="text-xs text-status-review">Check back {checkBack}</p>}
        {entry.reason && <p className="mt-1 text-sm text-ink-muted">“{entry.reason}”</p>}
        <p className="mt-1 text-xs text-ink-faint">
          {entry.actor_id ? `By ${entry.actor_id}` : 'By the platform'}
        </p>
      </div>
    </li>
  );
}

function HistoryBody({
  query,
  offset,
  onOffsetChange,
  emptyText,
}: {
  query: { data?: HistoryList; isLoading: boolean; isError: boolean; isFetching: boolean; refetch: () => unknown };
  offset: number;
  onOffsetChange: (offset: number) => void;
  emptyText: string;
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
          <HistoryRow key={entry.id} entry={entry} />
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
