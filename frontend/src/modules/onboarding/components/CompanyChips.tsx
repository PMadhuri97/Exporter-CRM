/**
 * The company's qualification and marker as badges, under their older names: the
 * same worded badges as everywhere else (`StatusBadge.tsx`). Separate displays for
 * separate values — none of them is a stage of another.
 */

import type { ExporterMarker, QualificationState } from '../types';

import { MarkerStatusBadge, QualificationBadge } from './StatusBadge';

export function QualificationChip({ state }: { state: QualificationState }) {
  return <QualificationBadge state={state} />;
}

/** Nothing at all for `NONE`: an unmarked relationship needs no badge. */
export function MarkerBadge({ marker, reason }: { marker: ExporterMarker; reason?: string | null }) {
  return <MarkerStatusBadge marker={marker} reason={reason} />;
}
