import type { TagTone } from '@/components';

import type { AdminUser } from './types';

type Role = AdminUser['role'];

// Order matters: most privileged first, so the filter dropdown and the role
// picker read consistently. Sourced from `UserRole` in
// `app/platform/authentication/models.py` — if the backend adds a role, the
// generated `schema.ts` widens this union and TypeScript flags the two
// records below as incomplete.
export const ROLE_OPTIONS: Role[] = [
  'ADMIN',
  'COMPLIANCE',
  'OPERATIONS',
  'DEVELOPER',
  'API_USER',
];

/** What each role can actually do, per section 3.7 of the architecture plan —
 * shown next to the role picker so an administrator is not guessing.
 *
 * The role *names* in this prose must match `roleLabel()`. COMPLIANCE's description
 * used to open "Everything Operations can do", which would have left the retired word
 * sitting in the product after every other site had moved off it. */
export const ROLE_DESCRIPTION: Record<Role, string> = {
  ADMIN: 'Full access, including managing users and qualification criteria.',
  COMPLIANCE:
    'Everything an RM can do, plus compliance decisions, audit trails, and unmasked tax IDs.',
  OPERATIONS:
    'Day-to-day CRM work: companies, contacts, activities and deals. Tax IDs are masked.',
  DEVELOPER:
    'Read-only technical access. Tax IDs are always masked and can never be revealed.',
  API_USER:
    'External or system callers. Reaches nothing in the CRM — the default for self-service sign-up.',
};

/** A role's tag: ink for the roles that sign decisions, quiet for the rest. Never a
 * state colour — colour means a state (frontend-plan §5.1), and a role is not one. */
export const ROLE_TAG_TONE: Record<Role, TagTone> = {
  ADMIN: 'ink',
  COMPLIANCE: 'ink',
  OPERATIONS: 'idle',
  DEVELOPER: 'idle',
  API_USER: 'idle',
};
