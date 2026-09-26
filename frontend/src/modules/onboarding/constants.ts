/**
 * Display vocabulary for the company record — **owner: Developer 2**.
 *
 * Labels and chip colours only. There is deliberately **no transition graph
 * here**: the journey is never moved by hand (a qualification outcome moves
 * it), and the moves a user may make on the marker and on qualification are
 * served by the API with each company (`allowed_marker_moves`,
 * `allowed_outcomes`, `can_record_results`). The ten-status lifecycle and the
 * hand-copied `PERMITTED_LIFECYCLE_TRANSITIONS` that used to live here were
 * retired in L2-04.
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

/**
 * Full, static Tailwind class strings — never built by interpolating a colour
 * name at runtime: Tailwind's JIT only generates classes it can see literally
 * in source.
 */
export const JOURNEY_CHIP_CLASSES: Record<ExporterJourney, string> = {
  LEAD: 'bg-stage-new/10 text-stage-new',
  PROSPECT: 'bg-stage-onboarding/10 text-stage-onboarding',
  CUSTOMER: 'bg-stage-active/10 text-stage-active',
};

export const QUALIFICATION_LABEL: Record<QualificationState, string> = {
  NOT_YET_REVIEWED: 'Not yet reviewed',
  QUALIFIED: 'Qualified',
  NOT_QUALIFIED: 'Not qualified',
};

export const QUALIFICATION_CHIP_CLASSES: Record<QualificationState, string> = {
  NOT_YET_REVIEWED: 'bg-status-pending/10 text-status-pending',
  QUALIFIED: 'bg-status-passed/10 text-status-passed',
  NOT_QUALIFIED: 'bg-status-failed/10 text-status-failed',
};

export const MARKER_LABEL: Record<ExporterMarker, string> = {
  NONE: 'Active relationship',
  PAUSED: 'Paused',
  ENDED: 'Ended',
};

export const MARKER_CHIP_CLASSES: Record<ExporterMarker, string> = {
  NONE: '',
  PAUSED: 'bg-stage-suspended/10 text-stage-suspended',
  ENDED: 'bg-stage-offboarded/15 text-ink-muted',
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
  PASS: 'text-status-passed',
  FAIL: 'text-status-failed',
  UNKNOWN: 'text-ink-muted',
};
