/**
 * The journey pipeline.
 *
 * Three columns, one per journey stage, each filled by its own server query
 * (`journey=`). There is no drag and no "move to" here on purpose: the
 * journey is never moved by hand. A QUALIFIED outcome moves a lead to
 * prospect, and the move to customer follows the background check.
 * PAUSED companies stay in their column with a badge; ENDED companies are
 * left out by the server, as in the list.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { EmptyLine, Input, PageHeader, Skeleton } from '@/components';
import { Icon } from '@/design/icons';

import { CompaniesViewSwitch, CompanyBadges } from '../components';
import { JOURNEY_LABEL, JOURNEY_STAGES } from '../constants';
import { useExporterProfiles, usePrefetchCompany } from '../hooks';
import { preloadExporterDetailPage } from '../lazyPages';
import { paths } from '../paths';
import type { ExporterJourney, ExporterProfileListItem } from '../types';

const COLUMN_LIMIT = 100;

/**
 * What moves a company out of each column — said, because nothing on the board can
 * move one (the journey is never moved by hand, architecture §4).
 */
const COLUMN_NOTE: Record<ExporterJourney, string> = {
  LEAD: 'A qualification decision moves a lead to prospect.',
  PROSPECT: 'A Clear background check makes a prospect a customer.',
  CUSTOMER: 'Customers can open deals and hand them over.',
};

function PipelineCard({
  profile,
  onIntent,
}: {
  profile: ExporterProfileListItem;
  onIntent: (id: string) => void;
}) {
  return (
    <Link
      to={paths.company(profile.customer_id)}
      data-testid="pipeline-card"
      onMouseEnter={() => onIntent(profile.customer_id)}
      onFocus={() => onIntent(profile.customer_id)}
      className="block rounded border border-line bg-surface p-3 transition-colors duration-quick hover:border-line-strong hover:bg-sunken"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-body font-semibold leading-snug text-accent">
          {profile.name ?? <span className="italic text-ink-3">Unnamed lead</span>}
        </span>
        {profile.country && <span className="shrink-0 text-caption text-ink-3">{profile.country}</span>}
      </div>
      <div className="mt-2">
        <CompanyBadges size="inline" qualification={profile.qualification} marker={profile.marker} />
      </div>
      {profile.relationship_manager && (
        <div className="mt-2 text-caption text-ink-3">RM {profile.relationship_manager}</div>
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
  const prefetch = usePrefetchCompany();
  // Ahead of the click: the company record's code and the company's data.
  const prepare = (customerId: string) => {
    void preloadExporterDetailPage();
    void prefetch(customerId);
  };
  const profiles = data?.profiles ?? [];

  return (
    <section aria-label={JOURNEY_LABEL[journey]} className="flex min-w-0 flex-col">
      <header className="rounded border border-line bg-surface px-3 py-2.5">
        <h2 className="text-heading font-semibold text-ink">
          {JOURNEY_LABEL[journey]}
          {!isLoading && !isError && (
            <span className="ml-1.5 font-normal tabular-nums text-ink-3">
              ({profiles.length}
              {profiles.length === COLUMN_LIMIT ? '+' : ''})
            </span>
          )}
        </h2>
        <p className="mt-0.5 text-caption text-ink-3">{COLUMN_NOTE[journey]}</p>
      </header>
      <div className="flex flex-col gap-2 pt-2">
        {isLoading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20" />)}
        {isError && <p className="py-6 text-secondary text-negative">Couldn't load this stage.</p>}
        {!isLoading &&
          !isError &&
          profiles.map((profile) => (
            <PipelineCard key={profile.customer_id} profile={profile} onIntent={prepare} />
          ))}
        {!isLoading && !isError && profiles.length === 0 && (
          <EmptyLine>No companies in this stage</EmptyLine>
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
        title="Companies"
        meta={<CompaniesViewSwitch view="board" />}
        description="The same companies as three journey columns. Nothing here moves a company: the journey moves on its own, when the decisions behind it are made."
        actions={
          <form
            role="search"
            className="relative"
            onSubmit={(e) => {
              e.preventDefault();
              setNameFilter(searchInput.trim());
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
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by name"
              aria-label="Search by company name"
              className="pl-9 sm:w-72"
            />
          </form>
        }
      />

      <div className="grid grid-cols-1 gap-8 md:grid-cols-3 md:gap-6">
        {JOURNEY_STAGES.map((journey) => (
          <PipelineColumn key={journey} journey={journey} name={nameFilter} />
        ))}
      </div>
    </div>
  );
}
