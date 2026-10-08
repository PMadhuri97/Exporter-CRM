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
 * The server checks permissions; this mirrors what each built-in role is seeded with
 * (`platform/authorization/catalog.py`, `BUILTIN_ROLE_PERMISSIONS`) and the route tables
 * that test them (`tests/contract/test_route_authorization_coverage.py`,
 * `app/modules/onboarding/tests/integration/test_route_authorization.py`). Until the
 * server exports that table, a change there is a change here, checked by hand in review:
 *
 *   READERS          OPERATIONS COMPLIANCE ADMIN DEVELOPER   exporters:view — GET /exporters,
 *                                                            /follow-ups, /deals, /deals/{id}
 *   STAFF            OPERATIONS COMPLIANCE                   exporters:create/edit, deals:*,
 *                                                            every CRM write
 *   STAFF + ADMIN    OPERATIONS COMPLIANCE ADMIN             compliance:view — a company's
 *                                                            background check, the due list
 *   COMPLIANCE       COMPLIANCE                              compliance:decide/approve, GST
 *                                                            branch flags, the reveal, RXIL intake
 *   ADMIN            ADMIN                                   settings:manage — criteria and
 *                                                            required documents
 *
 * The administrator reads the business and changes none of it. A lead role (Compliance
 * lead, Sales lead) keeps its base role's capabilities here; its senior permissions are
 * read from the server (`useHasPermission`).
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
  /** Take in an RXIL package — records a decision as RXIL's. COMPLIANCE. */
  | 'company.rxilIntake'
  /** A company's background check and the Re-KYC due list. STAFF and ADMIN — never DEVELOPER. */
  | 'compliance.read'
  /** Decide, propose and approve background-check outcomes. COMPLIANCE. */
  | 'compliance.decide'
  /** The cross-company queue of proposals awaiting approval. COMPLIANCE. */
  | 'compliance.queue'
  /** Flag or unflag a GST branch — it stops trade through it. COMPLIANCE. */
  | 'gst.flag'
  /** See full tax identifiers; everyone else is served them masked. COMPLIANCE. */
  | 'identifiers.reveal'
  /**
   * Whose queue the unjudged leads are. **Not a permission**, and the one entry here
   * that mirrors no route group: COMPLIANCE may record a qualification decision too —
   * both hold `crm.write` and the server refuses neither.
   * It says whose *work* it is, so the pipeline can count "waiting on you" for the
   * relationship managers and show nobody else a tally of someone else's queue.
   *
   * It is therefore the one capability a wider role does not inherit. Never gate a
   * request or a write on it; `crm.write` is the permission.
   */
  | 'queue.qualification'
  /**
   * Can be a company's relationship manager, and so may name **themselves** as one:
   * OPERATIONS only, mirroring the server's `domain/assignment.RM_ROLES`. Like
   * `queue.qualification`, a wider role does not inherit it — COMPLIANCE never is an RM.
   * Naming someone else is the `exporters:assign_rm` permission (`useHasPermission`,
   * the Sales lead role), not this.
   */
  | 'rm.self'
  /** The qualification-criteria screen (an editing screen). ADMIN. */
  | 'settings.criteria'
  /** The deal-required-documents screen (an editing screen). ADMIN. */
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
  'company.rxilIntake',
  'compliance.decide',
  'compliance.queue',
  'gst.flag',
  'identifiers.reveal',
];

const ROLE_CAPABILITIES: Readonly<Record<UserRole, readonly Capability[]>> = {
  // `queue.qualification` is deliberately not in `STAFF`, and so not inherited by
  // COMPLIANCE below: it marks whose work the leads are, not who may act.
  OPERATIONS: [...STAFF, 'queue.qualification', 'rm.self'],
  COMPLIANCE,
  // Runs the system: settings, and reading the business (companies, deals, a company's
  // background check) to help people with it. Writes, decides and reveals nothing.
  ADMIN: ['crm.read', 'compliance.read', 'settings.criteria', 'settings.requiredDocuments'],
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
