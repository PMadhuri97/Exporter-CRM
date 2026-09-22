import { describe, expect, it } from 'vitest';

import {
  PIPELINE_STAGE_GROUPS,
  legalDropGroups,
  legalDropTargetForGroup,
} from './PipelinePage';

describe('PipelinePage — EXP-F10 legal drag mapping', () => {
  it('excludes inactive exit states from kanban columns', () => {
    expect(PIPELINE_STAGE_GROUPS).toEqual([
      'NEW',
      'CONTACTED',
      'ONBOARDING',
      'APPROVED',
      'ACTIVE',
    ]);
    expect(PIPELINE_STAGE_GROUPS).not.toContain('INACTIVE');
  });

  it('allows LEAD to drop only into Contacted', () => {
    expect(legalDropGroups('LEAD')).toEqual(['CONTACTED']);
    expect(legalDropTargetForGroup('LEAD', 'CONTACTED')).toBe('CONTACTED');
    expect(legalDropTargetForGroup('LEAD', 'ACTIVE')).toBeNull();
  });

  it('maps compliance approval to Approved but keeps the same-column send-back on Move to', () => {
    expect(legalDropTargetForGroup('COMPLIANCE_REVIEW', 'APPROVED')).toBe('ONBOARDED');
    expect(legalDropTargetForGroup('COMPLIANCE_REVIEW', 'ONBOARDING')).toBeNull();
  });

  it('does not expose suspended/offboarded as drag targets from Active', () => {
    expect(legalDropGroups('ACTIVE')).toEqual([]);
  });
});
