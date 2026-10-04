/**
 * The CRM risk rating — **owner: Developer 4A** (L4-08).
 *
 * Four values (decision 6), and `CRITICAL` must look different from the rest
 * (architecture §3.3): it is the one a compliance officer must not skim past.
 * Drawn as frontend-plan §5.2 sets it out: a four-bar meter so the level never
 * depends on colour alone, tinted for LOW / MEDIUM / HIGH, and for CRITICAL the
 * only filled mark on the screen — white on solid negative, a 45° hatch and a
 * leading "!".
 *
 * "Prohibited" is not a risk value. It is an outcome, recorded as `FLAGGED`.
 */

import { cn } from '@/lib/cn';

import type { BackgroundCheckRisk } from '../types';

const LEVEL: Record<BackgroundCheckRisk, number> = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 };

const STYLES: Record<BackgroundCheckRisk, string> = {
  LOW: 'bg-positive-tint text-positive',
  MEDIUM: 'bg-attention-tint text-attention',
  HIGH: 'bg-negative-tint text-negative ring-1 ring-inset ring-negative/50',
  // The one filled mark: filled, hatched and bold.
  CRITICAL: 'hatch bg-negative-solid font-bold text-white',
};

const LABELS: Record<BackgroundCheckRisk, string> = {
  LOW: 'Low risk',
  MEDIUM: 'Medium risk',
  HIGH: 'High risk',
  CRITICAL: 'Critical risk',
};

/** Four rising bars, `level` of them filled — the meter glyph of §5.2. */
export function RiskMeter({ level, className }: { level: number; className?: string }) {
  return (
    <span aria-hidden className={cn('inline-flex h-2.5 items-end gap-px', className)}>
      {[1, 2, 3, 4].map((bar) => (
        <span
          key={bar}
          className={cn('w-[3px] rounded-[1px] bg-current', bar > level && 'opacity-25')}
          style={{ height: `${bar * 25}%` }}
        />
      ))}
    </span>
  );
}

export function RiskChip({ risk }: { risk: BackgroundCheckRisk | null | undefined }) {
  if (!risk) return null;
  return (
    <span
      data-testid="risk-chip"
      data-risk={risk}
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-caption font-medium',
        STYLES[risk],
      )}
    >
      {risk === 'CRITICAL' && <span aria-hidden>!</span>}
      <RiskMeter level={LEVEL[risk]} />
      {LABELS[risk]}
    </span>
  );
}
