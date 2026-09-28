/**
 * The CRM risk rating — **owner: Developer 4A** (L4-08).
 *
 * Four values (decision 6), and `CRITICAL` must look different from the rest
 * (architecture §3.3): it is the one a compliance officer must not skim past, so it
 * is the only one with a filled background and a border.
 *
 * "Prohibited" is not a risk value. It is an outcome, recorded as `FLAGGED`.
 */

import type { BackgroundCheckRisk } from '../types';

const STYLES: Record<BackgroundCheckRisk, string> = {
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  MEDIUM: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  HIGH: 'bg-orange-50 text-orange-800 ring-orange-600/30',
  // Deliberately louder than the rest: filled, bordered, and bold.
  CRITICAL: 'bg-red-600 text-white ring-red-700 font-bold',
};

const LABELS: Record<BackgroundCheckRisk, string> = {
  LOW: 'Low risk',
  MEDIUM: 'Medium risk',
  HIGH: 'High risk',
  CRITICAL: 'Critical risk',
};

export function RiskChip({ risk }: { risk: BackgroundCheckRisk | null | undefined }) {
  if (!risk) return null;
  return (
    <span
      data-testid="risk-chip"
      data-risk={risk}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[risk]}`}
    >
      {LABELS[risk]}
    </span>
  );
}
