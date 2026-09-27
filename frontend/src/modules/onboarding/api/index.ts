/**
 * Request functions for the Exporter CRM — re-export barrel.
 *
 * This file used to hold all of them. Four developers working in parallel on
 * one file means waiting in a queue rather than working in parallel
 * (architecture §7.2), so the functions now live in three files, one per
 * owner, and this re-exports them.
 *
 * Import from here, not from the per-owner files: the split is about who edits
 * what, not about who may call what. If an owner boundary moves, only these
 * three lines change.
 *
 *   profile.ts       company record and journey        Developer 2
 *   engagement.ts    contacts and the activity log     Developer 3
 *   verification.ts  checks, screening, bank activity  Developer 4
 *   qualification.ts qualification results, outcomes  Developer 2
 *   intake.ts        RXIL intake, bulk CSV import     Developer 2
 */

export * from './profile';
export * from './engagement';
export * from './verification';
export * from './qualification';
export * from './intake';

/*
 * Section 9.3 — one commit adds all three lines, and nobody adds another.
 *
 * `follow-ups` is Developer 3A Phase 2's, `deals` and `documents` Developer
 * 3B's. All three modules are empty today; the lines are here so that neither
 * developer — and neither of 3A's two phases — ever edits this barrel again.
 * A barrel every owner appends to is a queue, which is the thing the per-owner
 * split (above) exists to avoid.
 */
export * from './follow-ups';
export * from './deals';
export * from './documents';
