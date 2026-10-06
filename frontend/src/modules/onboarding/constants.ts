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
