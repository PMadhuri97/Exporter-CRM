/**
 * React Query hooks for the Exporter CRM — re-export barrel.
 *
 * Same per-owner split, and the same reason, as `api/index.ts`. Components
 * import from here.
 *
 *   profile.ts        company record and marker            Developer 2
 *   qualification.ts  criteria, results, outcomes          Developer 2
 *   intake.ts         RXIL intake, bulk CSV import          Developer 2
 *   history.ts        the shared history log               Developer 1
 *   engagement.ts     contacts, activities, conversation   Developer 3A
 *   follow-ups.ts     follow-ups and check-backs           Developer 3A
 *   deals.ts          deals and buyers                     Developer 3B
 *   documents.ts      documents and download links         Developer 3B
 *   verification.ts   checks, screening, bank activity     Developer 4
 *
 * Query keys are string arrays agreed by convention rather than a shared key
 * factory, so two owners can invalidate the same entry from different files —
 * the engagement mutations invalidate `['exporterProfile', id]`, Developer 2's
 * key, because the detail response embeds contacts and activities. A shared key
 * factory would be a separate change.
 */

export * from './profile';
export * from './qualification';
export * from './intake';
export * from './history';
export * from './engagement';
export * from './follow-ups';
export * from './deals';
export * from './documents';
export * from './verification';

// ── Background check — owner: Developer 4A ──
export * from './background-check';
