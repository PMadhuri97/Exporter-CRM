import { describe, expect, it } from 'vitest';

import {
  PIPELINE_STAGE_GROUPS,
  legalDropGroups,
  legalDropTargetForGroup,
} from './PipelinePage';
import { canMoveLifecycleFrom } from '../constants';

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

describe('canMoveLifecycleFrom — mirrors the backend per-edge gate', () => {
  it('lets OPERATIONS work the sales stages up to submitting for review', () => {
    for (const status of ['LEAD', 'CONTACTED', 'DATA_COLLECTION', 'VERIFICATION_IN_PROGRESS'] as const) {
      expect(canMoveLifecycleFrom(status, 'OPERATIONS')).toBe(true);
    }
  });

  it('reserves every move out of COMPLIANCE_REVIEW or later for COMPLIANCE/ADMIN', () => {
    for (const status of ['COMPLIANCE_REVIEW', 'ONBOARDED', 'ACTIVE', 'SUSPENDED'] as const) {
      expect(canMoveLifecycleFrom(status, 'OPERATIONS')).toBe(false);
      expect(canMoveLifecycleFrom(status, 'COMPLIANCE')).toBe(true);
      expect(canMoveLifecycleFrom(status, 'ADMIN')).toBe(true);
    }
  });

  it('never lets DEVELOPER or API_USER move an exporter', () => {
    expect(canMoveLifecycleFrom('LEAD', 'DEVELOPER')).toBe(false);
    expect(canMoveLifecycleFrom('LEAD', 'API_USER')).toBe(false);
  });
});
