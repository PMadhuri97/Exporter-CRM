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
import { Icon, type IconComponent } from '@/design/icons';
import { cn } from '@/lib/cn';
import { useCan } from '@/platform/access';

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

/** A quiet mark beside the stage name. Decorative: the name is right next to it. */
const COLUMN_DOT: Record<ExporterJourney, string> = {
  LEAD: 'bg-ink-4',
  PROSPECT: 'bg-accent',
  CUSTOMER: 'bg-positive',
};

interface NextStep {
  text: string;
  icon: IconComponent;
  /** Someone here has to act. Drawn in attention, and counted in the column header. */
  onUs: boolean;
}

/**
 * What this company is waiting for, worked out from the row the list already returns.
 *
 * Deliberately nothing that would need another request. A lead's criteria tally, a
 * prospect's screening items and a customer's open deals would each be a call per card,
 * which is what makes a board like this slow — so the line says which decision is
 * outstanding, and the record says how far along it is.
 *
 * `null` where the row implies no next step: a customer's is "trade", which the column
 * note already says once for all of them.
 */
function nextStep(profile: ExporterProfileListItem): NextStep | null {
  if (profile.marker === 'PAUSED') {
    return {
      text: profile.marker_reason ? `Paused — ${profile.marker_reason}` : 'Paused',
      icon: Icon.pause,
      onUs: false,
    };
  }
  if (profile.marker === 'ENDED') {
    return {
      text: profile.marker_reason ? `Ended — ${profile.marker_reason}` : 'Ended',
      icon: Icon.prohibited,
      onUs: false,
    };
  }

  switch (profile.journey) {
    case 'LEAD':
      // The one case where the board can say the work is ours: nobody has judged it.
      if (profile.qualification === 'NOT_YET_REVIEWED') {
        return { text: 'Waiting on a qualification decision', icon: Icon.warning, onUs: true };
      }
      // NOT_QUALIFIED and still a lead: decided, and it stays here. Not our move.
      return { text: 'Not qualified — stays a lead', icon: Icon.info, onUs: false };
    case 'PROSPECT':
      return { text: 'Waiting on the background check', icon: Icon.backgroundCheck, onUs: false };
    default:
      return null;
  }
}

/** The muted second line: what the company does, where it is, and who holds it. */
function factsLine(profile: ExporterProfileListItem): string | null {
  const parts = [
    profile.industry,
    profile.country,
    profile.relationship_manager ? `RM ${profile.relationship_manager}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function PipelineCard({
  profile,
  onIntent,
}: {
  profile: ExporterProfileListItem;
  onIntent: (id: string) => void;
}) {
  const step = nextStep(profile);
  const facts = factsLine(profile);
  return (
    <Link
      to={paths.company(profile.customer_id)}
      data-testid="pipeline-card"
      onMouseEnter={() => onIntent(profile.customer_id)}
      onFocus={() => onIntent(profile.customer_id)}
      className="block rounded border border-line bg-surface p-3 transition-colors duration-quick hover:border-line-strong hover:bg-sunken"
    >
      <span className="block text-body font-semibold leading-snug text-accent">
        {profile.name ?? <span className="italic text-ink-3">Unnamed lead</span>}
      </span>

      {/* Country reads here rather than floating in the corner, where a bare "IN" had
          nothing to say what it was. */}
      {facts && <p className="mt-1 text-caption text-ink-3">{facts}</p>}

      <div className="mt-2">
        <CompanyBadges size="inline" qualification={profile.qualification} marker={profile.marker} />
      </div>

      {/* The line the board is worth opening for. Attention only when someone here has
          to act, so a column of amber means a column of work. */}
      {step && (
        <div className="mt-2.5 flex items-center gap-1.5 border-t border-line pt-2">
          <step.icon
            size={13}
            className={cn('shrink-0', step.onUs ? 'text-attention' : 'text-ink-3')}
            aria-hidden
          />
          <span className={cn('text-caption', step.onUs ? 'font-medium text-attention' : 'text-ink-3')}>
            {step.text}
          </span>
        </div>
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
  // Counted from the page already in hand, not asked for: it is how many of these cards
  // say someone has to act. A column past `COLUMN_LIMIT` undercounts, which is why the
  // count beside the name carries the "+".
  //
  // Shown to the relationship managers only. Qualification is their work; COMPLIANCE and
  // ADMIN may record a decision too (all three hold `crm.write`), but it is not their
  // queue, and a tally of other people's work reads as a demand on whoever is looking.
  // `queue.qualification` says whose queue it is, which `crm.write` cannot.
  const ownsTheQueue = useCan('queue.qualification');
  const waiting = ownsTheQueue ? profiles.filter((profile) => nextStep(profile)?.onUs).length : 0;

  return (
    <section
      aria-label={JOURNEY_LABEL[journey]}
      // `rounded-xl` is 8px — the top of the scale (§5.5), which the side panel and
      // dialogs use. A column is a surface holding cards, so it reads softer than the
      // 4px cards inside it; the same radius on both made the nesting hard to see.
      className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface"
    >
      <header className="border-b border-line px-3.5 py-3">
        <div className="flex items-center gap-2">
          <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', COLUMN_DOT[journey])} aria-hidden />
          <h2 className="text-heading font-semibold text-ink">{JOURNEY_LABEL[journey]}</h2>
          {!isLoading && !isError && (
            <span className="tabular-nums text-secondary text-ink-3">
              {profiles.length}
              {profiles.length === COLUMN_LIMIT ? '+' : ''}
            </span>
          )}
          {waiting > 0 && (
            <span className="ml-auto shrink-0 rounded-full bg-attention-tint px-2 py-0.5 text-caption font-medium text-attention">
              {waiting} waiting on you
            </span>
          )}
        </div>
        <p className="mt-1.5 text-caption text-ink-3">{COLUMN_NOTE[journey]}</p>
      </header>

      {/* Capped and scrolled: one long stage used to run the page down past the other
          two, leaving the short columns stranded at the top. */}
      <div className="flex max-h-[34rem] flex-col gap-2 overflow-y-auto p-2.5">
        {isLoading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
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
        // description="The same companies as three journey columns. Nothing here moves a company: the journey moves on its own, when the decisions behind it are made."
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
