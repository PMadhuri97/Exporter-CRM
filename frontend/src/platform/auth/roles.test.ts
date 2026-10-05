import { describe, expect, it } from 'vitest';

import type { UserRole } from '@/lib/api/types';

import { roleLabel, roleShortLabel } from './roles';

describe('roleLabel', () => {
  // The enum value stays OPERATIONS; only what a person reads changes.
  it('names OPERATIONS as the relationship manager', () => {
    expect(roleLabel('OPERATIONS')).toBe('RM (Relationship Manager)');
    expect(roleShortLabel('OPERATIONS')).toBe('RM');
  });

  it('never shows the retired word for any role', () => {
    const roles: UserRole[] = ['ADMIN', 'COMPLIANCE', 'OPERATIONS', 'DEVELOPER', 'API_USER'];
    for (const role of roles) {
      expect(roleLabel(role)).not.toMatch(/operations/i);
      expect(roleShortLabel(role)).not.toMatch(/operations/i);
    }
  });

  it('falls back to the raw value for a role the map does not know yet', () => {
    expect(roleLabel('AUDITOR' as UserRole)).toBe('AUDITOR');
  });
});
