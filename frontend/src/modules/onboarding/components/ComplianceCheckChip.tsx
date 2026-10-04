/**
 * One compliance check's state as a chip, and rule B's required checks — **owner:
 * Developer 1** (allocation F1; plan P3-2).
 *
 * The state is served (`PASSED` / `FAILED` / `PENDING` / `MISSING`, IQ-2's meaning of
 * "passed" applied on the server); this only words and colours it.
 */

import type { ComplianceCheckState, RequiredCheck } from '../types';

import { verificationTypeLabel } from './verification-labels';

const CHECK_STYLES: Record<ComplianceCheckState, string> = {
  PASSED: 'bg-positive-tint text-positive',
  FAILED: 'bg-negative-tint text-negative',
  PENDING: 'bg-attention-tint text-attention',
  MISSING: 'bg-sunken text-ink-2',
};

const CHECK_LABELS: Record<ComplianceCheckState, string> = {
  PASSED: 'Passed',
  FAILED: 'Failed',
  PENDING: 'Pending',
  MISSING: 'Not checked',
};

export function ComplianceCheckChip({
  label,
  state,
  testId,
}: {
  label: string;
  state: ComplianceCheckState;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId ?? `compliance-${label.toLowerCase()}`}
      data-state={state}
      className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-caption font-medium ${CHECK_STYLES[state]}`}
    >
      {label}: {CHECK_LABELS[state]}
    </span>
  );
}

/**
 * The checks CLEAR requires (rule B: KYB, AML and sanctions, each passed in the current
 * cycle), as the server lists them — the screen keeps no list of its own. Nothing is
 * rendered when the server lists none.
 */
export function RequiredChecks({ checks }: { checks: RequiredCheck[] }) {
  if (checks.length === 0) return null;
  return (
    <div data-testid="required-checks" className="mt-3">
      <p className="text-caption font-medium text-ink-2">
        Required for Clear (this cycle)
      </p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {checks.map((check) => (
          <ComplianceCheckChip
            key={check.verification_type}
            label={verificationTypeLabel(check.verification_type)}
            state={check.state}
            testId={`required-check-${check.verification_type}`}
          />
        ))}
      </div>
    </div>
  );
}
