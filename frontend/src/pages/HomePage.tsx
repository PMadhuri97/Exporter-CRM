/**
 * Home (frontend-plan §8.2) — one per role, answering "what is mine to do now?" as a
 * grid of work cards, two columns from 1280px.
 *
 * - **RM**: my follow-ups (with *Mark done*), check-backs due, information a reviewer
 *   is waiting for on my companies, the pipeline counts, decisions on my companies, the
 *   Re-KYC list to read, and recent companies.
 * - **Compliance**: items to approve first, then everything an RM sees.
 * - **Admin**: the Compliance home plus a setup card.
 * - **Developer**: "Read-only access. Identifiers are masked." — the pipeline and the
 *   team's follow-ups to read, nothing from compliance.
 *
 * Every card is chosen by capability, so a card is never mounted — and its request
 * never sent — for a role the server would refuse. A card that needs something the
 * backend does not serve yet ("In review", "Deals in paperwork") is not shown at all
 * until the ask lands: hidden, never empty. A user with no CRM capability never
 * reaches this page: the root renders No workspace instead.
 */

import { Link } from 'react-router-dom';

import { Card, EmptyLine } from '@/components';
import {
  CheckBackCard,
  InfoRequestedCard,
  MyFollowUpsCard,
  paths,
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  RecentDecisionsCard,
  ReKycDueCard,
  SetupCard,
} from '@/modules/onboarding';
import { useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';
import { readRecentCompanies } from '@/platform/shell';

/** The last companies this viewer opened, kept per viewer in this browser. */
function RecentCompaniesCard({ userId }: { userId: string }) {
  const recent = readRecentCompanies(userId).slice(0, 5);
  return (
    <Card title="Recent companies">
      {recent.length === 0 ? (
        <EmptyLine className="py-0">Companies you open appear here.</EmptyLine>
      ) : (
        <ul className="-my-1.5 divide-y divide-line">
          {recent.map((company) => (
            <li key={company.id} className="py-1.5">
              <Link
                to={paths.company(company.id)}
                className="text-body font-semibold text-accent underline-offset-2 hover:underline"
              >
                {company.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function HomePage() {
  const user = useCurrentUser();
  const userId = String(user.id);
  const canWrite = useCan('crm.write');
  const canSeeQueue = useCan('compliance.queue');
  const canReadCompliance = useCan('compliance.read');
  const canSetUp = useCan('settings.criteria');
  const isRm = useCan('rm.self');

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-title font-semibold text-ink">Home</h1>
      </header>
      {!canWrite && (
        <p className="rounded border border-line bg-surface px-4 py-2.5 text-body text-ink-2">
          Read-only access. Identifiers are masked.
        </p>
      )}

      {canSeeQueue && <ProposalsAwaitingMeCard />}

      <div className="grid gap-4 xl:grid-cols-2 xl:items-start">
        <div className="flex flex-col gap-4">
          <MyFollowUpsCard userId={userId} canComplete={canWrite} />
          <CheckBackCard />
          {isRm && <InfoRequestedCard />}
        </div>
        <div className="flex flex-col gap-4">
          <PipelineSummaryCard />
          {canReadCompliance && <RecentDecisionsCard />}
          {canReadCompliance && <ReKycDueCard />}
          {canSetUp && <SetupCard />}
          <RecentCompaniesCard userId={userId} />
        </div>
      </div>
    </div>
  );
}
