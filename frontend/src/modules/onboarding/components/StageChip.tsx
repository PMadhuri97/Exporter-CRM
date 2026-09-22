import {
  STAGE_GROUP_CHIP_CLASSES,
  STAGE_GROUP_LABEL,
  STATUS_LABEL,
  STATUS_TO_STAGE_GROUP,
} from '../constants';
import type { ExporterLifecycleStatus } from '../types';

interface StageChipProps {
  status: ExporterLifecycleStatus;
  /** Show the exact underlying status alongside the grouped label — the
   * detail view wants both; a dense list row usually wants just the group. */
  showDetail?: boolean;
}

/** The grouped-stage chip, per decision #1 in
 * docs/exporter-crm-frontend-tickets.md — grouping is a display choice, the
 * exact status is never actually lost (see `showDetail`). */
export function StageChip({ status, showDetail = false }: StageChipProps) {
  const group = STATUS_TO_STAGE_GROUP[status];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STAGE_GROUP_CHIP_CLASSES[group]}`}
      >
        {STAGE_GROUP_LABEL[group]}
      </span>
      {showDetail && (
        <span className="text-xs text-ink-faint">{STATUS_LABEL[status]}</span>
      )}
    </span>
  );
}
