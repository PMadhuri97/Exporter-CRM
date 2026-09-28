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
 * shown next to the role picker so an administrator is not guessing. */
export const ROLE_DESCRIPTION: Record<Role, string> = {
  ADMIN: 'Full access, including managing users and qualification criteria.',
  COMPLIANCE:
    'Everything Operations can do, plus compliance decisions, audit trails, and unmasked tax IDs.',
  OPERATIONS:
    'Day-to-day CRM work: companies, contacts, activities and deals. Tax IDs are masked.',
  DEVELOPER:
    'Read-only technical access. Tax IDs are always masked and can never be revealed.',
  API_USER:
    'External or system callers. Reaches nothing in the CRM — the default for self-service sign-up.',
};

/** Chip colours reuse the existing semantic palette rather than introducing a
 * per-role hue: privileged roles read as "attention", ordinary staff as
 * neutral. Never the risk or verification colours, which must stay unambiguous
 * on screens that show them alongside. */
export const ROLE_CHIP_CLASS: Record<Role, string> = {
  ADMIN: 'bg-brand-50 text-brand-600',
  COMPLIANCE: 'bg-brand-50 text-brand-600',
  OPERATIONS: 'bg-surface-sunken text-ink-muted',
  DEVELOPER: 'bg-surface-sunken text-ink-muted',
  API_USER: 'bg-surface-sunken text-ink-faint',
};
