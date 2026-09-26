/**
 * The company detail page — **shell, owner: Developer 2**.
 *
 * This file was 599 lines carrying all four developers' features: the company
 * record, the contact and activity forms, and the verification section, plus
 * the generic layout components they shared. Four people editing one file is a
 * queue, not parallel work (architecture §7.2), so the rendering now lives in
 * one panel per owner:
 *
 *   panels/CompanyPanel.tsx          Developer 2
 *   panels/ConversationPanel.tsx     Developer 3
 *   panels/DealsPanel.tsx            Developer 3
 *   panels/BackgroundCheckPanel.tsx  Developer 4
 *
 * **The queries stayed here, and that was not an oversight.** The obvious
 * split moves `useExporterContacts` and `useExporterActivities` into
 * `ConversationPanel`. It changes behaviour: all three queries are called
 * below, before the early returns, so profile, contacts and activities start
 * together on the first render. A panel that only mounts once the profile has
 * resolved cannot start its fetches until then, turning one round trip into
 * two. `ExporterDetailPage.test.tsx` catches it — it awaits the profile
 * heading and then expects the contacts empty state synchronously.
 *
 * So the split is presentational: the data-fetching and the activity
 * pagination state stay exactly where the page already had them, and the
 * panels render. The cost is that some of Developer 3's state lives in
 * Developer 2's file; moving it needs a deliberate decision about accepting
 * the extra round trip, which is not this phase's to make.
 *
 * The rendered output is unchanged: the panels emit the same markup in the
 * same order, `DealsPanel` renders nothing because deals do not exist yet, and
 * every existing test passes unmodified.
 */

import { ArrowLeft } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { formatDate } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';

import { LifecycleMoveControl, StageChip } from '../components';
import {
  useExporterActivities,
  useExporterContacts,
  useExporterProfileDetail,
} from '../hooks';
import type { ExporterActivityType, ExporterProfileDetail } from '../types';
import { BackgroundCheckPanel } from './panels/BackgroundCheckPanel';
import { CompanyPanel } from './panels/CompanyPanel';
import { ConversationPanel } from './panels/ConversationPanel';
import { DealsPanel } from './panels/DealsPanel';

/** Rows per activity page. Lives here because the shell builds the query
 * params and decides whether a next page exists. */
const ACTIVITY_PAGE_SIZE = 8;

function displayName(profile: ExporterProfileDetail): string {
  return profile.name ?? 'Unnamed exporter';
}

export function ExporterDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const currentUser = useCurrentUser();
  const { data: profile, isLoading, isError } = useExporterProfileDetail(customerId);
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

  if (!customerId) {
    return <p className="text-sm text-status-failed">Exporter id is missing.</p>;
  }

  if (isLoading) {
    return (
      <div className="space-y-5" aria-label="Loading exporter">
        <div className="h-8 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="h-36 animate-pulse rounded-lg border border-border bg-surface" />
        <div className="h-64 animate-pulse rounded-lg border border-border bg-surface" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center shadow-card">
        <p className="font-medium text-ink">Couldn't load this exporter.</p>
        <p className="mt-1 text-sm text-ink-muted">The record may no longer exist or the request failed.</p>
        <Link to="/exporters" className="mt-4 inline-block text-sm font-medium text-brand-600 underline">
          Back to exporters
        </Link>
      </div>
    );
  }

  // DEVELOPER reads the CRM (masked) but writes nothing and cannot load
  // verification results — the backend refuses those with 403.
  const isStaff = currentUser.role !== 'DEVELOPER';
  const name = displayName(profile);
  // The detail response embeds contacts, so the page shows those until the
  // dedicated contacts query resolves — no empty flash on first paint.
  const contacts = contactQuery.data?.contacts ?? profile.contacts;
  const activities = activityQuery.data?.activities ?? [];
  const hasNextActivityPage = activities.length === ACTIVITY_PAGE_SIZE;

  return (
    <div className="space-y-5">
      <div>
        <Link
          to="/exporters"
          className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
        >
          <ArrowLeft size={15} />
          Exporters
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold text-ink">{name}</h1>
              <StageChip status={profile.lifecycle_status} showDetail />
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              Added {formatDate(profile.date_added)}
              {profile.relationship_manager ? ` · Owner: ${profile.relationship_manager}` : ''}
            </p>
          </div>
          <LifecycleMoveControl
            customerId={customerId}
            currentStatus={profile.lifecycle_status}
          />
        </div>
      </div>

      <CompanyPanel profile={profile} />

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

      <DealsPanel customerId={customerId} isStaff={isStaff} />


      <BackgroundCheckPanel customerId={customerId} isStaff={isStaff} />
    </div>
  );
}
