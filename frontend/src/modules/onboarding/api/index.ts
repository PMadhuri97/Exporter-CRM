/**
 * Request functions for the Exporter CRM — re-export barrel.
 *
 * The functions live in one file per area, so changes to different areas never
 * queue on one file (architecture §7.2); this re-exports them.
 *
 * Import from here, not from the per-area files: the split is about who edits
 * what, not about who may call what.
 *
 *   profile.ts        company record and marker
 *   qualification.ts  criteria, results, outcomes
 *   intake.ts         RXIL intake, bulk CSV import
 *   history.ts        the shared history log
 *   engagement.ts     contacts, activities, conversation
 *   follow-ups.ts     follow-ups and check-backs
 *   deals.ts          deals and buyers
 *   documents.ts      documents and download links
 *   trade.ts          trade relationships and outcomes
 *   verification.ts   checks, screening, bank activity
 */

export * from './profile';
export * from './addresses';
export * from './bank-accounts';
export * from './payment-terms';
export * from './groups';
export * from './qualification';
export * from './intake';
export * from './history';
export * from './engagement';
export * from './follow-ups';
export * from './deals';
export * from './trade';
export * from './documents';
export * from './verification';

// ── Background check ──
export * from './background-check';
