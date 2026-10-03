/**
 * Request functions for the Exporter CRM — re-export barrel.
 *
 * The functions live in one file per owner, so developers working in parallel
 * never queue on one file (architecture §7.2); this re-exports them.
 *
 * Import from here, not from the per-owner files: the split is about who edits
 * what, not about who may call what.
 *
 *   profile.ts        company record and marker            Developer 2
 *   qualification.ts  criteria, results, outcomes          Developer 2
 *   intake.ts         RXIL intake, bulk CSV import          Developer 2
 *   history.ts        the shared history log               Developer 1
 *   engagement.ts     contacts, activities, conversation   Developer 3A
 *   follow-ups.ts     follow-ups and check-backs           Developer 3A
 *   deals.ts          deals and buyers                     Developer 3B
 *   documents.ts      documents and download links         Developer 3B
 *   trade.ts          trade relationships and outcomes     Developer 3
 *   verification.ts   checks, screening, bank activity     Developer 4
 */

export * from './profile';
export * from './qualification';
export * from './intake';
export * from './history';
export * from './engagement';
export * from './follow-ups';
export * from './deals';
export * from './trade';
export * from './documents';
export * from './verification';

// ── Background check — owner: Developer 4A ──
export * from './background-check';
