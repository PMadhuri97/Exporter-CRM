/**
 * Chips for the company's journey, qualification gauge and marker —
 * **owner: Developer 2**. Three separate displays for three separate values:
 * none of them is a stage of another.
 */

import { Chip } from '@/components';

import {
  JOURNEY_CHIP_CLASSES,
  JOURNEY_LABEL,
  MARKER_CHIP_CLASSES,
  MARKER_LABEL,
  QUALIFICATION_CHIP_CLASSES,
  QUALIFICATION_LABEL,
} from '../constants';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../types';

export function JourneyChip({ journey }: { journey: ExporterJourney }) {
  return (
    <Chip dot className={JOURNEY_CHIP_CLASSES[journey]} data-testid="journey-chip">
      {JOURNEY_LABEL[journey]}
    </Chip>
  );
}

export function QualificationChip({ state }: { state: QualificationState }) {
  return <Chip className={QUALIFICATION_CHIP_CLASSES[state]}>{QUALIFICATION_LABEL[state]}</Chip>;
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
    <Chip className={MARKER_CHIP_CLASSES[marker]} title={reason ?? undefined}>
      {MARKER_LABEL[marker]}
    </Chip>
  );
}
