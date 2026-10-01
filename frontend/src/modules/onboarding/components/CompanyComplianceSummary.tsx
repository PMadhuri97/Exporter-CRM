/**
 * One company's compliance at a glance — **owner: Developer 1** (allocation F1; the
 * full version is task 1.20, which replaces `BuyerChecks`).
 *
 * The props are final: `{ companyId }`. Developer 2 mounts it on the deal page for the
 * seller and, once a deal names one, the buyer company; it works the same for both,
 * because the checks are the company's (decision D).
 *
 * Everything shown is served: the gauge, whether the Clear is still current and until
 * when, and the state of the sanctions and AML checks (`compliance` on the background-
 * check read — `ComplianceFactsReader` on the server). Nothing is derived here, so the
 * rule for "passed" (IQ-2) lives in one place.
 *
 * DEVELOPER is refused the background check (D8). This component makes no role check
 * of its own: a 403 is shown as "not available to your role", never as an error.
 *
 * Tranche 2 (P3-1c, P3-3c): the gauge carries the served "Awaiting approval" and
 * "Re-KYC due" badges.
 */

import { ApiError } from '@/lib/api/errors';
import { formatDate } from '@/lib/format';

import { useBackgroundCheck } from '../hooks';

import { BackgroundCheckGauge } from './BackgroundCheckGauge';
import { ComplianceCheckChip } from './ComplianceCheckChip';

export function CompanyComplianceSummary({ companyId }: { companyId: string }) {
  const check = useBackgroundCheck(companyId);

  if (check.isLoading) {
    return (
      <div data-testid="company-compliance-summary" className="text-sm text-slate-500">
        Loading compliance…
      </div>
    );
  }
  if (check.isError || !check.data) {
    const refused = check.error instanceof ApiError && check.error.status === 403;
    return (
      <div data-testid="company-compliance-summary" className="text-sm text-slate-500">
        {refused ? (
          'Compliance details are not available to your role.'
        ) : (
          <span role="alert" className="text-red-700">
            Compliance details could not be loaded.
          </span>
        )}
      </div>
    );
  }

  const { value, compliance, awaiting_approval: awaitingApproval, rekyc_due: rekycDue } =
    check.data;
  return (
    <div data-testid="company-compliance-summary" className="flex flex-col gap-2">
      <BackgroundCheckGauge
        value={value}
        awaitingApproval={awaitingApproval}
        rekycDue={rekycDue}
      />
      {compliance.is_clear && compliance.clear_expires_at && (
        <p
          data-testid="compliance-expiry"
          className={`text-xs ${compliance.is_clear_current ? 'text-slate-600' : 'font-medium text-red-700'}`}
        >
          {compliance.is_clear_current
            ? `Clear until ${formatDate(compliance.clear_expires_at)}`
            : `Clear expired on ${formatDate(compliance.clear_expires_at)} — Re-KYC due`}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        <ComplianceCheckChip label="Sanctions" state={compliance.sanctions} />
        <ComplianceCheckChip label="AML" state={compliance.aml} />
      </div>
    </div>
  );
}
