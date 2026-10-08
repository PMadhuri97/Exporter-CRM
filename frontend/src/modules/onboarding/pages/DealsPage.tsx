/**
 * Every deal, across companies: record list items, not a table (frontend-plan §6.7).
 * Each deal is its reference as a link, the seller and the buyer with the date it
 * was opened, and on the right its corridor and its stage.
 *
 * **The corridor is worked out by the server** — the seller's country, then the
 * buyer's — and never stored, so it cannot disagree with the parties. A deal with no
 * buyer yet has no corridor; it is still listed, and *Corridor not known* finds it.
 *
 * Every filter runs on the server and lives in the URL (`?corridor=IN-NL&stage=OPEN
 * &q=&seller=&buyer=&from=&to=`), so a filtered list can be shared. Dates are the
 * viewer's own days: *to* includes the whole of its day.
 *
 * **The parties are two filters, not one.** `seller=` and `buyer=` narrow each side,
 * and together they are the deals between that pair. The route still accepts
 * `company_id` for a company on *either* side, but no screen asks for it: one box that
 * matched either side could not express a pair, and keeping both was three company
 * pickers on one bar.
 *
 * *New deal* opens over the list, and `?new=1` opens it from a link — the header's
 * *+ New* menu uses that.
 */

import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  Button,
  EmptyLine,
  ErrorState,
  Input,
  PageHeader,
  RecordListItem,
  Segmented,
  Select,
  Skeleton,
  Tag,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';
import { useCan } from '@/platform/access';

import { CompanySearchSelect, DealStageChip, NewDealPanel } from '../components';
import {
  corridorDescription,
  corridorLabel,
  DEAL_STAGE_LABEL,
  DEAL_STAGES,
  UNKNOWN_CORRIDOR,
} from '../constants';
import { useAllDeals } from '../hooks';
import { paths } from '../paths';
import type { AllDealsParams, DealStage, DealSummary } from '../types';

const PAGE_SIZE = 50;
const CORRIDOR = /^([A-Z]{2}-[A-Z]{2}|UNKNOWN)$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

type StageLens = 'ALL' | DealStage;

/** The start of a `YYYY-MM-DD` day in the viewer's zone, as an ISO timestamp. */
function startOfDay(day: string, plusDays = 0): string {
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number);
  return new Date(year, month - 1, date + plusDays).toISOString();
}

/** The filter parameters, read from the URL and written back to it. */
function useDealFilters() {
  const [params, setParams] = useSearchParams();
  const read = (name: string, valid: RegExp | null = null) => {
    const value = params.get(name);
    return value && (!valid || valid.test(value)) ? value : null;
  };
  const stage = read('stage');
  const filters = {
    corridor: read('corridor', CORRIDOR),
    stage: stage && (DEAL_STAGES as readonly string[]).includes(stage) ? (stage as DealStage) : null,
    q: read('q'),
    seller: read('seller'),
    buyer: read('buyer'),
    from: read('from', DAY),
    to: read('to', DAY),
  };
  /** Set some filters; `null` removes one. Replaces the history entry, like a tab. */
  const update = (changes: Partial<Record<keyof typeof filters | 'new', string | null>>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [name, value] of Object.entries(changes)) {
          if (value) next.set(name, value);
          else next.delete(name);
        }
        return next;
      },
      { replace: true },
    );
  return { filters, update, creating: params.get('new') === '1' };
}

function Corridor({ deal }: { deal: DealSummary }) {
  if (deal.corridor) {
    return (
      <Tag tone="neutral" icon={<Icon.country size={12} aria-hidden />} title={corridorDescription(deal.corridor)}>
        <span className="sr-only">{corridorDescription(deal.corridor)}</span>
        <span aria-hidden>{corridorLabel(deal.corridor)}</span>
      </Tag>
    );
  }
  return (
    <Tag tone="idle" className="text-ink-3">
      {deal.buyer_name ? 'Country missing' : 'No buyer yet'}
    </Tag>
  );
}

function Row({ deal }: { deal: DealSummary }) {
  return (
    <RecordListItem
      to={paths.deal(deal.id)}
      title={deal.reference}
      muted={deal.stage === 'WITHDRAWN'}
      data-testid="deal-row"
      facts={
        <>
          {deal.seller_name ?? 'Unnamed company'}
          {' → '}
          {deal.buyer_name ?? <span className="text-ink-3">no buyer yet</span>}
          {` · opened ${formatDate(deal.created_at)}`}
        </>
      }
      badges={
        <>
          <Corridor deal={deal} />
          <DealStageChip stage={deal.stage} />
        </>
      }
    />
  );
}

export function DealsPage() {
  const canOpen = useCan('crm.write');
  const { filters, update, creating } = useDealFilters();
  const [page, setPage] = useState(0);
  const [searchInput, setSearchInput] = useState(filters.q ?? '');

  const params: AllDealsParams = {
    corridors: filters.corridor ? [filters.corridor] : undefined,
    stages: filters.stage ? [filters.stage] : undefined,
    q: filters.q ?? undefined,
    sellerCompanyId: filters.seller ?? undefined,
    buyerCompanyId: filters.buyer ?? undefined,
    openedFrom: filters.from ? startOfDay(filters.from) : undefined,
    openedBefore: filters.to ? startOfDay(filters.to, 1) : undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
  const { data, isLoading, isError, isFetching, refetch } = useAllDeals(params);
  const deals = data?.deals ?? [];
  const total = data?.total ?? 0;
  const filtering = Object.values(filters).some(Boolean);

  /** Change filters and go back to the first page. */
  function filter(changes: Parameters<typeof update>[0]) {
    setPage(0);
    update(changes);
  }

  // A corridor in the URL that no deal is on is still offered, so the select can show it.
  const corridors = data?.corridors ?? [];
  const corridorChoices = corridors.filter((choice) => choice.corridor !== null);
  const unknownCount = corridors.find((choice) => choice.corridor === null)?.deals;
  const stray =
    filters.corridor &&
    filters.corridor !== UNKNOWN_CORRIDOR &&
    !corridorChoices.some((choice) => choice.corridor === filters.corridor);

  const first = page * PAGE_SIZE + 1;
  const last = page * PAGE_SIZE + deals.length;

  return (
    <div>
      <PageHeader
        title="Deals"
        actions={
          canOpen && (
            <Button variant="primary" onClick={() => update({ new: '1' })}>
              <Icon.add size={16} aria-hidden />
              New deal
            </Button>
          )
        }
      />

      <section aria-label="Deal list" className="rounded border border-line bg-surface">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3">
          {/* The stage lens and the search share a line: the search is how most visits
              start, and it reads as the counterpart to the tabs rather than the first of
              six filters below. They stack when there is no room for both. */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented<StageLens>
              label="Stage"
              value={filters.stage ?? 'ALL'}
              onValueChange={(value) => filter({ stage: value === 'ALL' ? null : value })}
              options={[
                { value: 'ALL', label: 'All' },
                ...DEAL_STAGES.map((stage) => ({ value: stage, label: DEAL_STAGE_LABEL[stage] })),
              ]}
            />
            <form
              role="search"
              className="relative w-full sm:w-72"
              onSubmit={(event) => {
                event.preventDefault();
                filter({ q: searchInput.trim() || null });
              }}
            >
              <Icon.search
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3"
                aria-hidden
              />
              <Input
                type="search"
                data-page-search
                value={searchInput}
                onChange={(event) => {
                  setSearchInput(event.target.value);
                  // Clearing the field clears the search, without a second Enter.
                  if (event.target.value === '' && filters.q) filter({ q: null });
                }}
                placeholder="Search reference, seller, buyer"
                aria-label="Search deals by reference, seller or buyer"
                className="w-full pl-9"
              />
            </form>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:flex xl:flex-wrap xl:items-end">
            <Select
              aria-label="Corridor"
              className="xl:w-auto"
              value={filters.corridor ?? ''}
              onChange={(event) => filter({ corridor: event.target.value || null })}
            >
              <option value="">All corridors</option>
              {corridorChoices.map((choice) => (
                <option key={choice.corridor} value={choice.corridor!}>
                  {`${corridorLabel(choice.corridor!)} · ${corridorDescription(choice.corridor!)} (${choice.deals})`}
                </option>
              ))}
              {stray && <option value={filters.corridor!}>{corridorLabel(filters.corridor!)}</option>}
              <option value={UNKNOWN_CORRIDOR}>
                {`Corridor not known yet${unknownCount ? ` (${unknownCount})` : ''}`}
              </option>
            </Select>
            {/* Two sides, not one "either side" box. Each narrows on its own — every
                deal this company sold, or bought — and together they are the deals
                between those two. The server still accepts `company_id` for an
                either-side match; no screen asks for it. */}
            <CompanySearchSelect
              label="Seller"
              hideLabel
              placeholder="Seller company"
              value={filters.seller}
              onChange={(id) => filter({ seller: id })}
              className="xl:w-56"
            />
            <CompanySearchSelect
              label="Buyer"
              hideLabel
              placeholder="Buyer company"
              value={filters.buyer}
              onChange={(id) => filter({ buyer: id })}
              className="xl:w-56"
            />
            <div className="flex items-center gap-2">
              <Input
                type="date"
                aria-label="Opened from"
                title="Opened from"
                value={filters.from ?? ''}
                max={filters.to ?? undefined}
                onChange={(event) => filter({ from: event.target.value || null })}
                className="min-w-0 flex-1 xl:w-40 xl:flex-none"
              />
              <span className="text-secondary text-ink-3" aria-hidden>
                to
              </span>
              <Input
                type="date"
                aria-label="Opened to"
                title="Opened to"
                value={filters.to ?? ''}
                min={filters.from ?? undefined}
                onChange={(event) => filter({ to: event.target.value || null })}
                className="min-w-0 flex-1 xl:w-40 xl:flex-none"
              />
            </div>
            {filtering && (
              <Button
                variant="subtle"
                onClick={() => {
                  setSearchInput('');
                  filter({
                    corridor: null,
                    stage: null,
                    q: null,
                    seller: null,
                    buyer: null,
                    from: null,
                    to: null,
                  });
                }}
              >
                Clear filters
              </Button>
            )}
          </div>
        </div>

        {isError ? (
          <ErrorState title="Couldn't load deals." className="m-4" onRetry={() => void refetch()}>
            Check your connection and try again.
          </ErrorState>
        ) : isLoading ? (
          <div className="divide-y divide-line" aria-hidden>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="space-y-2 px-4 py-3">
                <Skeleton className="h-6 w-64" />
                <Skeleton className="h-4 w-96 max-w-full" />
              </div>
            ))}
          </div>
        ) : deals.length === 0 ? (
          <EmptyLine
            className="px-4 py-8"
            action={
              !filtering &&
              canOpen && (
                <button
                  type="button"
                  onClick={() => update({ new: '1' })}
                  className="font-semibold text-accent underline-offset-2 hover:underline"
                >
                  Open the first one
                </button>
              )
            }
          >
            {filtering ? 'No deals match these filters.' : 'No deals yet.'}
          </EmptyLine>
        ) : (
          <>
            <ol aria-label="Deals" className="divide-y divide-line">
              {deals.map((deal) => (
                <Row key={deal.id} deal={deal} />
              ))}
            </ol>
            <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-secondary text-ink-3">
              <span className="tabular-nums">
                {total > deals.length ? `${first}–${last} of ${total}` : `${total} ${total === 1 ? 'deal' : 'deals'}`}
                {isFetching ? ' · updating…' : ''}
              </span>
              {total > PAGE_SIZE && (
                <span className="flex gap-2">
                  <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                    Previous
                  </Button>
                  <Button size="sm" disabled={last >= total} onClick={() => setPage((p) => p + 1)}>
                    Next
                  </Button>
                </span>
              )}
            </div>
          </>
        )}
      </section>

      {canOpen && <NewDealPanel open={creating} onOpenChange={(open) => update({ new: open ? '1' : null })} />}
    </div>
  );
}
