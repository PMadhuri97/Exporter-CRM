import type { ExporterLifecycleStatus } from './types';

/**
 * Visual grouping of the backend's 10-state `ExporterLifecycleStatus`, per
 * `docs/exporter-crm-frontend-tickets.md` decision #1: the backend states
 * are NOT simplified (each carries real workflow meaning — which check is
 * outstanding) — only the *display* groups them into fewer columns/tabs.
 * `SUSPENDED`/`OFFBOARDED` are deliberately not a pipeline stage (exits, not
 * a step forward) — surfaced via the "Inactive" filter, never a kanban
 * column once EXP-F10 exists.
 */
export const STAGE_GROUPS = [
  'NEW',
  'CONTACTED',
  'ONBOARDING',
  'APPROVED',
  'ACTIVE',
  'INACTIVE',
] as const;

export type StageGroup = (typeof STAGE_GROUPS)[number];

export const STAGE_GROUP_LABEL: Record<StageGroup, string> = {
  NEW: 'New',
  CONTACTED: 'Contacted',
  ONBOARDING: 'Onboarding',
  APPROVED: 'Approved',
  ACTIVE: 'Active',
  INACTIVE: 'Inactive',
};

export const STATUS_TO_STAGE_GROUP: Record<
  ExporterLifecycleStatus,
  StageGroup
> = {
  LEAD: 'NEW',
  CONTACTED: 'CONTACTED',
  DATA_COLLECTION: 'ONBOARDING',
  VERIFICATION_IN_PROGRESS: 'ONBOARDING',
  COMPLIANCE_REVIEW: 'ONBOARDING',
  ONBOARDED: 'APPROVED',
  FINANCING_ELIGIBLE: 'APPROVED',
  ACTIVE: 'ACTIVE',
  SUSPENDED: 'INACTIVE',
  OFFBOARDED: 'INACTIVE',
};

/** Human-readable label for the exact backend status — shown as the
 * secondary chip alongside the grouped stage, per the design principle that
 * grouping is a display choice, not information loss. */
export const STATUS_LABEL: Record<ExporterLifecycleStatus, string> = {
  LEAD: 'Lead',
  CONTACTED: 'Contacted',
  DATA_COLLECTION: 'Data Collection',
  VERIFICATION_IN_PROGRESS: 'Verification In Progress',
  COMPLIANCE_REVIEW: 'Compliance Review',
  ONBOARDED: 'Onboarded',
  FINANCING_ELIGIBLE: 'Financing Eligible',
  ACTIVE: 'Active',
  SUSPENDED: 'Suspended',
  OFFBOARDED: 'Offboarded',
};

/**
 * Full, static Tailwind class strings for each grouped stage's chip — not
 * built by interpolating a color name at runtime (`` `bg-stage-${x}` ``):
 * Tailwind's JIT compiler only generates classes it can see literally in
 * source, so a template-built class name would silently produce no styles
 * at all. Matches `tailwind.config.ts`'s `stage.*` palette.
 */
export const STAGE_GROUP_CHIP_CLASSES: Record<StageGroup, string> = {
  NEW: 'bg-stage-new/10 text-stage-new',
  CONTACTED: 'bg-stage-contacted/10 text-stage-contacted',
  ONBOARDING: 'bg-stage-onboarding/10 text-stage-onboarding',
  APPROVED: 'bg-stage-approved/10 text-stage-approved',
  ACTIVE: 'bg-stage-active/10 text-stage-active',
  INACTIVE: 'bg-stage-offboarded/10 text-stage-offboarded',
};


/**
 * Frontend mirror of backend
 * `ExporterProfileService.PERMITTED_LIFECYCLE_TRANSITIONS`. This is kept in
 * one place so EXP-F6 and the future EXP-F10 kanban share the exact same
 * definition of a legal move. Drift risk: when the backend graph changes,
 * this constant must change with it until the API exposes the graph as data.
 */
export const PERMITTED_LIFECYCLE_TRANSITIONS: Record<
  ExporterLifecycleStatus,
  readonly ExporterLifecycleStatus[]
> = {
  LEAD: ['CONTACTED'],
  CONTACTED: ['DATA_COLLECTION'],
  DATA_COLLECTION: ['VERIFICATION_IN_PROGRESS'],
  VERIFICATION_IN_PROGRESS: ['COMPLIANCE_REVIEW'],
  COMPLIANCE_REVIEW: ['DATA_COLLECTION', 'ONBOARDED'],
  ONBOARDED: ['FINANCING_ELIGIBLE', 'ACTIVE'],
  FINANCING_ELIGIBLE: ['ACTIVE'],
  ACTIVE: ['SUSPENDED', 'OFFBOARDED'],
  SUSPENDED: ['ACTIVE', 'OFFBOARDED'],
  OFFBOARDED: [],
};
