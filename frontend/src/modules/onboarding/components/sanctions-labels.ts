/** Words for sanctions screening: outcomes, decisions on a match, and who was screened. */

import type { BadgeTone } from '@/components/ui/styles';

import type { SanctionsDisposition, SanctionsSubject } from '../types';

export type SanctionsOutcome = 'PASSED' | 'FAILED' | 'REVIEW';

export const OUTCOME_LABEL: Record<SanctionsOutcome, string> = {
  PASSED: 'Passed',
  FAILED: 'Failed',
  REVIEW: 'Under review',
};

export const OUTCOME_TONE: Record<SanctionsOutcome, BadgeTone> = {
  PASSED: 'positive',
  FAILED: 'negative',
  REVIEW: 'attention',
};

export const DISPOSITION_LABEL: Record<SanctionsDisposition, string> = {
  OPEN: 'Open',
  FALSE_POSITIVE: 'False positive',
  TRUE_MATCH_PROPOSED: 'True match — awaiting confirmation',
  TRUE_MATCH: 'True match',
  ESCALATED: 'Escalated',
};

export const DISPOSITION_TONE: Record<SanctionsDisposition, BadgeTone> = {
  OPEN: 'attention',
  FALSE_POSITIVE: 'positive',
  TRUE_MATCH_PROPOSED: 'negative',
  TRUE_MATCH: 'negative',
  ESCALATED: 'progress',
};

export const SUBJECT_LABEL: Record<SanctionsSubject['subject_type'], string> = {
  COMPANY: 'Company',
  DIRECTOR: 'Director',
  UBO: 'Beneficial owner',
};
