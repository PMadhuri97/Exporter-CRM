/**
 * Home — "my work": what is late, who is due a call back, and how the pipeline
 * stands. Replaces the placeholder dashboard.
 *
 * Built from routes that already exist (follow-ups, company search); there is
 * no statistics endpoint, and this page does not pretend there is one. The
 * cards are the onboarding module's, reached through its public facade.
 *
 * Compliance (Developer 1, plans P3-1c, P3-3c): "Proposals awaiting me" for COMPLIANCE
 * and ADMIN — the officers who approve — and "Re-KYC due" for all staff (the RM reads
 * it). Neither is shown to DEVELOPER, whom the background-check routes refuse (D8).
 */

import { Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { buttonClasses, PageHeader } from '@/components';
import {
  CheckBacksDueCard,
  FollowUpsDueCard,
  paths,
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
} from '@/modules/onboarding';
import { isComplianceRole, isStaffRole, roleLabel, useCurrentUser } from '@/platform/auth';

function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function HomePage() {
  const user = useCurrentUser();
  const firstName = user.full_name?.split(' ')[0];

  return (
    <div>
      <PageHeader
        title={`${greeting(new Date())}${firstName ? `, ${firstName}` : ''}`}
        description={`Signed in as ${roleLabel(user.role)}. Here is what needs attention.`}
        actions={
          isStaffRole(user.role) && (
            <Link to={paths.newCompany} className={buttonClasses({ variant: 'primary' })}>
              <Plus size={15} />
              Add company
            </Link>
          )
        }
      />

      <div className="grid gap-5 lg:grid-cols-2">
        {isComplianceRole(user.role) && <ProposalsAwaitingMeCard />}
        {isStaffRole(user.role) && <ReKycDueCard />}
        <FollowUpsDueCard userId={String(user.id)} />
        <CheckBacksDueCard />
        <div className="lg:col-span-2">
          <PipelineSummaryCard />
        </div>
      </div>
    </div>
  );
}
