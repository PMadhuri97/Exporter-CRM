/**
 * The Companies list (frontend-plan §8.3): record list items, not a table (§6.7).
 * Each company is its name as a link, one line of key facts (industry, country, its
 * identifiers as the role may see them, the RM), and its status badges on the right.
 *
 * Every filter runs on the server: the journey lens, qualification, relationship
 * and the name search — including the rule that ENDED companies leave the default
 * list and come back for a search or the "Ended" filter; this page does not
 * re-implement it, it just asks. The lenses live in the URL (`?journey=PROSPECT`,
 * `?qualification=`, `?relationship=`), so a filtered list can be shared and Home's
 * counts link straight into one.
 *
 * **Whose companies.** `?owner=me` is *My companies*, reached from its own row in the
 * side navigation (the page is titled so). `?owner=none` and `?owner=inactive` narrow
 * to unassigned companies and to those whose RM has been deactivated; both still work,
 * but the bar no longer offers them as a dropdown, so they are URL lenses now. Every one
 * of them is a filter only: every reader sees every company. ADMIN and holders of
 * `exporters:assign_rm` get **Reassign companies**.
 *
 * The list route has no total: journey counts are capped ("200+"), and the
 * footer says how many are shown rather than guessing how many exist. Hovering or
 * focusing a row loads its record ahead of the click.
 */

import { useCallback, useState, type SetStateAction } from 'react';
import { Link } from 'react-router-dom';

import {
  Button,
  buttonClasses,
  EmptyLine,
  ErrorState,
  Input,
  PageHeader,
  RecordListItem,
  Segmented,
  Select,
  Skeleton,
  useSearchParamState,
} from '@/components';
import { Icon } from '@/design/icons';
import { useCan, useHasPermission } from '@/platform/access';

import { BulkReassignPanel, CompanyBadges } from '../components';
import { CompanyFilterPanel, type CompanyFilters } from '../components/CompanyFilterPanel';
import { saveObjectUrl } from '../components/useOpenDocument';
import { companiesToCsv, csvBlob, csvFileName } from '../exportCompanies';
import { JOURNEY_LABEL, JOURNEY_STAGES, MARKER_LABEL, QUALIFICATION_LABEL } from '../constants';
import { COUNT_CAP, useExporterProfiles, useJourneyCount, usePrefetchCompany } from '../hooks';
import { preloadExporterDetailPage } from '../lazyPages';
import { paths } from '../paths';
import type {
  ExporterJourney,
  ExporterMarker,
  ExporterProfileListItem,
  QualificationState,
  RelationshipManagerFilter,
} from '../types';

type Lens = 'ALL' | ExporterJourney;
const LENSES: readonly Lens[] = ['ALL', ...JOURNEY_STAGES];
const QUALIFICATIONS: readonly string[] = ['ANY', ...Object.keys(QUALIFICATION_LABEL)];
const RELATIONSHIPS: readonly string[] = ['ANY', ...Object.keys(MARKER_LABEL)];
/**
 * Who a company belongs to, as a URL lens rather than a control.
 *
 * `me` is *My companies*, which has its own row in the side navigation — the page is
 * titled for it. `none` (unassigned) and `inactive` (the RM's account is deactivated)
 * still filter when asked for in the URL and are still the server's own filters; the
 * dropdown that offered them has gone from the bar, so nothing links to them today.
 */
type Owner = 'ANY' | 'me' | 'none' | 'inactive';
const OWNERS: readonly Owner[] = ['ANY', 'me', 'none', 'inactive'];
/** A page of rows; "Show more" asks for the next, up to what one request returns. */
const PAGE_SIZE = 50;

function JourneyCount({ journey }: { journey: ExporterJourney }) {
  const count = useJourneyCount(journey);
  if (count === undefined) return null;
  return <>{count >= COUNT_CAP ? `${COUNT_CAP}+` : count}</>;
}

/**
 * The muted second line: what the company does, where it is, and who holds it.
 *
 * Identifiers are deliberately not here. PAN and GSTIN are not what anyone scans a list
 * for — they are looked up on a company already found — and putting masked values on
 * every row made each one read as a string of dots. The branch count went with the
 * GSTINs it was counting; branches are on the company's own record, with each one's
 * state. Nothing is hidden by this: the company record shows all of it.
 */
function identityLine(profile: ExporterProfileListItem): string | null {
  const parts = [
    profile.industry,
    profile.country,
    profile.relationship_manager_name
      ? `RM ${profile.relationship_manager_name}${profile.relationship_manager_inactive ? ' (deactivated)' : ''}`
      : 'No RM',
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function Row({
  profile,
  prepare,
}: {
  profile: ExporterProfileListItem;
  /** Readies the company's record; resolves `true` once it can draw at once. */
  prepare: (id: string) => Promise<boolean>;
}) {
  const outside = profile.pipeline_status === 'NOT_IN_PIPELINE';
  const line = identityLine(profile);
  return (
    <RecordListItem
      to={paths.company(profile.customer_id)}
      title={profile.name ?? 'Unnamed lead'}
      // An ended relationship: the name greyed (§18.2).
      muted={profile.marker === 'ENDED'}
      onIntent={() => void prepare(profile.customer_id)}
      data-testid="company-row"
      facts={line}
      badges={
        <CompanyBadges
          journey={profile.journey}
          qualification={profile.qualification}
          marker={profile.marker}
          outsidePipeline={outside}
        />
      }
    />
  );
}

export function ExportersListPage() {
  // Absent, not disabled, for a role the server refuses: DEVELOPER reads
  // the list and is offered no write screen.
  const canCreate = useCan('company.create');
  const canImport = useCan('company.import');
  const canTakeInRxil = useCan('company.rxilIntake');
  const canReassign = useHasPermission('exporters:assign_rm');
  const [reassigning, setReassigning] = useState(false);
  // Read-only here now: the lens comes from the URL, not from a control on the bar.
  const [owner] = useSearchParamState<Owner>('owner', OWNERS, 'ANY');
  const [lens, setLens] = useSearchParamState<Lens>('journey', LENSES, 'ALL');
  const [qualification, setQualification] = useSearchParamState('qualification', QUALIFICATIONS, 'ANY');
  const [relationship, setRelationship] = useSearchParamState('relationship', RELATIONSHIPS, 'ANY');
  const [pages, setPages] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [name, setName] = useState('');
  // The panel's filters, applied only when it says so. Held here rather than in the
  // URL: two of them are free text, which `useSearchParamState` cannot express — a
  // shareable filtered link is worth having and is a separate change.
  const [filters, setFilters] = useState<CompanyFilters>({});
  // Referentially stable, which the panel's typing timer relies on. It also resets the
  // paging: the old offset belongs to the old filter.
  const changeFilters = useCallback((next: SetStateAction<CompanyFilters>) => {
    setFilters(next);
    setPages(1);
  }, []);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // The panel stores only filters that are actually set, so the key count is the badge.
  const filterCount = Object.keys(filters).length;
  const prefetch = usePrefetchCompany();
  // The company record, ready to draw: its code and the company's data.
  const prepare = (customerId: string) =>
    Promise.all([preloadExporterDetailPage(), prefetch(customerId)]).then((loaded) =>
      loaded.every(Boolean),
    );

  const limit = Math.min(PAGE_SIZE * pages, COUNT_CAP);
  const { data, isLoading, isError, isFetching, refetch } = useExporterProfiles({
    name: name || undefined,
    journey: lens === 'ALL' ? undefined : lens,
    qualification: qualification === 'ANY' ? undefined : (qualification as QualificationState),
    marker: relationship === 'ANY' ? undefined : (relationship as ExporterMarker),
    ...filters,
    relationship_manager: owner === 'ANY' ? undefined : (owner as RelationshipManagerFilter),
    limit,
  });
  const profiles = data?.profiles ?? [];
  const filtering = Boolean(
    name ||
      qualification !== 'ANY' ||
      relationship !== 'ANY' ||
      lens !== 'ALL' ||
      owner !== 'ANY' ||
      filterCount,
  );
  // The panel's filters count here too: they are filters other than the owner, which is
  // the whole distinction this second flag draws.
  const filteringOtherThanOwner = Boolean(
    name || qualification !== 'ANY' || relationship !== 'ANY' || lens !== 'ALL' || filterCount,
  );
  const mayHaveMore = profiles.length === limit && limit < COUNT_CAP;

  return (
    <div>
      {/* No List/Pipeline switch here. The board is a side-navigation destination of its
          own, so offering it a second time on this page was the same screen behind two
          doors — which read as duplicated navigation. */}
      <PageHeader
        title={owner === 'me' ? 'My companies' : 'Companies'}
        actions={
          <>
            {/* The identity completion list: work on the records themselves, kept
                apart from the pipeline. */}
            <Link to={paths.identityCompletion} className={buttonClasses({ variant: 'subtle' })}>
              Identity to complete
            </Link>
            {/* The server admits ADMIN only: intake records a decision as RXIL's. */}
            {canTakeInRxil && (
              <Link to={paths.rxilIntake} className={buttonClasses({ variant: 'subtle' })}>
                RXIL intake
              </Link>
            )}
            {canReassign && (
              <Button variant="subtle" onClick={() => setReassigning((open) => !open)}>
                Reassign companies
              </Button>
            )}
            {canImport && (
              <Link to={paths.importCompanies} className={buttonClasses()}>
                <Icon.upload size={16} aria-hidden />
                Import companies
              </Link>
            )}
            {canCreate && (
              <Link to={paths.newCompany} className={buttonClasses({ variant: 'primary' })}>
                <Icon.add size={16} aria-hidden />
                New company
              </Link>
            )}
          </>
        }
      />

      <section aria-label="Company list" className="rounded border border-line bg-surface">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
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
              <option value="">Any relationship</option>
              {(Object.keys(MARKER_LABEL) as ExporterMarker[]).map((value) => (
                <option key={value} value={value}>
                  {MARKER_LABEL[value]}
                </option>
              ))}
            </Select>

            {/* What is on screen, as a file. Disabled with nothing to write, and it
                says the row count so "export" is not read as "export everything" — there
                is no server-side export, so this is the loaded page of the filtered
                list. */}
            <Button
              variant="subtle"
              disabled={profiles.length === 0}
              onClick={() => {
                const url = URL.createObjectURL(csvBlob(companiesToCsv(profiles)));
                saveObjectUrl(url, csvFileName());
                // On a later tick: revoking at once cancels the save in some browsers.
                window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
              }}
            >
              <Icon.download size={16} aria-hidden />
              Export {profiles.length > 0 && `(${profiles.length})`}
            </Button>

            {/* The rest of the filters, behind one button. The count is what tells
                somebody the list is narrowed — without it a filtered list looks like an
                empty one. */}
            <Button variant="subtle" onClick={() => setFiltersOpen(true)}>
              <Icon.filter size={16} aria-hidden />
              Filters
              {filterCount > 0 && (
                <span className="ml-1 rounded-full bg-accent-tint px-1.5 text-caption font-semibold text-accent tabular-nums">
                  {filterCount}
                </span>
              )}
            </Button>
            {filterCount > 0 && (
              <Button
                variant="subtle"
                onClick={() => {
                  setFilters({});
                  setPages(1);
                }}
              >
                Clear
              </Button>
            )}
          </div>
        </div>

        {reassigning && (
          <BulkReassignPanel
            shown={profiles}
            journey={lens === 'ALL' ? undefined : lens}
            onClose={() => setReassigning(false)}
          />
        )}

        {isError ? (
          <ErrorState title="Couldn't load companies." className="m-4" onRetry={() => void refetch()}>
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
        ) : profiles.length === 0 && owner === 'me' && !filteringOtherThanOwner ? (
          <EmptyLine className="px-4 py-8">
            You are not the relationship manager of any company yet. Open an unassigned
            company and choose <strong>Assign to me</strong>.
          </EmptyLine>
        ) : profiles.length === 0 ? (
          <EmptyLine
            className="px-4 py-8"
            action={
              !filtering &&
              canCreate && (
                <Link to={paths.newCompany} className="font-semibold text-accent underline-offset-2 hover:underline">
                  Add the first one
                </Link>
              )
            }
          >
            {filtering ? 'No companies match this filter.' : 'No companies yet.'}
          </EmptyLine>
        ) : (
          <>
            <ol aria-label="Companies" className="divide-y divide-line">
              {profiles.map((profile) => (
                <Row key={profile.customer_id} profile={profile} prepare={prepare} />
              ))}
            </ol>
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-secondary text-ink-3">
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
      </section>

      {/* Mounted only while open, so every opening starts from the filters in force. */}
      {filtersOpen && (
        <CompanyFilterPanel
          applied={filters}
          shown={profiles.length}
          loading={isLoading || isFetching}
          onChange={changeFilters}
          onClose={() => setFiltersOpen(false)}
        />
      )}
    </div>
  );
}
