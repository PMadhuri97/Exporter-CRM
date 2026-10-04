/**
 * Role names, as people read them.
 *
 * What a role may *do* is not here: that is `@/platform/access` (`useCan`, `Gate`),
 * the one client-side copy of the server's role groups (R-33, frontend plan §4.2).
 * The `isStaffRole` / `isAdminRole` / `isComplianceRole` helpers that used to live in
 * this file were replaced by its capabilities.
 */

import type { UserRole } from '@/lib/api/types';

/**
 * What a role is called on screen.
 *
 * `OPERATIONS` reads **"RM (Relationship Manager)"** (IQ-13): the people in that role
 * are relationship managers, and "Operations" meant nothing to them. The **enum value
 * is deliberately unchanged** — it is written into every history row already recorded
 * and into every route-authorisation table, so renaming it would make the past read as
 * a role that never existed.
 *
 * This exists instead of `humanize(role)` (`lib/format.ts`), which title-cases an enum
 * generically and so can only ever produce "Operations". `humanize` stays right for
 * every other enum; a role is the one vocabulary where the stored value and the label
 * have come apart on purpose.
 *
 * Every screen that shows a role calls this, so the label is in one place: miss one and
 * the old word reappears in a corner of the product.
 */
const ROLE_LABEL: Record<UserRole, string> = {
  ADMIN: 'Admin',
  COMPLIANCE: 'Compliance',
  OPERATIONS: 'RM (Relationship Manager)',
  DEVELOPER: 'Developer',
  API_USER: 'API user',
};

export function roleLabel(role: UserRole): string {
  // A role the API adds before this map does falls back to the raw value rather
  // than rendering `undefined`.
  return ROLE_LABEL[role] ?? role;
}

/**
 * The short form, for places where the full label would crowd the layout — a table
 * chip or a filter option. `OPERATIONS` is just "RM" here; every other role is the
 * same as its full label.
 */
const ROLE_SHORT_LABEL: Record<UserRole, string> = {
  ...ROLE_LABEL,
  OPERATIONS: 'RM',
};

export function roleShortLabel(role: UserRole): string {
  return ROLE_SHORT_LABEL[role] ?? role;
}
