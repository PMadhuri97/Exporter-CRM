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
