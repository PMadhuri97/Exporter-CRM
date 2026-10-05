/**
 * A deal's stage.
 *
 * The status language applied to a deal: neutral while it is open, blue while
 * paperwork is being gathered, green once handed over, muted once withdrawn —
 * the same grammar every other chip uses, so a reader learns it once.
 */

import { Tag, type TagTone } from '@/components';

import type { DealStage } from '../types';

const STAGE_LOOK: Record<DealStage, { label: string; tone: TagTone; className?: string }> = {
  OPEN: { label: 'Open', tone: 'idle' },
  GATHERING_PAPERWORK: { label: 'Gathering paperwork', tone: 'progress' },
  HANDED_OVER: { label: 'Handed over', tone: 'positive' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'idle', className: 'text-ink-3' },
};

export function DealStageChip({ stage }: { stage: DealStage }) {
  const look = STAGE_LOOK[stage];
  return (
    <Tag dot tone={look.tone} className={look.className}>
      {look.label}
    </Tag>
  );
}
