/**
 * Display vocabulary for the company record.
 *
 * Labels and chip colours only. There is deliberately **no transition graph
 * here**: the journey is never moved by hand (a qualification outcome moves
 * it), and the moves a user may make on the marker and on qualification are
 * served by the API with each company (`allowed_marker_moves`,
 * `allowed_outcomes`, `can_record_results`). The ten-status lifecycle and the
 * hand-copied `PERMITTED_LIFECYCLE_TRANSITIONS` that used to live here were
 * retired.
 */

import type {
  CriterionResultValue,
  DealStage,
  ExporterJourney,
  ExporterMarker,
  QualificationState,
} from './types';

/** The journey's three stages, in order — the pipeline's columns. */
export const JOURNEY_STAGES: readonly ExporterJourney[] = ['LEAD', 'PROSPECT', 'CUSTOMER'];

export const JOURNEY_LABEL: Record<ExporterJourney, string> = {
  LEAD: 'Lead',
  PROSPECT: 'Prospect',
  CUSTOMER: 'Customer',
};

export const QUALIFICATION_LABEL: Record<QualificationState, string> = {
  NOT_YET_REVIEWED: 'Not yet reviewed',
  QUALIFIED: 'Qualified',
  NOT_QUALIFIED: 'Not qualified',
};

export const MARKER_LABEL: Record<ExporterMarker, string> = {
  NONE: 'Active relationship',
  PAUSED: 'Paused',
  ENDED: 'Ended',
};

/** The verb for moving the marker to a value, for buttons. */
export const MARKER_ACTION_LABEL: Record<ExporterMarker, string> = {
  NONE: 'Resume relationship',
  PAUSED: 'Pause relationship',
  ENDED: 'End relationship',
};

export const RESULT_LABEL: Record<CriterionResultValue, string> = {
  PASS: 'Pass',
  FAIL: 'Fail',
  UNKNOWN: 'Unknown',
};

export const RESULT_CLASSES: Record<CriterionResultValue, string> = {
  PASS: 'text-positive',
  FAIL: 'text-negative',
  UNKNOWN: 'text-ink-2',
};

// ── Deals ──────────────────────────────────────────────────────

/** A deal's stages, in the order a deal moves through them. */
export const DEAL_STAGES: readonly DealStage[] = [
  'OPEN',
  'GATHERING_PAPERWORK',
  'HANDED_OVER',
  'WITHDRAWN',
];

export const DEAL_STAGE_LABEL: Record<DealStage, string> = {
  OPEN: 'Open',
  GATHERING_PAPERWORK: 'Gathering paperwork',
  HANDED_OVER: 'Handed over',
  WITHDRAWN: 'Withdrawn',
};

/** The `corridor` filter value for deals whose corridor is not known yet. */
export const UNKNOWN_CORRIDOR = 'UNKNOWN';

let countryNames: Intl.DisplayNames | null | undefined;

/** "Netherlands" for `NL`; the code itself where the browser has no name for it. */
export function countryName(code: string): string {
  if (countryNames === undefined) {
    try {
      countryNames = new Intl.DisplayNames(['en'], { type: 'region' });
    } catch {
      countryNames = null;
    }
  }
  return countryNames?.of(code) ?? code;
}

/** `IN-NL` as "IN → NL": seller's country first. */
export function corridorLabel(corridor: string): string {
  return corridor.replace('-', ' → ');
}

/** `IN-NL` as "India to Netherlands", for a tooltip or a screen reader. */
export function corridorDescription(corridor: string): string {
  const [from, to] = corridor.split('-');
  return from && to ? `${countryName(from)} to ${countryName(to)}` : corridor;
}
