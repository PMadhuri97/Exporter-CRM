/**
 * The company dossier — **shell, owner: Developer 2**, drawn as frontend-plan §8.5.
 *
 * A serif header (the name, one line of facts, the identifiers, the marker menu the
 * server allows), the **hero Standing** — journey, qualification, conversation and,
 * for a role that may read it, the background check, side by side — and the
 * chapters. The header compresses to a slim bar once it scrolls away. Chapters are a
 * rail on a wide screen and tabs below that; the keys and `?tab=` are unchanged, so
 * every old link lands where it did.
 *
 *   Profile            panels/CompanyPanel.tsx          Developer 2
 *   Qualification      panels/QualificationPanel.tsx    Developer 2
 *   Conversation       panels/ConversationPanel.tsx     Developer 3A
 *   Deals & trade      panels/DealsPanel.tsx and trade  Developer 3B / 3
 *   Documents          panels/DocumentsPanel.tsx        Developer 3B
 *   Background check   panels/BackgroundCheckPanel.tsx  Developer 4 / 1
 *   Ledger             components/HistoryTimeline.tsx   Developer 1
 *
 * **Now**, at the top of the profile, lists at most three next steps, each built only
 * from what the server served for this company (`can_open_deal`, the background
 * check's `allowed_moves`, `open_proposal.allowed_actions`, `rekyc_due`, the
 * conversation's check-back) — nothing is worked out from rules held here.
 *
 * The contact and activity queries stay here, not in the Conversation chapter: they
 * start with the profile, so opening that chapter shows them at once.
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  Button,
  ErrorState,
  Panel,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useSearchParamState,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';
import { companyNameTransition } from '@/lib/viewTransition';
import { useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';
import { Identifier } from '@/platform/mask';
import { rememberCompany, useCommandActions, useCrumbs, usePageShortcuts } from '@/platform/shell';

import {
  CompanyDealsList,
  CompanyHistory,
  CompanyTradePanel,
  GstRegistrationsSection,
  IdentityGapNotice,
  MarkerBadge,
  MarkerControl,
  NotInPipelineNotice,
  Standing,
  type StandingSegment,
} from '../components';
import { cycleKindLabel } from '../components/background-check-labels';
import {
  useBackgroundCheck,
  useBringIntoPipeline,
  useCompanyDeals,
  useExporterActivities,
  useExporterContacts,
  useExporterConversation,
  useExporterProfileDetail,
} from '../hooks';
import { COMPANY_TABS, paths, type CompanyTab } from '../paths';
import type { ExporterActivityType, ExporterProfileDetail } from '../types';

import { CompanyPanel } from './panels/CompanyPanel';
import { ConversationPanel } from './panels/ConversationPanel';
import { DealsPanel } from './panels/DealsPanel';
import { DocumentsPanel } from './panels/DocumentsPanel';
import { QualificationPanel } from './panels/QualificationPanel';

// The compliance chapter is its own chunk (G7): a role without the tab never loads it.
const BackgroundCheckPanel = lazy(() =>
  import('./panels/BackgroundCheckPanel').then((m) => ({ default: m.BackgroundCheckPanel })),
);

/** Rows per activity page. Lives here because the shell builds the query
 * params and decides whether a next page exists. */
const ACTIVITY_PAGE_SIZE = 8;

const TAB_LABEL: Record<CompanyTab, string> = {
  overview: 'Profile',
  qualification: 'Qualification',
  conversation: 'Conversation',
  deals: 'Deals & trade',
  documents: 'Documents',
  'background-check': 'Background check',
  history: 'Ledger',
};

/** Which chapter a hero segment opens. */
const SEGMENT_TAB: Record<StandingSegment, CompanyTab> = {
  journey: 'history',
  qualification: 'qualification',
  conversation: 'conversation',
  'background-check': 'background-check',
};

function displayName(profile: ExporterProfileDetail): string {
  return profile.name ?? 'Unnamed company';
}

/** Today, as the `YYYY-MM-DD` the server's dates use. */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

interface NowItem {
  key: string;
  text: ReactNode;
  verb: string;
  open: CompanyTab;
}

/** True once `ref`'s element has scrolled out of view (and IntersectionObserver exists). */
function useScrolledPast(ref: React.RefObject<HTMLElement>): boolean {
  const [past, setPast] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setPast(!entry!.isIntersecting), {
      threshold: 0,
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return past;
}

export function ExporterDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  // DEVELOPER reads the CRM (masked) but writes nothing and cannot load
  // verification results — the backend refuses those with 403 (D8) — so it gets no
  // Background check chapter at all, and no request for one.
  const isStaff = useCan('crm.write');
  const canReadCompliance = useCan('compliance.read');
  // Flagging a branch stops trade through it, so it is a compliance decision and not
  // a sales one (plan P6-5). The server refuses it for OPERATIONS; the screen does not
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
  // Only for a role the background-check routes admit (D8): no request otherwise.
  const check = useBackgroundCheck(canReadCompliance ? customerId : undefined);
  // Hooks run before the missing-id guard below; the mutation is only offered after it.
  const bringIntoPipeline = useBringIntoPipeline(customerId ?? '');
  const header = useRef<HTMLDivElement>(null);
  const compact = useScrolledPast(header);

  // The shell (R-33 Phase 2): the trail, ⌘K's "Recent", and its chapters as commands.
  const userId = String(useCurrentUser().id);
  const name = profile ? displayName(profile) : null;
  useCrumbs([{ label: 'Companies', to: paths.companies }, ...(name ? [{ label: name }] : [])]);
  useEffect(() => {
    if (customerId && name) rememberCompany(userId, { id: customerId, name });
  }, [customerId, name, userId]);
  // `l` logs an activity (staff, §7.5): it opens the Conversation chapter and its
  // composer, the same one the Thread's button opens.
  const [logRequested, setLogRequested] = useState(false);
  const logActivity = () => {
    setTab('conversation');
    setLogRequested(true);
  };
  useCommandActions(
    profile
      ? [
          ...(isStaff
            ? [{ id: 'log-activity', label: 'Log an activity', shortcut: 'l', keywords: ['call', 'note', 'meeting'], run: logActivity }]
            : []),
          ...tabs
            .filter((value) => value !== tab)
            .map((value) => ({
              id: `chapter-${value}`,
              label: `Go to ${TAB_LABEL[value]}`,
              run: () => setTab(value),
            })),
        ]
      : [],
  );
  usePageShortcuts(profile && isStaff ? [{ key: 'l', label: 'Log an activity', run: logActivity }] : []);

  if (!customerId) {
    return <p className="text-body text-negative">Company id is missing.</p>;
  }

  if (isLoading) {
    return (
      <div className="max-w-reading space-y-5" aria-label="Loading company">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-4 w-96 max-w-full" />
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
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
  const activities = activityQuery.data?.activities ?? [];
  const hasNextActivityPage = activities.length === ACTIVITY_PAGE_SIZE;
  const dealCount = dealsQuery.data?.total;
  // A company that exists only because it was somebody's buyer: its journey and both
  // gauges do not apply, and the server refuses them (plan P4-2, task 3.9).
  const notInPipeline = profile.pipeline_status === 'NOT_IN_PIPELINE';
  const gauge = conversation.data;
  const standing = check.data;
  const cycle = standing?.current_cycle;
  const clearUntil =
    standing?.compliance?.is_clear && standing.compliance.clear_expires_at
      ? standing.compliance.clear_expires_at
      : null;

  // Now: only what the server served for this company, at most three.
  const now: NowItem[] = [];
  if (standing?.open_proposal?.allowed_actions?.some((action) => action !== 'WITHDRAW')) {
    now.push({
      key: 'proposal',
      text: 'A background-check decision is waiting for your signature.',
      verb: 'Review it',
      open: 'background-check',
    });
  }
  if (standing?.rekyc_due) {
    now.push({ key: 'rekyc', text: 'Re-KYC is due on this company.', verb: 'Open the check', open: 'background-check' });
  }
  if (standing?.value === 'NOT_STARTED' && (standing.allowed_moves ?? []).length > 0) {
    now.push({ key: 'start', text: 'No background check has been started.', verb: 'Start it', open: 'background-check' });
  }
  if (gauge?.conversation === 'READY_NOW' && dealsQuery.data?.can_open_deal) {
    now.push({ key: 'deal', text: 'Ready now, and no open deal.', verb: 'Open a deal', open: 'deals' });
  }
  if (gauge?.conversation === 'NOT_NOW' && gauge.check_back_on && gauge.check_back_on <= today()) {
    now.push({
      key: 'checkback',
      text: `Due a check-back (since ${formatDate(gauge.check_back_on)}).`,
      verb: 'Open the conversation',
      open: 'conversation',
    });
  }

  const details: Partial<Record<StandingSegment, ReactNode>> = {
    journey: `added ${formatDate(profile.date_added)}`,
    'background-check': [
      cycle ? `cycle ${cycle.number} · ${cycleKindLabel(cycle.kind)}` : null,
      clearUntil ? `until ${formatDate(clearUntil)}` : null,
    ]
      .filter(Boolean)
      .join(' · ') || undefined,
  };

  const facts = [
    profile.industry,
    profile.country,
    profile.year_established ? `since ${profile.year_established}` : null,
    profile.relationship_manager ? `RM ${profile.relationship_manager}` : null,
  ].filter(Boolean);

  return (
    // One `Tabs` root around the header and the chapters, so the triggers and the
    // contents share its ids (the tab <-> tabpanel wiring).
    <Tabs value={tab} onValueChange={(next) => setTab(next as CompanyTab)}>
      <div className="max-w-reading">
        {/* The slim bar that replaces the header once it has scrolled away. */}
        {compact && (
          <div
            aria-hidden
            className="sticky -top-6 z-20 -mx-4 mb-2 flex h-11 items-center gap-4 border-b border-line bg-paper px-4 sm:-mx-8 sm:px-8"
          >
            <span className="truncate font-display text-[18px] text-ink">{displayName(profile)}</span>
            <Standing
              size="card"
              journey={profile.journey}
              qualification={profile.qualification}
              conversation={gauge?.conversation}
              backgroundCheck={standing?.value}
              awaitingApproval={standing?.awaiting_approval}
              rekycDue={standing?.rekyc_due}
              marker={profile.marker}
              outsidePipeline={notInPipeline}
            />
          </div>
        )}

        <header ref={header} className="mb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h1
                  data-company-title
                  className="font-display text-display-lg text-ink [overflow-wrap:anywhere]"
                  style={{ viewTransitionName: companyNameTransition(customerId) }}
                >
                  {displayName(profile)}
                </h1>
                <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
              </div>
              <p className="mt-1 text-body text-ink-2">
                {facts.join(' · ') || `Added ${formatDate(profile.date_added)}`}
                {profile.marker_reason ? ` · ${profile.marker_reason}` : ''}
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              {/* Only the marker moves the server listed for this user; none, nothing. */}
              <MarkerControl customerId={customerId} moves={profile.allowed_marker_moves ?? []} />
              <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-secondary text-ink-3">
                <div className="flex items-center gap-1.5">
                  <dt>PAN</dt>
                  <dd>
                    <Identifier kind="PAN" value={profile.pan} />
                  </dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt>GSTIN</dt>
                  <dd className="flex items-center gap-1">
                    <Identifier kind="GSTIN" value={profile.gstins[0] ?? null} />
                    {profile.gstins.length > 1 && <span>+{profile.gstins.length - 1}</span>}
                  </dd>
                </div>
              </dl>
            </div>
          </div>

          <Standing
            size="hero"
            className="mt-5"
            journey={profile.journey}
            outsidePipeline={notInPipeline}
            qualification={profile.qualification}
            conversation={gauge?.conversation}
            checkBackOn={gauge?.check_back_on}
            backgroundCheck={standing?.value}
            risk={standing?.risk_rating}
            awaitingApproval={standing?.awaiting_approval}
            rekycDue={standing?.rekyc_due}
            details={details}
            onOpen={(segment) => setTab(SEGMENT_TAB[segment])}
          />
        </header>
      </div>

      <div className="grid gap-6 xl:grid-cols-[12rem_minmax(0,1fr)]">
        <TabsList
          aria-label="Company chapters"
          className="xl:sticky xl:top-0 xl:h-fit xl:flex-col xl:gap-0.5 xl:overflow-visible xl:border-b-0"
        >
          {tabs.map((value) => (
            <TabsTrigger
              key={value}
              value={value}
              className="xl:-mb-0 xl:justify-between xl:rounded-md xl:border-b-0 xl:border-l-2 xl:py-2 xl:data-[state=active]:bg-surface"
            >
              {TAB_LABEL[value]}
              {value === 'deals' && dealCount !== undefined && dealCount > 0 && (
                <span className="text-caption tabular-nums text-ink-3">{dealCount}</span>
              )}
              {value === 'background-check' && (standing?.awaiting_approval || standing?.rekyc_due) && (
                <span aria-label="needs attention" className="h-1.5 w-1.5 rounded-full bg-attention-solid" />
              )}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="min-w-0 max-w-reading">
          <TabsContent value="overview">
            <div className="flex flex-col gap-6">
              <section aria-label="Now" className="rounded-xl border border-line bg-surface px-4 py-3">
                <h2 className="text-caption text-ink-3">Now</h2>
                {now.length === 0 ? (
                  <p className="mt-1 text-body text-ink-2">Nothing waiting on you here.</p>
                ) : (
                  <ul className="mt-1 divide-y divide-line">
                    {now.slice(0, 3).map((item) => (
                      <li key={item.key} className="flex flex-wrap items-center justify-between gap-3 py-2">
                        <span className="flex items-center gap-2 text-body text-ink">
                          <Icon.forward size={15} className="text-ink-3" aria-hidden />
                          {item.text}
                        </span>
                        <Button size="sm" variant="secondary" onClick={() => setTab(item.open)}>
                          {item.verb}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              {/* IQ-7's completion list, from the company's side (R-28). */}
              {profile.identity_type === null ? (
                <IdentityGapNotice country={profile.country} canEdit={isStaff} />
              ) : null}
              <CompanyPanel profile={profile} canEdit={isStaff} />
              {/* The company's branches (task 3.13). Flagging one is COMPLIANCE's
                  decision, so it is gated separately from editing. */}
              <GstRegistrationsSection customerId={customerId} canEdit={isStaff} canFlag={canFlagBranches} />
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
                logRequested={logRequested}
                onLogHandled={() => setLogRequested(false)}
              />
            )}
          </TabsContent>
          <TabsContent value="deals">
            {/* Both sides of this company's trade (task 3.9): selling, where a deal is
                opened, and buying, a plain list. Then what came of it, invoice by
                invoice — never totalled; amounts stay in their own currency (IQ-4). */}
            <div className="flex flex-col gap-8">
              <DealsPanel customerId={customerId} isStaff={isStaff} />
              <Panel
                title="Buying"
                description="Deals where this company is the buyer. A company can be a buyer on one deal and a seller on another."
              >
                <CompanyDealsList companyId={customerId} as="buyer" />
              </Panel>
              <Panel
                title="Trade — sold to"
                description="Who this company has invoiced, and what became of each invoice. Nothing here is totalled: amounts stay in the currency they were invoiced in."
              >
                <CompanyTradePanel companyId={customerId} as="seller" canRecord={isStaff} />
              </Panel>
              <Panel
                title="Trade — bought from"
                description="Who has invoiced this company. The same pair in the other direction is a different relationship, with different invoices."
              >
                <CompanyTradePanel companyId={customerId} as="buyer" canRecord={isStaff} />
              </Panel>
            </div>
          </TabsContent>
          <TabsContent value="documents">
            <DocumentsPanel customerId={customerId} isStaff={isStaff} />
          </TabsContent>
          <TabsContent value="background-check">
            {/* Never rendered for a role without the chapter, so its code never loads (G7). */}
            <Suspense fallback={<Skeleton className="h-40 rounded-xl" />}>
              <BackgroundCheckPanel customerId={customerId} isStaff={isStaff} />
            </Suspense>
          </TabsContent>
          <TabsContent value="history">
            <CompanyHistory customerId={customerId} />
          </TabsContent>
        </div>
      </div>
    </Tabs>
  );
}
