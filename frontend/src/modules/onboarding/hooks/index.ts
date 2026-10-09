/**
 * React Query hooks for the Exporter CRM — re-export barrel.
 *
 * Same per-area split, and the same reason, as `api/index.ts`. Components
 * import from here.
 *
 *   profile.ts        company record and marker
 *   finder.ts         the command bar's company search
 *   qualification.ts  criteria, results, outcomes
 *   intake.ts         RXIL intake, bulk CSV import
 *   history.ts        the shared history log
 *   engagement.ts     contacts, activities, conversation
 *   follow-ups.ts     follow-ups and check-backs
 *   deals.ts          deals and buyers
 *   documents.ts      documents and download links
 *   verification.ts   checks, screening, bank activity
 *
 * Query keys are string arrays agreed by convention rather than a shared key
 * factory, so two areas can invalidate the same entry from different files —
 * the engagement mutations invalidate `['exporterProfile', id]`, the company
 * record's key, because the detail response embeds contacts and activities. A shared key
 * factory would be a separate change.
 */

export * from './profile';
export * from './addresses';
export * from './bank-accounts';
export * from './payment-terms';
export * from './groups';
export * from './sanctions';
export * from './finder';
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
