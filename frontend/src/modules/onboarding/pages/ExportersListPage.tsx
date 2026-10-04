/**
 * The company list — **owner: Developer 2** (L2-14).
 *
 * Every filter runs on the server: the journey tabs, qualification, marker and
 * the name search. That includes the rule that ENDED companies leave the
 * default list and come back for a search or the "Ended" marker filter —
 * this page does not re-implement it, it just asks.
 *
 * The journey tab lives in the URL (`?journey=PROSPECT`), so the Home page's
 * stage counts can link straight to a filtered list.
 */

import { ChevronLeft, ChevronRight, Plus, Search, Upload } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import {
  Button,
  buttonClasses,
  Card,
  ErrorState,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Table,
  Tabs,
  TabsList,
  TabsTrigger,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  useSearchParamState,
} from '@/components';
import { useCan } from '@/platform/access';
import { MaskedValue } from '@/platform/mask';

import { JourneyChip, MarkerBadge, QualificationChip } from '../components';
import {
  JOURNEY_LABEL,
  JOURNEY_STAGES,
  MARKER_LABEL,
  QUALIFICATION_LABEL,
} from '../constants';
import { useExporterProfiles } from '../hooks';
import { paths } from '../paths';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../types';

type Tab = 'ALL' | ExporterJourney;
const TABS: readonly Tab[] = ['ALL', ...JOURNEY_STAGES];
const QUALIFICATION_OPTIONS = Object.keys(QUALIFICATION_LABEL) as QualificationState[];
const MARKER_OPTIONS = Object.keys(MARKER_LABEL) as ExporterMarker[];
const COLUMNS = 6;
/** Rows per page. The search response carries no total, so a full page means
 * "there may be more". */
const PAGE_SIZE = 50;

function TableSkeletonRow() {
  return (
    <tr>
      {Array.from({ length: COLUMNS }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className="h-4 w-24" />
        </td>
      ))}
    </tr>
  );
}

export function ExportersListPage() {
  // Absent, not disabled, for a role the server refuses (R-33, G3): DEVELOPER reads
  // the register and is offered no write screen.
  const canCreate = useCan('company.create');
  const canImport = useCan('company.import');
  const canTakeInRxil = useCan('company.rxilIntake');
  const [searchInput, setSearchInput] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [tab, setTabParam] = useSearchParamState<Tab>('journey', TABS, 'ALL');
  const [qualification, setQualification] = useState<QualificationState | ''>('');
  const [marker, setMarker] = useState<ExporterMarker | ''>('');
  const [page, setPage] = useState(0);

  const { data, isLoading, isError, isFetching, refetch } = useExporterProfiles({
    name: nameFilter || undefined,
    journey: tab === 'ALL' ? undefined : tab,
    qualification: qualification || undefined,
    marker: marker || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const profiles = data?.profiles ?? [];
  const filtering = Boolean(nameFilter || qualification || marker || tab !== 'ALL');
  const hasNextPage = profiles.length === PAGE_SIZE;

  // Any change of filter starts again from the first page.
  const setTab = (value: Tab) => {
    setTabParam(value);
    setPage(0);
  };

  return (
    <div>
      <PageHeader
        title="Companies"
        description="Find and manage company relationships. Ended relationships are hidden unless you search for them or filter by “Ended”."
        actions={
          <>
            {/* IQ-7's completion list (R-28): work on the records themselves, kept
                apart from the pipeline. */}
            <Link to={paths.identityCompletion} className={buttonClasses({ variant: 'ghost' })}>
              Identity to complete
            </Link>
            {canImport && (
              <Link to={paths.importCompanies} className={buttonClasses()}>
                <Upload size={15} />
                Import CSV
              </Link>
            )}
            {/* The server admits ADMIN only: intake records a decision as RXIL's. */}
            {canTakeInRxil && (
              <Link to={paths.rxilIntake} className={buttonClasses()}>
                RXIL intake
              </Link>
            )}
            {canCreate && (
              <Link to={paths.newCompany} className={buttonClasses({ variant: 'primary' })}>
                <Plus size={15} />
                Add company
              </Link>
            )}
          </>
        }
      />

      <Card>
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
          <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} variant="pill">
            <TabsList aria-label="Journey stage">
              {TABS.map((value) => (
                <TabsTrigger key={value} value={value}>
                  {value === 'ALL' ? 'All' : JOURNEY_LABEL[value]}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <form
              role="search"
              className="relative"
              onSubmit={(e) => {
                e.preventDefault();
                setNameFilter(searchInput.trim());
                setPage(0);
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
                className="pl-9 sm:w-64"
              />
            </form>
            <Select
              aria-label="Qualification"
              className="sm:w-auto"
              value={qualification}
              onChange={(e) => {
                setQualification(e.target.value as QualificationState | '');
                setPage(0);
              }}
            >
              <option value="">Any qualification</option>
              {QUALIFICATION_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {QUALIFICATION_LABEL[value]}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Relationship"
              className="sm:w-auto"
              value={marker}
              onChange={(e) => {
                setMarker(e.target.value as ExporterMarker | '');
                setPage(0);
              }}
            >
              <option value="">Any relationship (ended hidden)</option>
              {MARKER_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {MARKER_LABEL[value]}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {isError ? (
          <ErrorState title="Couldn't load companies." className="m-4" onRetry={() => void refetch()}>
            Check your connection and try again.
          </ErrorState>
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Company</Th>
                <Th>PAN</Th>
                <Th>GSTIN</Th>
                <Th>Journey</Th>
                <Th>Qualification</Th>
                <Th>Owner</Th>
              </tr>
            </THead>
            <TBody>
              {isLoading && Array.from({ length: 6 }).map((_, i) => <TableSkeletonRow key={i} />)}

              {!isLoading && profiles.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS} className="px-4 py-12 text-center text-sm text-ink-muted">
                    {filtering ? (
                      'No companies match this filter.'
                    ) : (
                      <>
                        No companies yet —{' '}
                        <Link to={paths.newCompany} className="font-medium text-brand-600 underline">
                          Add company
                        </Link>
                      </>
                    )}
                  </td>
                </tr>
              )}

              {!isLoading &&
                profiles.map((profile) => (
                  <Tr key={profile.customer_id}>
                    <Td className="font-medium text-ink">
                      <Link
                        to={paths.company(profile.customer_id)}
                        className="hover:text-brand-600 hover:underline"
                      >
                        {profile.name ?? <span className="italic text-ink-faint">Unnamed lead</span>}
                      </Link>
                      {profile.country && (
                        <span className="ml-2 text-xs font-normal text-ink-faint">{profile.country}</span>
                      )}
                    </Td>
                    <Td>
                      <MaskedValue value={profile.pan} />
                    </Td>
                    <Td>
                      <MaskedValue value={profile.gstins[0] ?? null} />
                      {profile.gstins.length > 1 && (
                        <span className="ml-1.5 text-xs text-ink-faint">+{profile.gstins.length - 1}</span>
                      )}
                    </Td>
                    <Td>
                      <span className="inline-flex items-center gap-1.5">
                        <JourneyChip journey={profile.journey} />
                        <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
                      </span>
                    </Td>
                    <Td>
                      <QualificationChip state={profile.qualification} />
                    </Td>
                    <Td className="text-ink-muted">{profile.relationship_manager ?? '—'}</Td>
                  </Tr>
                ))}
            </TBody>
          </Table>
        )}

        {!isError && (page > 0 || hasNextPage) && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm text-ink-muted">
            <span>
              Page {page + 1}
              {isFetching && !isLoading ? ' · updating…' : ''}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft size={15} />
                Previous
              </Button>
              <Button size="sm" disabled={!hasNextPage} onClick={() => setPage((p) => p + 1)}>
                Next
                <ChevronRight size={15} />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
