/**
 * A deal's stage — **owner: Developer 3B**.
 *
 * The status language applied to a deal: neutral while it is open, blue while
 * paperwork is being gathered, green once handed over, muted once withdrawn —
 * the same grammar every other chip uses, so a reader learns it once.
 */

import { Chip, type ChipTone } from '@/components';

import type { DealStage } from '../types';

const STAGE_LOOK: Record<DealStage, { label: string; tone: ChipTone; className?: string }> = {
  OPEN: { label: 'Open', tone: 'neutral' },
  GATHERING_PAPERWORK: { label: 'Gathering paperwork', tone: 'info' },
  HANDED_OVER: { label: 'Handed over', tone: 'success' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'neutral', className: 'text-ink-faint' },
};

export function DealStageChip({ stage }: { stage: DealStage }) {
  const look = STAGE_LOOK[stage];
  return (
    <Chip dot tone={look.tone} className={look.className}>
      {look.label}
    </Chip>
  );
}
