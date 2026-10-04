/**
 * How an invoice was settled — **owner: Developer 3** (task 3.22, plan P5-7).
 *
 * The same chip grammar every other status uses, so a reader learns it once: green
 * for settled, amber while something is outstanding, red for a dispute, neutral for
 * what nobody knows.
 *
 * Two distinctions the wording has to keep, because the screen is the only place
 * they are visible:
 *
 * - **`UNKNOWN` is an answer, not a gap.** Somebody looked and could not say. An
 *   invoice with *no* outcome at all renders no chip and reads "No outcome recorded"
 *   instead, which is what `NoOutcomeChip` is for.
 * - **`CLAIMED` is not `PROVEN`.** An outcome nobody has evidence for still counts
 *   as something the exporter told us, and it is shown — with the proof status beside
 *   it, never folded into the payment status. "Paid" and "Paid, claimed" must not
 *   look the same, because a lending decision would read them differently.
 */

import { Chip, type ChipTone } from '@/components';

import type { TradePaymentStatus, TradeProofStatus } from '../types';

const PAYMENT_LOOK: Record<
  TradePaymentStatus,
  { label: string; tone: ChipTone; className?: string }
> = {
  PAID: { label: 'Paid', tone: 'success' },
  PARTIAL: { label: 'Part paid', tone: 'warning' },
  UNPAID: { label: 'Unpaid', tone: 'warning' },
  DISPUTED: { label: 'Disputed', tone: 'danger' },
  UNKNOWN: { label: 'Not known', tone: 'neutral', className: 'text-ink-faint' },
};

/** `PROVEN` is deliberately silent: proof is the expectation, so saying so on every
 * row would make the rows that lack it harder to spot, not easier. */
const PROOF_LABEL: Record<TradeProofStatus, string | null> = {
  PROVEN: null,
  CLAIMED: 'Claimed',
};

export interface TradeOutcomeChipProps {
  paymentStatus: TradePaymentStatus;
  proofStatus: TradeProofStatus;
}

export function TradeOutcomeChip({ paymentStatus, proofStatus }: TradeOutcomeChipProps) {
  const look = PAYMENT_LOOK[paymentStatus];
  const proof = PROOF_LABEL[proofStatus];
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Chip dot tone={look.tone} className={look.className}>
        {look.label}
      </Chip>
      {proof && (
        <Chip tone="neutral" className="text-ink-faint" title="Nobody has shown proof of this yet">
          {proof}
        </Chip>
      )}
    </span>
  );
}

/** An invoice nobody has recorded an outcome for. Not `UNKNOWN`: nobody has looked. */
export function NoOutcomeChip() {
  return (
    <Chip tone="neutral" className="text-ink-faint">
      No outcome recorded
    </Chip>
  );
}
