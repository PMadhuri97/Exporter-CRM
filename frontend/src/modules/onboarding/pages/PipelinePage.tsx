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

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { JourneyChip, MarkerBadge, QualificationChip } from '../components';
import { JOURNEY_LABEL, JOURNEY_STAGES } from '../constants';
import { useExporterProfiles } from '../hooks';
import type { ExporterJourney, ExporterProfileListItem } from '../types';

const COLUMN_LIMIT = 100;

function PipelineCard({ profile }: { profile: ExporterProfileListItem }) {
  return (
    <Link
      to={`/exporters/${profile.customer_id}`}
      data-testid="pipeline-card"
      className="block rounded-lg border border-border bg-surface p-3 shadow-card transition-colors hover:border-brand-500"
    >
      <div className="text-sm font-medium text-ink">
        {profile.name ?? <span className="italic text-ink-faint">Unnamed lead</span>}
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
      className="flex min-w-0 flex-col rounded-lg border border-border bg-surface-subtle"
    >
      <header className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <JourneyChip journey={journey} />
        {!isLoading && !isError && (
          <span className="text-xs text-ink-muted">
            {profiles.length}
            {profiles.length === COLUMN_LIMIT ? '+' : ''}
          </span>
        )}
      </header>
      <div className="flex flex-col gap-2 p-3">
        {isLoading &&
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-surface-sunken" />
          ))}
        {isError && (
          <div className="px-3 py-8 text-center text-xs text-status-failed">
            Couldn't load this stage.
          </div>
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
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Pipeline</h1>
          <p className="text-sm text-ink-muted">
            Companies by journey stage. Stages move on their own — a qualification
            decision moves a lead to prospect.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setNameFilter(searchInput.trim());
          }}
        >
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by company name…"
            aria-label="Search by company name"
            className="w-72 rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </form>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {JOURNEY_STAGES.map((journey) => (
          <PipelineColumn key={journey} journey={journey} name={nameFilter} />
        ))}
      </div>
    </div>
  );
}
