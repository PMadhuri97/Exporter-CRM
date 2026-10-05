/**
 * Chips for the company's journey, qualification gauge and marker.
 * Three separate displays for three separate values:
 * none of them is a stage of another.
 */

import { Tag } from '@/components';
import { cn } from '@/lib/cn';

import {
  JOURNEY_CHIP_CLASSES,
  JOURNEY_LABEL,
  JOURNEY_STAGES,
  MARKER_CHIP_CLASSES,
  MARKER_LABEL,
  QUALIFICATION_CHIP_CLASSES,
  QUALIFICATION_LABEL,
} from '../constants';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../types';

/** The journey's progress as ink dots — `●○○` lead, `●●○` prospect, `●●●` customer
 * (frontend-plan §5.2). Progress, not a state, so it is never coloured. */
export function JourneyDots({ journey, className }: { journey: ExporterJourney; className?: string }) {
  const reached = JOURNEY_STAGES.indexOf(journey) + 1;
  return (
    <span aria-hidden className={cn('inline-flex items-center gap-[3px]', className)}>
      {JOURNEY_STAGES.map((stage, index) => (
        <span
          key={stage}
          className={cn(
            'h-[7px] w-[7px] rounded-full border border-ink',
            index < reached ? 'bg-ink' : 'bg-transparent',
          )}
        />
      ))}
    </span>
  );
}

export function JourneyChip({ journey }: { journey: ExporterJourney }) {
  return (
    <Tag
      className={JOURNEY_CHIP_CLASSES[journey]}
      icon={<JourneyDots journey={journey} />}
      data-testid="journey-chip"
    >
      {JOURNEY_LABEL[journey]}
    </Tag>
  );
}

export function QualificationChip({ state }: { state: QualificationState }) {
  return <Tag className={QUALIFICATION_CHIP_CLASSES[state]}>{QUALIFICATION_LABEL[state]}</Tag>;
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
    <Tag className={MARKER_CHIP_CLASSES[marker]} title={reason ?? undefined}>
      {MARKER_LABEL[marker]}
    </Tag>
  );
}
