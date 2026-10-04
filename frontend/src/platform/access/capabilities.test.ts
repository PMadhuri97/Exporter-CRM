/**
 * The manifest against `docs/frontend-plan.md` §4.1 and the server's route groups —
 * written out by hand, so a wrong edit to `capabilities.ts` fails here.
 */

import { describe, expect, it } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { canReveal } from '@/platform/mask';

import { can, capabilitiesFor, type Capability } from './capabilities';

const EXPECTED: Record<Capability, UserRole[]> = {
  'crm.read': ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER'],
  'crm.write': ['OPERATIONS', 'COMPLIANCE', 'ADMIN'],
  'company.create': ['OPERATIONS', 'COMPLIANCE', 'ADMIN'],
  'company.import': ['OPERATIONS', 'COMPLIANCE', 'ADMIN'],
  'company.rxilIntake': ['ADMIN'],
  // D8: a company's background check is never the DEVELOPER's.
  'compliance.read': ['OPERATIONS', 'COMPLIANCE', 'ADMIN'],
  'compliance.decide': ['COMPLIANCE', 'ADMIN'],
  'compliance.queue': ['COMPLIANCE', 'ADMIN'],
  'gst.flag': ['COMPLIANCE', 'ADMIN'],
  'identifiers.reveal': ['COMPLIANCE', 'ADMIN'],
  'settings.criteria': ['ADMIN'],
  'settings.requiredDocuments': ['ADMIN'],
};

const ROLES: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER', 'API_USER'];

describe('the capability manifest', () => {
  const cases = (Object.keys(EXPECTED) as Capability[]).flatMap((capability) =>
    ROLES.map((role) => [capability, role, EXPECTED[capability].includes(role)] as const),
  );

  it.each(cases)('%s for %s is %s', (capability, role, expected) => {
    expect(can(role, capability)).toBe(expected);
  });

  it('gives the API user nothing in the CRM', () => {
    expect(capabilitiesFor('API_USER').size).toBe(0);
  });

  it.each([['AUDITOR'], [''], [null], [undefined]])(
    'fails closed for a role nobody listed (%s)',
    (role) => {
      expect(capabilitiesFor(role as string | null | undefined).size).toBe(0);
      expect(can(role as string | null | undefined, 'crm.read')).toBe(false);
    },
  );

  it('needs every capability in a list, and an empty list is always met', () => {
    expect(can('OPERATIONS', ['crm.read', 'crm.write'])).toBe(true);
    expect(can('OPERATIONS', ['crm.read', 'gst.flag'])).toBe(false);
    expect(can('API_USER', [])).toBe(true);
  });

  it('is the one list the masking reveal reads', () => {
    for (const role of ROLES) {
      expect(canReveal(role)).toBe(can(role, 'identifiers.reveal'));
    }
  });
});
