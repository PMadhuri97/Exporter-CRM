/**
 * Chips for the company's journey, qualification gauge and marker —
 * **owner: Developer 2**. Three separate displays for three separate values:
 * none of them is a stage of another.
 */

import {
  JOURNEY_CHIP_CLASSES,
  JOURNEY_LABEL,
  MARKER_CHIP_CLASSES,
  MARKER_LABEL,
  QUALIFICATION_CHIP_CLASSES,
  QUALIFICATION_LABEL,
} from '../constants';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../types';

const CHIP = 'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium';

export function JourneyChip({ journey }: { journey: ExporterJourney }) {
  return (
    <span className={`${CHIP} ${JOURNEY_CHIP_CLASSES[journey]}`} data-testid="journey-chip">
      {JOURNEY_LABEL[journey]}
    </span>
  );
}

export function QualificationChip({ state }: { state: QualificationState }) {
  return (
    <span className={`${CHIP} ${QUALIFICATION_CHIP_CLASSES[state]}`}>
      {QUALIFICATION_LABEL[state]}
    </span>
  );
}

/** Nothing at all for `NONE`: an unmarked relationship needs no badge. */
export function MarkerBadge({
  marker,
  reason,
}: {
  marker: ExporterMarker;
  reason?: string | null;
}) {
  if (marker === 'NONE') return null;
  return (
    <span className={`${CHIP} ${MARKER_CHIP_CLASSES[marker]}`} title={reason ?? undefined}>
      {MARKER_LABEL[marker]}
    </span>
  );
}
