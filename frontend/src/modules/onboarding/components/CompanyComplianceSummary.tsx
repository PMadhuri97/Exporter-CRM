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
 */

import { ApiError } from '@/lib/api/errors';
import { formatDate } from '@/lib/format';

import { useBackgroundCheck } from '../hooks';
import type { ComplianceCheckState } from '../types';

import { BackgroundCheckGauge } from './BackgroundCheckGauge';

const CHECK_STYLES: Record<ComplianceCheckState, string> = {
  PASSED: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  FAILED: 'bg-red-50 text-red-700 ring-red-600/20',
  PENDING: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  MISSING: 'bg-slate-100 text-slate-600 ring-slate-500/20',
};

const CHECK_LABELS: Record<ComplianceCheckState, string> = {
  PASSED: 'Passed',
  FAILED: 'Failed',
  PENDING: 'Pending',
  MISSING: 'Not checked',
};

function CheckChip({ label, state }: { label: string; state: ComplianceCheckState }) {
  return (
    <span
      data-testid={`compliance-${label.toLowerCase()}`}
      data-state={state}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${CHECK_STYLES[state]}`}
    >
      {label}: {CHECK_LABELS[state]}
    </span>
  );
}

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

  const { value, compliance } = check.data;
  return (
    <div data-testid="company-compliance-summary" className="flex flex-col gap-2">
      <BackgroundCheckGauge value={value} />
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
        <CheckChip label="Sanctions" state={compliance.sanctions} />
        <CheckChip label="AML" state={compliance.aml} />
      </div>
    </div>
  );
}
