/**
 * The journey pipeline — **owner: Developer 2** (L2-14).
 *
 * Three columns, one per journey stage, each filled by its own server query
 * (`journey=`). There is no drag and no "move to" here on purpose: the
 * journey is never moved by hand. A QUALIFIED outcome moves a lead to
 * prospect, and the move to customer follows the background check (L2-11).
 * PAUSED companies stay in their column with a badge; ENDED companies are
 * left out by the server, as in the list.
 */

import { Search } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Input, PageHeader, Skeleton } from '@/components';
import { cn } from '@/lib/cn';

import { JourneyChip, MarkerBadge, QualificationChip } from '../components';
import { JOURNEY_LABEL, JOURNEY_STAGES } from '../constants';
import { useExporterProfiles } from '../hooks';
import { paths } from '../paths';
import type { ExporterJourney, ExporterProfileListItem } from '../types';

const COLUMN_LIMIT = 100;

/** The column's top rule, in the stage's colour. */
const COLUMN_ACCENT: Record<ExporterJourney, string> = {
  LEAD: 'border-t-journey-lead',
  PROSPECT: 'border-t-journey-prospect',
  CUSTOMER: 'border-t-journey-customer',
};

function PipelineCard({ profile }: { profile: ExporterProfileListItem }) {
  return (
    <Link
      to={paths.company(profile.customer_id)}
      data-testid="pipeline-card"
      className="block rounded-lg border border-border bg-surface p-3 shadow-card transition-colors hover:border-brand-500"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-ink">
          {profile.name ?? <span className="italic text-ink-faint">Unnamed lead</span>}
        </span>
        {profile.country && <span className="shrink-0 text-xs text-ink-faint">{profile.country}</span>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <QualificationChip state={profile.qualification} />
        <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
      </div>
      {profile.relationship_manager && (
        <div className="mt-2 text-xs text-ink-muted">{profile.relationship_manager}</div>
      )}
    </Link>
  );
}

function PipelineColumn({ journey, name }: { journey: ExporterJourney; name: string }) {
  const { data, isLoading, isError } = useExporterProfiles({
    journey,
    name: name || undefined,
    limit: COLUMN_LIMIT,
  });
  const profiles = data?.profiles ?? [];

  return (
    <section
      aria-label={JOURNEY_LABEL[journey]}
      className={cn(
        'flex min-w-0 flex-col rounded-lg border border-t-2 border-border bg-surface-sunken/60',
        COLUMN_ACCENT[journey],
      )}
    >
      <header className="flex items-center justify-between px-3 py-2.5">
        <JourneyChip journey={journey} />
        {!isLoading && !isError && (
          <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-medium tabular-nums text-ink-muted">
            {profiles.length}
            {profiles.length === COLUMN_LIMIT ? '+' : ''}
          </span>
        )}
      </header>
      <div className="flex flex-col gap-2 px-3 pb-3">
        {isLoading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
        {isError && (
          <div className="px-3 py-8 text-center text-xs text-status-failed">Couldn't load this stage.</div>
        )}
        {!isLoading &&
          !isError &&
          profiles.map((profile) => <PipelineCard key={profile.customer_id} profile={profile} />)}
        {!isLoading && !isError && profiles.length === 0 && (
          <div className="rounded-lg border border-dashed border-border-strong px-3 py-8 text-center text-xs text-ink-faint">
            No companies in this stage
          </div>
        )}
      </div>
    </section>
  );
}

export function PipelinePage() {
  const [searchInput, setSearchInput] = useState('');
  const [nameFilter, setNameFilter] = useState('');

  return (
    <div>
      <PageHeader
        title="Pipeline"
        description="Companies by journey stage. Stages move on their own — a qualification decision moves a lead to prospect."
        actions={
          <form
            role="search"
            className="relative"
            onSubmit={(e) => {
              e.preventDefault();
              setNameFilter(searchInput.trim());
            }}
          >
            <Search
              size={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint"
            />
            <Input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by company name…"
              aria-label="Search by company name"
              className="pl-9 sm:w-72"
            />
          </form>
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {JOURNEY_STAGES.map((journey) => (
          <PipelineColumn key={journey} journey={journey} name={nameFilter} />
        ))}
      </div>
    </div>
  );
}
