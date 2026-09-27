/**
 * React Query hooks for the Exporter CRM — re-export barrel.
 *
 * Same split, and the same reason, as `api/index.ts`: one file that four
 * developers all edit is a queue, not parallel work (architecture §7.2).
 * Components import from here; the per-owner files exist so that edits do not
 * collide.
 *
 *   profile.ts       company record and journey        Developer 2
 *   engagement.ts    contacts and the activity log     Developer 3
 *   verification.ts  checks, screening, bank activity  Developer 4
 *   qualification.ts qualification results, outcomes  Developer 2
 *   intake.ts        RXIL intake, bulk CSV import     Developer 2
 *
 * Query keys were not touched by the split. They are still ad-hoc string
 * arrays agreed by convention rather than a shared key factory, so two owners
 * can still invalidate the same cache entry from different files — the
 * engagement mutations invalidate `['exporterProfile', id]`, which is
 * Developer 2's key, because the detail response embeds contacts and
 * activities. That is existing behaviour, preserved deliberately; a shared key
 * factory is a separate change and not part of this mechanical split.
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
