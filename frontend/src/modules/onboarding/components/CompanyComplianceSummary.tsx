/**
 * One company's compliance at a glance — **owner: Developer 1** (allocation F1; the
 * full version is task 1.20).
 *
 * The props are final: `{ companyId }`. It renders the same for any company — a seller,
 * a buyer-only company or one that is both — because the checks are the company's
 * (decision D, plan P4-5): one set of checks per company, wherever it appears. Developer
 * 2 mounts it on the deal page for the seller and for the buyer company (task 2.4).
 *
 * What it shows, all served by the background-check read (nothing is derived here, so
 * the rule for "passed" — IQ-2 — and for "current" live in one place):
 *
 * - the gauge, with the "Awaiting approval" (maker-checker) and "Re-KYC due" badges;
 * - whether the Clear is current and until when, or when it expired;
 * - the latest sanctions and AML results in the current cycle (`PASSED` / `FAILED` /
 *   `PENDING` / not checked) — what the handover guard reads (BQ-3, BQ-4);
 * - a link to the company's own background-check panel, where everything else is.
 *
 * It is the one compliance summary in the app. On a deal whose buyer is still a legacy
 * `deal_buyer` row (no buyer company yet), `BuyerChecks` remains the place that buyer's
 * own checks are recorded until the deal-buyer migration and its retirement (P4-6,
 * P4-10); it is a recording list, not a second summary.
 *
 * DEVELOPER is refused the background check (D8). This component makes no role check of
 * its own: a 403 is shown as "not available to your role", never as an error.
 */

import { Link } from 'react-router-dom';

import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { formatDate } from '@/lib/format';

import { useBackgroundCheck } from '../hooks';
import { paths } from '../paths';

import { BackgroundCheckGauge } from './BackgroundCheckGauge';
import { ComplianceCheckChip } from './ComplianceCheckChip';

export function CompanyComplianceSummary({ companyId }: { companyId: string }) {
  const check = useBackgroundCheck(companyId);

  if (check.isLoading) {
    return (
      <div data-testid="company-compliance-summary" className="text-sm text-ink-3">
        Loading compliance…
      </div>
    );
  }
  if (check.isError || !check.data) {
    const refused = check.error instanceof ApiError && check.error.status === 403;
    return (
      <div data-testid="company-compliance-summary" className="text-sm text-ink-3">
        {refused ? (
          'Compliance details are not available to your role.'
        ) : (
          <span role="alert" className="text-negative">
            Compliance details could not be loaded.
          </span>
        )}
      </div>
    );
  }

  const {
    value,
    compliance,
    awaiting_approval: awaitingApproval,
    rekyc_due: rekycDue,
  } = check.data;
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
          className={`text-xs ${compliance.is_clear_current ? 'text-ink-2' : 'font-medium text-negative'}`}
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
      <Link
        to={paths.company(companyId, 'background-check')}
        data-testid="compliance-panel-link"
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-ink hover:underline"
      >
        Open the background check
        <Icon.forward size={12} />
      </Link>
    </div>
  );
}
