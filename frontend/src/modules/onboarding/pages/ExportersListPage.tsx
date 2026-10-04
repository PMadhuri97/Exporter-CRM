/**
 * The register — **owner: Developer 2** (L2-14), drawn as frontend-plan §8.3: rows,
 * not a table. Each company is its serif name, its Standing, one muted line of
 * identity, its primary identifier and, on the right, its country and RM.
 *
 * Every filter runs on the server: the journey lens, qualification, relationship
 * and the name search — including the rule that ENDED companies leave the default
 * list and come back for a search or the "Ended" filter; this page does not
 * re-implement it, it just asks. The lenses live in the URL (`?journey=PROSPECT`,
 * `?qualification=`, `?relationship=`), so a filtered register can be shared and the
 * desk's counts link straight into one.
 *
 * The list route has no total (ask A2): journey counts are capped ("200+"), and the
 * footer says how many are shown rather than guessing how many exist. Hovering or
 * focusing a row loads its dossier ahead of the click; `j` / `k` move through the
 * rows and Enter opens one.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  Button,
  buttonClasses,
  EmptyLine,
  ErrorState,
  Input,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  useSearchParamState,
} from '@/components';
import { Icon } from '@/design/icons';
import { settle } from '@/lib/motion';
import { canMorph, companyNameTransition, isPlainClick, morphTo } from '@/lib/viewTransition';
import { useCan } from '@/platform/access';
import { Identifier } from '@/platform/mask';
import { usePageShortcuts } from '@/platform/shell';

import { CompaniesViewSwitch, Standing } from '../components';
import { JOURNEY_LABEL, JOURNEY_STAGES, MARKER_LABEL, QUALIFICATION_LABEL } from '../constants';
import { COUNT_CAP, useExporterProfiles, useJourneyCount, usePrefetchCompany } from '../hooks';
import { preloadExporterDetailPage } from '../lazyPages';
import { paths } from '../paths';
import type {
  ExporterJourney,
  ExporterMarker,
  ExporterProfileListItem,
  QualificationState,
} from '../types';

type Lens = 'ALL' | ExporterJourney;
const LENSES: readonly Lens[] = ['ALL', ...JOURNEY_STAGES];
const QUALIFICATIONS: readonly string[] = ['ANY', ...Object.keys(QUALIFICATION_LABEL)];
const RELATIONSHIPS: readonly string[] = ['ANY', ...Object.keys(MARKER_LABEL)];
/** A page of rows; "Show more" asks for the next, up to what one request returns. */
const PAGE_SIZE = 50;

function JourneyCount({ journey }: { journey: ExporterJourney }) {
  const count = useJourneyCount(journey);
  if (count === undefined) return null;
  return <>{count >= COUNT_CAP ? `${COUNT_CAP}+` : count}</>;
}

/** The muted second line: what the company does, and how it reached us. */
function identityLine(profile: ExporterProfileListItem): string | null {
  const parts = [
    profile.industry,
    profile.gstins.length > 1 ? `${profile.gstins.length} branches` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function Row({
  profile,
  prepare,
}: {
  profile: ExporterProfileListItem;
  /** Readies the company's dossier; resolves `true` once it can draw at once. */
  prepare: (id: string) => Promise<boolean>;
}) {
  const ended = profile.marker === 'ENDED';
  const outside = profile.pipeline_status === 'NOT_IN_PIPELINE';
  const line = identityLine(profile);
  const navigate = useNavigate();
  const to = paths.company(profile.customer_id);
  return (
    <li
      className="grid gap-x-6 gap-y-1 py-3.5 sm:grid-cols-[minmax(0,1fr)_auto]"
      data-testid="company-row"
    >
      <div className="min-w-0">
        <Link
          to={to}
          data-row-link
          onMouseEnter={() => void prepare(profile.customer_id)}
          onFocus={() => void prepare(profile.customer_id)}
          // The name travels into the dossier's title (§5.4) where the browser can
          // morph; anywhere else this is an ordinary link.
          onClick={(event) => {
            if (!isPlainClick(event) || !canMorph()) return;
            event.preventDefault();
            morphTo(() => navigate(to), {
              from: event.currentTarget.querySelector('[data-company-name]'),
              name: companyNameTransition(profile.customer_id),
              arriveAt: '[data-company-title]',
              ready: prepare(profile.customer_id),
            });
          }}
          className="font-display text-display-sm text-ink underline-offset-4 hover:underline focus-visible:underline"
        >
          <span data-company-name className={ended ? 'line-through decoration-ink-3' : undefined}>
            {profile.name ?? <span className="italic text-ink-3">Unnamed lead</span>}
          </span>
        </Link>
        <div className="mt-1">
          <Standing
            journey={profile.journey}
            qualification={profile.qualification}
            marker={profile.marker}
            outsidePipeline={outside}
          />
        </div>
        {line && <p className="mt-1 text-secondary text-ink-3">{line}</p>}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-secondary text-ink-3 sm:flex-col sm:items-end">
        <span className="inline-flex items-center gap-1.5">
          PAN <Identifier kind="PAN" value={profile.pan} />
        </span>
        {profile.gstins[0] && (
          <span className="inline-flex items-center gap-1.5">
            GSTIN <Identifier kind="GSTIN" value={profile.gstins[0]} />
            {profile.gstins.length > 1 && <span>+{profile.gstins.length - 1}</span>}
          </span>
        )}
        <span>
          {[profile.country, profile.relationship_manager].filter(Boolean).join(' · ') || '—'}
        </span>
      </div>
    </li>
  );
}

export function ExportersListPage() {
  // Absent, not disabled, for a role the server refuses (R-33, G3): DEVELOPER reads
  // the register and is offered no write screen.
  const canCreate = useCan('company.create');
  const canImport = useCan('company.import');
  const canTakeInRxil = useCan('company.rxilIntake');
  const [lens, setLens] = useSearchParamState<Lens>('journey', LENSES, 'ALL');
  const [qualification, setQualification] = useSearchParamState('qualification', QUALIFICATIONS, 'ANY');
  const [relationship, setRelationship] = useSearchParamState('relationship', RELATIONSHIPS, 'ANY');
  const [pages, setPages] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [name, setName] = useState('');
  const list = useRef<HTMLOListElement>(null);
  const prefetch = usePrefetchCompany();
  // The dossier, ready to draw: its code and the company's record.
  const prepare = (customerId: string) =>
    Promise.all([preloadExporterDetailPage(), prefetch(customerId)]).then((loaded) =>
      loaded.every(Boolean),
    );

  const limit = Math.min(PAGE_SIZE * pages, COUNT_CAP);
  const { data, isLoading, isError, isFetching, isPlaceholderData, refetch } = useExporterProfiles({
    name: name || undefined,
    journey: lens === 'ALL' ? undefined : lens,
    qualification: qualification === 'ANY' ? undefined : (qualification as QualificationState),
    marker: relationship === 'ANY' ? undefined : (relationship as ExporterMarker),
    limit,
  });
  const profiles = data?.profiles ?? [];
  const filtering = Boolean(
    name || qualification !== 'ANY' || relationship !== 'ANY' || lens !== 'ALL',
  );
  const mayHaveMore = profiles.length === limit && limit < COUNT_CAP;
  // The rows settle into place when a lens or filter brings a new set (§5.4) — keyed
  // on the filters whose rows are actually shown, so the old rows kept on screen
  // while the next set loads do not settle twice, and "Show more" does not at all.
  // The list is replayed, not remounted: rows in both sets are kept, not rebuilt.
  const filterKey = [name, lens, qualification, relationship].join('|');
  const [shownKey, setShownKey] = useState(filterKey);
  if (!isPlaceholderData && shownKey !== filterKey) setShownKey(filterKey);
  const settledKey = useRef(shownKey);
  useEffect(() => {
    if (settledKey.current === shownKey) return;
    settledKey.current = shownKey;
    settle(list.current);
  }, [shownKey]);

  // `j` / `k` move through the rows; the row's link takes Enter itself.
  const moveFocus = (step: number) => {
    const links = [
      ...(list.current?.querySelectorAll<HTMLAnchorElement>('[data-row-link]') ?? []),
    ];
    if (links.length === 0) return;
    const at = links.indexOf(document.activeElement as HTMLAnchorElement);
    links[Math.max(0, Math.min(links.length - 1, at === -1 ? 0 : at + step))]?.focus();
  };
  usePageShortcuts([
    { key: 'j', label: 'Next company', run: () => moveFocus(1) },
    { key: 'k', label: 'Previous company', run: () => moveFocus(-1) },
  ]);

  return (
    <div>
      <PageHeader
        title="Companies"
        meta={<CompaniesViewSwitch view="register" />}
        description="Find and manage company relationships. Ended relationships are hidden unless you search for them or filter by “Ended”."
        actions={
          <>
            {/* IQ-7's completion list (R-28): work on the records themselves, kept
                apart from the pipeline. */}
            <Link to={paths.identityCompletion} className={buttonClasses({ variant: 'quiet' })}>
              Identity to complete
            </Link>
            {/* The server admits ADMIN only: intake records a decision as RXIL's. */}
            {canTakeInRxil && (
              <Link to={paths.rxilIntake} className={buttonClasses({ variant: 'quiet' })}>
                RXIL intake
              </Link>
            )}
            {canImport && (
              <Link to={paths.importCompanies} className={buttonClasses()}>
                <Icon.csv size={16} aria-hidden />
                Import CSV
              </Link>
            )}
            {canCreate && (
              <Link to={paths.newCompany} className={buttonClasses({ variant: 'primary' })}>
                <Icon.add size={15} aria-hidden />
                Add company
              </Link>
            )}
          </>
        }
      />

      <div className="flex flex-col gap-3 border-b border-line pb-4 xl:flex-row xl:items-center xl:justify-between">
        <Segmented
          label="Journey stage"
          value={lens}
          onValueChange={(value) => {
            setLens(value);
            setPages(1);
          }}
          options={LENSES.map((value) => ({
            value,
            label: value === 'ALL' ? 'All' : JOURNEY_LABEL[value],
            count: value === 'ALL' ? undefined : <JourneyCount journey={value} />,
          }))}
        />
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <form
            role="search"
            className="relative"
            onSubmit={(event) => {
              event.preventDefault();
              setName(searchInput.trim());
              setPages(1);
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
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search by name"
              aria-label="Search by company name"
              className="pl-9 sm:w-64"
            />
          </form>
          <Select
            aria-label="Qualification"
            className="sm:w-auto"
            value={qualification === 'ANY' ? '' : qualification}
            onChange={(event) => {
              setQualification(event.target.value || 'ANY');
              setPages(1);
            }}
          >
            <option value="">Any qualification</option>
            {(Object.keys(QUALIFICATION_LABEL) as QualificationState[]).map((value) => (
              <option key={value} value={value}>
                {QUALIFICATION_LABEL[value]}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Relationship"
            className="sm:w-auto"
            value={relationship === 'ANY' ? '' : relationship}
            onChange={(event) => {
              setRelationship(event.target.value || 'ANY');
              setPages(1);
            }}
          >
            <option value="">Any relationship (ended hidden)</option>
            {(Object.keys(MARKER_LABEL) as ExporterMarker[]).map((value) => (
              <option key={value} value={value}>
                {MARKER_LABEL[value]}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {isError ? (
        <ErrorState title="Couldn't load companies." className="mt-4" onRetry={() => void refetch()}>
          Check your connection and try again.
        </ErrorState>
      ) : isLoading ? (
        <div className="divide-y divide-line" aria-hidden>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="space-y-2 py-4">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-4 w-96 max-w-full" />
            </div>
          ))}
        </div>
      ) : profiles.length === 0 ? (
        <EmptyLine
          className="py-8"
          action={
            !filtering &&
            canCreate && (
              <Link to={paths.newCompany} className="font-medium text-ink underline underline-offset-[3px]">
                Add the first one
              </Link>
            )
          }
        >
          {filtering ? 'No companies match this filter.' : 'No companies yet.'}
        </EmptyLine>
      ) : (
        <>
          <ol ref={list} aria-label="Companies" className="animate-settle divide-y divide-line">
            {profiles.map((profile) => (
              <Row key={profile.customer_id} profile={profile} prepare={prepare} />
            ))}
          </ol>
          <div className="flex items-center justify-between border-t border-line py-3 text-secondary text-ink-3">
            <span className="tabular-nums">
              {profiles.length} shown
              {isFetching ? ' · updating…' : ''}
              {profiles.length >= COUNT_CAP && ' — narrow the search to see the rest'}
            </span>
            {mayHaveMore && (
              <Button size="sm" onClick={() => setPages((count) => count + 1)} loading={isFetching}>
                Show more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
