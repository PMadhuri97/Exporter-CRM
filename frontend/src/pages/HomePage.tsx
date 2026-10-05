/**
 * The desk (frontend-plan §8.2) — one per role, answering "what is mine to do now?"
 * for the person signed in rather than showing everyone the same numbers.
 *
 * - **RM**: Up next (overdue follow-ups and due check-backs, one queue), the pipeline
 *   as three numerals, and the Re-KYC list to read.
 * - **Compliance**: decisions awaiting your signature first, then everything an RM sees.
 * - **Admin**: the Compliance desk plus one setup section.
 * - **Developer**: "Read-only access. Identifiers are masked." — the pipeline and the
 *   team's queue to read, nothing from compliance.
 *
 * Every section is chosen by capability, so a section is never mounted —
 * and its request never sent — for a role the server would refuse. A section that
 * needs something the backend does not serve yet ("In review", "Deals in paperwork") is not shown at
 * all until the ask lands: hidden, never empty. A user with no CRM capability never
 * reaches this page: the root renders No workspace instead.
 */

import { Link } from 'react-router-dom';

import { buttonClasses } from '@/components';
import { Icon } from '@/design/icons';
import {
  paths,
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
  SetupCard,
  UpNextCard,
} from '@/modules/onboarding';
import { useCan } from '@/platform/access';
import { roleLabel, useCurrentUser } from '@/platform/auth';

function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function HomePage() {
  const user = useCurrentUser();
  const firstName = user.full_name?.split(' ')[0];
  const canWrite = useCan('crm.write');
  const canCreateCompany = useCan('company.create');
  const canSeeQueue = useCan('compliance.queue');
  const canReadCompliance = useCan('compliance.read');
  const canSetUp = useCan('settings.criteria');
  const now = new Date();

  return (
    <div className="max-w-reading space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-secondary text-ink-3">
            {now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
          <h1 className="mt-1 font-display text-display-xl text-ink">
            {greeting(now)}
            {firstName ? `, ${firstName}` : ''}
          </h1>
          <p className="mt-2 text-body text-ink-2">
            {canWrite
              ? `Signed in as ${roleLabel(user.role)}. Here is what is yours to do.`
              : 'Read-only access. Identifiers are masked.'}
          </p>
        </div>
        {canCreateCompany && (
          <Link to={paths.newCompany} className={buttonClasses({ variant: 'primary' })}>
            <Icon.add size={15} aria-hidden />
            Add company
          </Link>
        )}
      </header>

      {canSeeQueue && <ProposalsAwaitingMeCard />}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <UpNextCard userId={String(user.id)} canComplete={canWrite} />
        <div className="space-y-10">
          <PipelineSummaryCard />
          {canReadCompliance && <ReKycDueCard />}
          {canSetUp && <SetupCard />}
        </div>
      </div>
    </div>
  );
}
