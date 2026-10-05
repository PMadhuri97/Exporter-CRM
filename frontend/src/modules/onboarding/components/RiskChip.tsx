/**
 * The CRM risk rating.
 *
 * Four values (decision 6), and `CRITICAL` must look different from the rest
 * (architecture §3.3): it is the one a compliance officer must not skim past.
 * Drawn as frontend-plan §5.2 sets it out, never by colour alone: the words say the
 * level, High adds a negative outline, and Critical is the only solid badge on the
 * screen — white on the negative solid, with a warning icon.
 *
 * "Prohibited" is not a risk value. It is an outcome, recorded as `FLAGGED`.
 */

import type { BackgroundCheckRisk } from '../types';

import { RiskBadge } from './StatusBadge';

export function RiskChip({ risk }: { risk: BackgroundCheckRisk | null | undefined }) {
  if (!risk) return null;
  return <RiskBadge risk={risk} data-testid="risk-chip" />;
}
