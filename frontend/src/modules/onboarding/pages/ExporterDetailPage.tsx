/**
 * The company record (frontend-plan §8.5): the record header (§6.3) with the key
 * fields, the actions the server serves for this company and user, and the journey
 * path; tabs under it; and the related records in a right-hand column (§6.6). The
 * `?tab=` keys are unchanged, so every old link lands where it did.
 *
 *   Details            panels/CompanyPanel.tsx
 *   Qualification      panels/QualificationPanel.tsx
 *   Activity           panels/ConversationPanel.tsx
 *   Deals              panels/CompanyDealsTab.tsx (deals, and trade by counterparty)
 *   Documents          panels/DocumentsPanel.tsx
 *   Background check   panels/BackgroundCheckPanel.tsx
 *   History            components/HistoryTimeline.tsx
 *
 * Header actions are built only from what the server served (`can_open_deal`, the
 * background check's `allowed_moves`, `open_proposal.allowed_actions`, `rekyc_due`);
 * nothing is worked out from rules held here.
 *
 * The contact and activity queries stay here, not in the Activity tab: they start with
 * the profile, so opening that tab shows them at once.
 */

import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  Badge,
  ErrorState,
  Path,
  RecordHeader,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useSearchParamState,
  type PathStep,
  type RecordAction,
  type RecordField,
} from '@/components';
import { formatDate } from '@/lib/format';
import { useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';
import { rememberCompany } from '@/platform/shell';

import {
  AddressesSection,
  BankAccountsSection,
  CollectionsOwnerSection,
  CompanyGroupPanel,
  DefaultPaymentTermSection,
  CompanyRelatedCards,
  CompanyHistory,
  GstRegistrationsSection,
  IdentityGapNotice,
  MarkerBadge,
  MarkerControl,
  NotInPipelineNotice,
} from '../components';
import {
  BackgroundCheckBadge,
  ConversationBadge,
  OutsidePipelineBadge,
  QualificationBadge,
} from '../components/StatusBadge';
import {
  useBackgroundCheck,
  useBringIntoPipeline,
  useCompanyDeals,
  useExporterActivities,
  useCompanySanctions,
  useExporterContacts,
  useExporterConversation,
  useExporterProfileDetail,
} from '../hooks';
import { COMPANY_TABS, paths, type CompanyTab } from '../paths';
import type { ExporterActivityType, ExporterJourney, ExporterProfileDetail } from '../types';

import { CompanyPanel } from './panels/CompanyPanel';
import { ConversationPanel } from './panels/ConversationPanel';
import { CompanyDealsTab } from './panels/CompanyDealsTab';
import { DocumentsPanel } from './panels/DocumentsPanel';
import { QualificationPanel } from './panels/QualificationPanel';
import { COMMUNICATION_HINT } from '../constants';
import { countryLabel } from '../countries';

// The Background check tab is its own chunk: a role without the tab never loads it.
const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

/** Rows per activity page. Lives here because the shell builds the query
 * params and decides whether a next page exists. */
const ACTIVITY_PAGE_SIZE = 8;

const TAB_LABEL: Record<CompanyTab, string> = {
  overview: 'Details',
  qualification: 'Qualification',
  conversation: 'Activity',
  deals: 'Deals',
  documents: 'Documents',
  'background-check': 'Background check',
  group: 'Group',
  history: 'History',
};

const JOURNEY_STEPS: PathStep<ExporterJourney>[] = [
  { key: 'LEAD', label: 'Lead' },
  { key: 'PROSPECT', label: 'Prospect' },
  { key: 'CUSTOMER', label: 'Customer' },
];

// The journey bar carries no guidance line. What moves it on is never a manual action
// (architecture: the server advances it), and each step's caption restated what the
// qualification and background-check gauges sitting beside it already show.

function displayName(profile: ExporterProfileDetail): string {
  return profile.name ?? 'Unnamed company';
}

export function ExporterDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  // DEVELOPER reads the CRM (masked) but writes nothing and cannot load
  // verification results — the backend refuses those with 403 — so it gets no
  // Background check tab at all, and no request for one.
  const isStaff = useCan('crm.write');
  const canReadCompliance = useCan('compliance.read');
  // Flagging a branch stops trade through it, so it is a compliance decision and not
  // a sales one. The server refuses it for OPERATIONS; the screen does not
  // offer it either, rather than showing a button that 403s.
  const canFlagBranches = useCan('gst.flag');
  const tabs = canReadCompliance
    ? COMPANY_TABS
    : COMPANY_TABS.filter((value) => value !== 'background-check');
  const { data: profile, isLoading, isError, refetch } = useExporterProfileDetail(customerId);
  const [tab, setTab] = useSearchParamState<CompanyTab>('tab', tabs, 'overview');
  const [activityType, setActivityType] = useState<ExporterActivityType | ''>('');
  const [activityPage, setActivityPage] = useState(0);

  const contactQuery = useExporterContacts(customerId);
  // A sanctions true match flags the company: read only by those who see compliance work.
  const sanctions = useCompanySanctions(customerId, canReadCompliance);
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
  const conversation = useExporterConversation(customerId);
  // Only for a role the background-check routes admit: no request otherwise.
  const check = useBackgroundCheck(canReadCompliance ? customerId : undefined);
  // Hooks run before the missing-id guard below; the mutation is only offered after it.
  const bringIntoPipeline = useBringIntoPipeline(customerId ?? '');
  // Search's "Recent". The breadcrumbs are in the record header.
  const userId = String(useCurrentUser().id);
  const name = profile ? displayName(profile) : null;
  useEffect(() => {
    if (customerId && name) rememberCompany(userId, { id: customerId, name });
  }, [customerId, name, userId]);
  // Set to open the Activity tab's composer from outside it.
  const [logRequested, setLogRequested] = useState(false);

  if (!customerId) {
    return <p className="text-body text-negative">Company id is missing.</p>;
  }

  if (isLoading) {
    return (
      <div className="max-w-reading space-y-5" aria-label="Loading company">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-4 w-96 max-w-full" />
        <Skeleton className="h-24 rounded" />
        <Skeleton className="h-64 rounded" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <ErrorState title="Couldn't load this company." onRetry={() => void refetch()}>
        The record may no longer exist or the request failed.{' '}
        <Link to={paths.companies} className="font-medium text-ink underline">
          Back to companies
        </Link>
      </ErrorState>
    );
  }

  // The detail response embeds contacts, so the page shows those until the
  // dedicated contacts query resolves — no empty flash on first paint.
  const contacts = contactQuery.data?.contacts ?? profile.contacts;
  // A prospect or customer needs someone to reach: a deal is not handed over without
  // an active primary contact, so the header says so before the handover does.
  const missingPrimaryContact =
    (profile.journey === 'PROSPECT' || profile.journey === 'CUSTOMER') &&
    !contacts.some((contact) => contact.is_primary_contact && contact.status === 'ACTIVE');
  const activities = activityQuery.data?.activities ?? [];
  const hasNextActivityPage = activities.length === ACTIVITY_PAGE_SIZE;
  const dealCount = dealsQuery.data?.total;
  // A company that exists only because it was somebody's buyer: its journey and both
  // gauges do not apply, and the server refuses them.
  const notInPipeline = profile.pipeline_status === 'NOT_IN_PIPELINE';
  const gauge = conversation.data;
  const standing = check.data;
  const clearUntil =
    standing?.compliance?.is_clear && standing.compliance.clear_expires_at
      ? standing.compliance.clear_expires_at
      : null;

  // The header's actions (frontend-plan §8.5), built only from what the server served
  // for this company and this user. Each opens the tab where the work is done.
  const actions: RecordAction[] = [];
  if (standing?.open_proposal?.allowed_actions?.some((action) => action !== 'WITHDRAW')) {
    actions.push({ label: 'Review proposal', onSelect: () => setTab('background-check') });
  }
  if (isStaff && !notInPipeline) {
    actions.push({
      label: 'Log a call',
      onSelect: () => {
        setTab('conversation');
        setLogRequested(true);
      },
    });
  }
  if (dealsQuery.data?.can_open_deal) {
    actions.push({ label: 'Open deal', onSelect: () => setTab('deals') });
  }
  if (standing?.value === 'NOT_STARTED' && (standing.allowed_moves ?? []).some((move) => move.to_value === 'IN_REVIEW')) {
    actions.push({ label: 'Start background check', onSelect: () => setTab('background-check') });
  }
  if (standing?.rekyc_due) {
    actions.push({ label: 'Open Re-KYC', onSelect: () => setTab('background-check') });
  }
  if (notInPipeline && isStaff) {
    actions.push({
      label: 'Bring into pipeline',
      onSelect: () => bringIntoPipeline.mutate({}),
      loading: bringIntoPipeline.isPending,
    });
  }

  const fields: RecordField[] = [];
  if (!notInPipeline) {
    fields.push({ label: 'Qualification', value: <QualificationBadge state={profile.qualification} /> });
    if (gauge) {
      fields.push({
        label: 'Communication',
        hint: COMMUNICATION_HINT,
        value: <ConversationBadge value={gauge.conversation} checkBackOn={gauge.check_back_on} />,
      });
    }
  }
  if (canReadCompliance && standing) {
    fields.push({
      label: 'Background check',
      // The badge alone. The cycle number and kind that used to sit under it ("Cycle 2 ·
      // Re-KYB") describe how the check was arrived at, not where it stands — that belongs
      // on the Background check tab, which shows the cycle in full.
      value: (
        <BackgroundCheckBadge
          state={standing.value}
          risk={standing.risk_rating}
          clearUntil={clearUntil}
          awaitingApproval={standing.awaiting_approval}
          rekycDue={standing.rekyc_due}
        />
      ),
    });
  }
  // PAN and GSTIN are deliberately not in this strip. They are identifiers, not state:
  // the header carries what someone needs at a glance to judge the company, and both
  // remain on the Company panel (PAN) and in `GstRegistrationsSection` (the GSTINs,
  // each with its branch state) where they can be read in full.

  const facts = [
    profile.industry,
    profile.country ? countryLabel(profile.country) : null,
    profile.year_established ? `since ${profile.year_established}` : null,
    profile.relationship_manager_name ? `RM ${profile.relationship_manager_name}` : null,
  ].filter(Boolean);

  return (
    // One `Tabs` root around the header and the tabs, so the triggers and the
    // contents share its ids (the tab <-> tabpanel wiring).
    <Tabs value={tab} onValueChange={(next) => setTab(next as CompanyTab)}>
      <RecordHeader
        breadcrumbs={[{ label: 'Companies', to: paths.companies }, { label: displayName(profile) }]}
        objectType="Company"
        title={displayName(profile)}
        titleBadges={
          <>
            <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
            {sanctions.data?.flagged && (
              <Badge tone="negative" title="A sanctions true match is proposed or confirmed">
                Sanctions match
              </Badge>
            )}
            {missingPrimaryContact && (
              <Badge tone="attention" title="Add an active primary contact before handing over a deal">
                No primary contact
              </Badge>
            )}
          </>
        }
        meta={
          <>
            {facts.join(' · ') || `Added ${formatDate(profile.date_added)}`}
            {profile.marker_reason ? ` · ${profile.marker_reason}` : ''}
          </>
        }
        fields={fields}
        actions={actions}
        path={
          notInPipeline ? (
            <div className="flex flex-wrap items-center gap-3">
              <OutsidePipelineBadge />
              <span className="text-secondary text-ink-2">
                A buyer-only company: the journey does not apply until it is brought into the pipeline.
              </span>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Path
                label="Journey"
                steps={JOURNEY_STEPS}
                current={profile.journey}
                className="min-w-0 flex-1"
              />
              {/* Only the marker moves the server listed for this user; none, nothing. */}
              <MarkerControl customerId={customerId} moves={profile.allowed_marker_moves ?? []} />
            </div>
          )
        }
      />

      <TabsList aria-label="Company" className="mt-4">
        {tabs.map((value) => (
          <TabsTrigger key={value} value={value}>
            {TAB_LABEL[value]}
            {value === 'deals' && dealCount !== undefined && dealCount > 0 && (
              <span className="font-normal tabular-nums text-ink-3">({dealCount})</span>
            )}
            {value === 'background-check' && (standing?.awaiting_approval || standing?.rekyc_due) && (
              <span aria-label="needs attention" className="h-1.5 w-1.5 rounded-full bg-attention-solid" />
            )}
          </TabsTrigger>
        ))}
      </TabsList>

      {/* The tab's content, and the related records beside it from 1280px (§8.5);
          below that the related cards follow the content. */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22.5rem]">
        <div className="min-w-0">
          <TabsContent value="overview">
            <div className="flex flex-col gap-4">
              {/* The identity completion list, from the company's side. */}
              {profile.identity_type === null ? (
                <IdentityGapNotice country={profile.country} canEdit={isStaff} />
              ) : null}
              <CompanyPanel profile={profile} canEdit={isStaff} />
              {/* The company's branches. Flagging one is COMPLIANCE's
                  decision, so it is gated separately from editing. */}
              <GstRegistrationsSection customerId={customerId} canEdit={isStaff} canFlag={canFlagBranches} />
              <AddressesSection customerId={customerId} canEdit={isStaff} />
              <DefaultPaymentTermSection
                customerId={customerId}
                defaultPaymentTermId={profile.default_payment_term_id}
                canEdit={isStaff}
              />
              <CollectionsOwnerSection
                key={profile.collections_owner_user_id ?? 'none'}
                customerId={customerId}
                ownerId={profile.collections_owner_user_id}
                ownerName={profile.collections_owner_name}
              />
              <BankAccountsSection customerId={customerId} />
            </div>
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
                activities={activities}
                activitiesLoading={activityQuery.isLoading}
                activitiesFetching={activityQuery.isFetching}
                activityType={activityType}
                onActivityTypeChange={setActivityType}
                activityPage={activityPage}
                onActivityPageChange={setActivityPage}
                hasNextActivityPage={hasNextActivityPage}
                isStaff={isStaff}
                logRequested={logRequested}
                onLogHandled={() => setLogRequested(false)}
              />
            )}
          </TabsContent>
          <TabsContent value="deals">
            {/* Deals and trade as two views: each counterparty once per view. */}
            <CompanyDealsTab customerId={customerId} isStaff={isStaff} />
          </TabsContent>
          <TabsContent value="documents">
            <DocumentsPanel customerId={customerId} isStaff={isStaff} />
          </TabsContent>
          <TabsContent value="background-check">
            {/* Never rendered for a role without the tab, so its code never loads. */}
            <Suspense fallback={<Skeleton className="h-40 rounded" />}>
              <BackgroundCheckPanel customerId={customerId} isStaff={isStaff} />
            </Suspense>
          </TabsContent>
          <TabsContent value="group">
            {tab === 'group' && (
              <CompanyGroupPanel
                customerId={customerId}
                canEdit={isStaff}
                canSeeSuggestions={canReadCompliance && isStaff}
              />
            )}
          </TabsContent>
          <TabsContent value="history">
            <CompanyHistory customerId={customerId} />
          </TabsContent>
        </div>
        <CompanyRelatedCards
          customerId={customerId}
          contacts={contacts}
          contactsLoading={contactQuery.isLoading}
          canAdd={isStaff}
        />
      </div>
    </Tabs>
  );
}
