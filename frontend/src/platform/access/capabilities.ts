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
 *                                                                /deals, /deals/{id},
 *                                                                /companies/identity-completion
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
 *
 * One entry — `queue.qualification` — mirrors no route group and is not a permission.
 * It marks whose queue a piece of work is, so a screen can address the people whose job
 * it is without a `role === '…'` check. Its own comment says why it is here.
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
  /**
   * Whose queue the unjudged leads are. **Not a permission**, and the one entry here
   * that mirrors no route group: COMPLIANCE and ADMIN may record a qualification
   * decision too — all three hold `crm.write` and the server refuses none of them.
   * It says whose *work* it is, so the pipeline can count "waiting on you" for the
   * relationship managers and show nobody else a tally of someone else's queue.
   *
   * It is therefore the one capability a wider role does not inherit. Never gate a
   * request or a write on it; `crm.write` is the permission.
   */
  | 'queue.qualification'
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
  // `queue.qualification` is deliberately not in `STAFF`, and so not inherited by
  // COMPLIANCE or ADMIN below: it marks whose work the leads are, not who may act.
  OPERATIONS: [...STAFF, 'queue.qualification'],
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
