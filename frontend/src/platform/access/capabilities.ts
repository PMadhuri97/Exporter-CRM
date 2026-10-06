/**
 * What each role may use — the one client-side copy of the server's role groups
 * (`docs/frontend-plan.md` §4.1–4.2).
 *
 * The server is the authority: it refuses what a role may not do whatever the screen
 * shows. This exists so the screen never **offers**, **mentions**, **fetches** or
 * **downloads** what the server would refuse. Every role check in the app goes through
 * here (`useCan`, `Gate`); a lint rule refuses `role === '…'` anywhere else.
 *
 * **An allowlist per role, failing closed.** No default branch and no denylist: a role
 * nobody listed — a new backend role, a typo, `undefined` — has no capability at all
 * and gets the No-workspace screen, not a guess.
 *
 * It mirrors these route-table groups (`tests/contract/test_route_authorization_coverage.py`
 * and `app/modules/onboarding/tests/integration/test_route_authorization.py`). Until the
 * server exports that table, a change there is a change here,
 * checked by hand in review:
 *
 *   READERS              OPERATIONS COMPLIANCE ADMIN DEVELOPER   GET /exporters, /follow-ups,
 *                                                                /deals/{id}, /companies/identity-completion
 *   STAFF                OPERATIONS COMPLIANCE ADMIN             POST /exporters, /imports/companies,
 *                                                                every CRM write, GET /background-check/due
 *                                                                and a company's background check
 *   COMPLIANCE_OR_ADMIN  COMPLIANCE ADMIN                        GET /background-check/proposals (queue),
 *                                                                decisions, GST branch flags, reveal
 *   ADMIN_ONLY           ADMIN                                   POST /rxil/company-intake,
 *                                                                POST /qualification/criteria,
 *                                                                POST /settings/deal-required-documents
 *
 * Users and roles screens are not here: they follow `/auth/me/permissions`
 * (`modules/settings/usePermissions`), so granting a permission needs no code change.
 */

import type { UserRole } from '@/lib/api/types';

export type Capability =
  /** See the CRM at all: companies, deals, follow-ups, pipeline. READERS. */
  | 'crm.read'
  /** Create, edit and move things in the CRM. STAFF. */
  | 'crm.write'
  /** Add a company by hand. STAFF. */
  | 'company.create'
  /** Import companies from a CSV. STAFF. */
  | 'company.import'
  /** Take in an RXIL package — records a decision as RXIL's. ADMIN_ONLY. */
  | 'company.rxilIntake'
  /** A company's background check and the Re-KYC due list. STAFF — never DEVELOPER. */
  | 'compliance.read'
  /** Decide, propose and approve background-check outcomes. COMPLIANCE_OR_ADMIN. */
  | 'compliance.decide'
  /** The cross-company queue of proposals awaiting approval. COMPLIANCE_OR_ADMIN. */
  | 'compliance.queue'
  /** Flag or unflag a GST branch — it stops trade through it. COMPLIANCE_OR_ADMIN. */
  | 'gst.flag'
  /** See full tax identifiers; everyone else is served them masked. COMPLIANCE_OR_ADMIN. */
  | 'identifiers.reveal'
  /** The qualification-criteria screen (an editing screen). ADMIN_ONLY. */
  | 'settings.criteria'
  /** The deal-required-documents screen (an editing screen). ADMIN_ONLY. */
  | 'settings.requiredDocuments';

const STAFF: readonly Capability[] = [
  'crm.read',
  'crm.write',
  'company.create',
  'company.import',
  'compliance.read',
];

const COMPLIANCE: readonly Capability[] = [
  ...STAFF,
  'compliance.decide',
  'compliance.queue',
  'gst.flag',
  'identifiers.reveal',
];

const ROLE_CAPABILITIES: Readonly<Record<UserRole, readonly Capability[]>> = {
  OPERATIONS: STAFF,
  COMPLIANCE,
  ADMIN: [...COMPLIANCE, 'company.rxilIntake', 'settings.criteria', 'settings.requiredDocuments'],
  // Reads the CRM, masked, and writes nothing.
  DEVELOPER: ['crm.read'],
  // Nothing in the CRM: the API user is a machine account.
  API_USER: [],
};

const NONE: ReadonlySet<Capability> = new Set();
const BY_ROLE = new Map<string, ReadonlySet<Capability>>(
  Object.entries(ROLE_CAPABILITIES).map(([role, caps]) => [role, new Set(caps)]),
);

/** Every capability `role` holds. A role nobody listed holds none. */
export function capabilitiesFor(role: UserRole | string | null | undefined): ReadonlySet<Capability> {
  if (typeof role !== 'string') return NONE;
  return BY_ROLE.get(role) ?? NONE;
}

/** Whether `role` holds every capability in `requires` (an empty list is always met). */
export function can(
  role: UserRole | string | null | undefined,
  requires: Capability | readonly Capability[],
): boolean {
  const held = capabilitiesFor(role);
  const needed: readonly Capability[] = typeof requires === 'string' ? [requires] : requires;
  return needed.every((capability) => held.has(capability));
}
