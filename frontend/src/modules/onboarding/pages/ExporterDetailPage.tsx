/**
 * The company page — **shell, owner: Developer 2**.
 *
 * A sticky summary header — who the company is and where it stands — over one
 * tab per part of the relationship. The selected tab is in the URL (`?tab=`),
 * so a link, a reload or the back button lands where the reader was.
 *
 * Each tab renders one owner's panel:
 *
 *   Overview           panels/CompanyPanel.tsx          Developer 2
 *   Qualification      panels/QualificationPanel.tsx    Developer 2
 *   Conversation       panels/ConversationPanel.tsx     Developer 3A
 *   Deals              panels/DealsPanel.tsx            Developer 3B
 *   Documents          panels/DocumentsPanel.tsx        Developer 3B
 *   Background check   panels/BackgroundCheckPanel.tsx  Developer 4
 *   History            components/HistoryTimeline.tsx   Developer 1
 *
 * **The contact and activity queries stay here, not in the Conversation
 * panel.** They start with the profile on the first render, so opening the
 * Conversation tab shows them at once rather than starting a second round trip
 * then. The activity pagination state stays with them.
 *
 * The header shows the company's three separate positions — journey,
 * qualification, marker — and offers only the marker moves the server listed.
 * The journey has no control: it is never moved by hand.
 */

import { CalendarClock } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  Panel,
  ErrorState,
  PageHeader,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useSearchParamState,
} from '@/components';
import { formatDate, humanize } from '@/lib/format';
import { isStaffRole, useCurrentUser } from '@/platform/auth';
import { MaskedValue } from '@/platform/mask';

import {
  CompanyDealsList,
  NotInPipelineNotice,
  CompanyHistory,
  JourneyChip,
  MarkerBadge,
  MarkerControl,
  QualificationChip,
} from '../components';
import {
  useBringIntoPipeline,
  useCompanyDeals,
  useExporterActivities,
  useExporterContacts,
  useExporterConversation,
  useExporterProfileDetail,
} from '../hooks';
import { COMPANY_TABS, paths, type CompanyTab } from '../paths';
import type { ExporterActivityType, ExporterProfileDetail } from '../types';
import { BackgroundCheckPanel } from './panels/BackgroundCheckPanel';
import { CompanyPanel } from './panels/CompanyPanel';
import { ConversationPanel } from './panels/ConversationPanel';
import { DealsPanel } from './panels/DealsPanel';
import { DocumentsPanel } from './panels/DocumentsPanel';
import { QualificationPanel } from './panels/QualificationPanel';

/** Rows per activity page. Lives here because the shell builds the query
 * params and decides whether a next page exists. */
const ACTIVITY_PAGE_SIZE = 8;

const TAB_LABEL: Record<CompanyTab, string> = {
  overview: 'Overview',
  qualification: 'Qualification',
  conversation: 'Conversation',
  deals: 'Deals',
  documents: 'Documents',
  'background-check': 'Background check',
  history: 'History',
};

function displayName(profile: ExporterProfileDetail): string {
  return profile.name ?? 'Unnamed company';
}

/** One labelled fact in the summary strip. */
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 truncate text-sm text-ink">{children}</dd>
    </div>
  );
}

function SummaryStrip({ profile }: { profile: ExporterProfileDetail }) {
  const conversation = useExporterConversation(profile.customer_id);
  const gauge = conversation.data;

  return (
    <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-4 sm:grid-cols-3 lg:grid-cols-5">
      <Fact label="PAN">
        <MaskedValue value={profile.pan} />
      </Fact>
      <Fact label="GSTIN">
        <MaskedValue value={profile.gstins[0] ?? null} />
        {profile.gstins.length > 1 && (
          <span className="ml-1 text-xs text-ink-faint">+{profile.gstins.length - 1}</span>
        )}
      </Fact>
      <Fact label="Country">{profile.country ?? '—'}</Fact>
      <Fact label="Owner">{profile.relationship_manager ?? '—'}</Fact>
      <Fact label="Conversation">
        {gauge ? (
          <span className="inline-flex flex-wrap items-center gap-x-2">
            {humanize(gauge.conversation)}
            {gauge.check_back_on && (
              <span className="inline-flex items-center gap-1 text-xs text-status-review">
                <CalendarClock size={12} /> {formatDate(gauge.check_back_on)}
              </span>
            )}
          </span>
        ) : (
          '—'
        )}
      </Fact>
    </dl>
  );
}

export function ExporterDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const currentUser = useCurrentUser();
  // DEVELOPER reads the CRM (masked) but writes nothing and cannot load
  // verification results — the backend refuses those with 403 — so it gets no
  // Background check tab at all rather than a tab that renders nothing.
  const isStaff = isStaffRole(currentUser.role);
  const tabs = isStaff
    ? COMPANY_TABS
    : COMPANY_TABS.filter((value) => value !== 'background-check');
  const { data: profile, isLoading, isError, refetch } = useExporterProfileDetail(customerId);
  const [tab, setTab] = useSearchParamState<CompanyTab>('tab', tabs, 'overview');
  const [activityType, setActivityType] = useState<ExporterActivityType | ''>('');
  const [activityPage, setActivityPage] = useState(0);

  const contactQuery = useExporterContacts(customerId);
  const activityParams = useMemo(
    () => ({
      activityType: activityType || undefined,
      limit: ACTIVITY_PAGE_SIZE,
      offset: activityPage * ACTIVITY_PAGE_SIZE,
    }),
    [activityType, activityPage],
  );
  const activityQuery = useExporterActivities(customerId, activityParams);
  const dealsQuery = useCompanyDeals(customerId);
  const bringIntoPipeline = useBringIntoPipeline(customerId);

  if (!customerId) {
    return <p className="text-sm text-status-failed">Company id is missing.</p>;
  }

  if (isLoading) {
    return (
      <div className="space-y-5" aria-label="Loading company">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-28 rounded-lg" />
        <Skeleton className="h-10 w-full max-w-2xl" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <ErrorState title="Couldn't load this company." onRetry={() => void refetch()}>
        The record may no longer exist or the request failed.{' '}
        <Link to={paths.companies} className="font-medium text-brand-600 underline">
          Back to companies
        </Link>
      </ErrorState>
    );
  }

  // The detail response embeds contacts, so the page shows those until the
  // dedicated contacts query resolves — no empty flash on first paint.
  const contacts = contactQuery.data?.contacts ?? profile.contacts;
  const activities = activityQuery.data?.activities ?? [];
  const hasNextActivityPage = activities.length === ACTIVITY_PAGE_SIZE;
  const dealCount = dealsQuery.data?.total;
  // A company that exists only because it was somebody's buyer: its journey and both
  // gauges do not apply, and the server refuses them (plan P4-2, task 3.9). Read
  // here, below the guards, because it needs the loaded profile.
  const notInPipeline = profile.pipeline_status === 'NOT_IN_PIPELINE';

  return (
    // One `Tabs` root around the sticky header and the panels, so the triggers
    // and the contents share its ids (the tab <-> tabpanel wiring).
    <Tabs value={tab} onValueChange={(next) => setTab(next as CompanyTab)}>
      <div className="sticky -top-5 z-10 -mx-4 mb-5 border-b border-border bg-surface-subtle/95 px-4 pt-1 backdrop-blur sm:-top-6 sm:-mx-6 sm:px-6">
        <PageHeader
          back={{ to: paths.companies, label: 'Companies' }}
          title={displayName(profile)}
          meta={
            <>
              {/* A buyer-only company's `journey` reads LEAD because the column is
                  NOT NULL, not because anyone judged it (plan P4-2). Showing the
                  chip would claim a sales stage that does not exist, and the two
                  gauges below do not apply either. */}
              {notInPipeline ? (
                <span className="rounded-full border border-border-strong bg-surface-subtle px-2 py-0.5 text-xs font-medium text-ink-muted">
                  Not in pipeline
                </span>
              ) : (
                <>
                  <JourneyChip journey={profile.journey} />
                  <QualificationChip state={profile.qualification} />
                </>
              )}
              <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
            </>
          }
          description={
            <>
              Added {formatDate(profile.date_added)}
              {profile.marker_reason ? ` · ${profile.marker_reason}` : ''}
            </>
          }
          // Only the moves the server listed for this user; none, nothing.
          actions={
            <MarkerControl customerId={customerId} moves={profile.allowed_marker_moves ?? []} />
          }
        />
        <SummaryStrip profile={profile} />

        <TabsList aria-label="Company sections" className="mt-3 border-b-0">
          {tabs.map((value) => (
            <TabsTrigger key={value} value={value}>
              {TAB_LABEL[value]}
              {value === 'deals' && dealCount !== undefined && dealCount > 0 && (
                <span className="rounded-full bg-surface-sunken px-1.5 text-xs tabular-nums text-ink-muted">
                  {dealCount}
                </span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      <TabsContent value="overview">
        <CompanyPanel profile={profile} canEdit={isStaff} />
      </TabsContent>
      <TabsContent value="qualification">
        {notInPipeline ? (
          <NotInPipelineNotice
            what="Qualification"
            onBringIn={isStaff ? () => bringIntoPipeline.mutate({}) : undefined}
            busy={bringIntoPipeline.isPending}
          />
        ) : (
          <QualificationPanel customerId={customerId} />
        )}
      </TabsContent>
      <TabsContent value="conversation">
        {notInPipeline ? (
          <NotInPipelineNotice
            what="The conversation gauge"
            onBringIn={isStaff ? () => bringIntoPipeline.mutate({}) : undefined}
            busy={bringIntoPipeline.isPending}
          />
        ) : (
        <ConversationPanel
          customerId={customerId}
          contacts={contacts}
          contactsLoading={contactQuery.isLoading}
          activities={activities}
          activitiesLoading={activityQuery.isLoading}
          activitiesFetching={activityQuery.isFetching}
          activityType={activityType}
          onActivityTypeChange={setActivityType}
          activityPage={activityPage}
          onActivityPageChange={setActivityPage}
          hasNextActivityPage={hasNextActivityPage}
          isStaff={isStaff}
        />
        )}
      </TabsContent>
      <TabsContent value="deals">
        {/* Both sides of this company's trade (task 3.9). `DealsPanel` is the
            seller side — it owns the "open a deal" control and shows each deal's
            stage — and the buyer side is a plain list, because there is nothing to
            open there: a deal is opened on the company that is selling. */}
        <div className="flex flex-col gap-5">
          <DealsPanel customerId={customerId} isStaff={isStaff} />
          <Panel
            title="Bought from"
            description="Deals where this company is the buyer. A company can be a buyer on one deal and a seller on another."
          >
            <CompanyDealsList companyId={customerId} as="buyer" />
          </Panel>
        </div>
      </TabsContent>
      <TabsContent value="documents">
        <DocumentsPanel customerId={customerId} isStaff={isStaff} />
      </TabsContent>
      <TabsContent value="background-check">
        <BackgroundCheckPanel customerId={customerId} isStaff={isStaff} />
      </TabsContent>
      <TabsContent value="history">
        <CompanyHistory customerId={customerId} />
      </TabsContent>
    </Tabs>
  );
}
