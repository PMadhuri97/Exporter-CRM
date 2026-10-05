/**
 * A deal's stage (frontend-plan §6.5): the path Open > Gathering paperwork > Handed
 * over, with the current step solid blue. Never clickable — moves are the server's
 * `allowed_stage_moves`, offered as buttons in the deal header. A withdrawn deal
 * shows a "Withdrawn" badge instead of the path. `compact` (a deal in a list) is the
 * stage badge alone.
 */

import { Path } from '@/components';

import type { DealStage } from '../../types';
import { DealStageChip } from '../DealStageChip';

const STEPS: { key: Exclude<DealStage, 'WITHDRAWN'>; label: string }[] = [
  { key: 'OPEN', label: 'Open' },
  { key: 'GATHERING_PAPERWORK', label: 'Gathering paperwork' },
  { key: 'HANDED_OVER', label: 'Handed over' },
];

export function DealStagePath({ stage, compact = false }: { stage: DealStage; compact?: boolean }) {
  return (
    <span
      className={compact || stage === 'WITHDRAWN' ? 'inline-flex' : 'flex w-full max-w-2xl min-w-0'}
      data-testid="deal-stage-path"
      data-stage={stage}
    >
      {compact || stage === 'WITHDRAWN' ? (
        <DealStageChip stage={stage} />
      ) : (
        <Path label="Deal stage" steps={STEPS} current={stage} className="w-full" />
      )}
    </span>
  );
}
