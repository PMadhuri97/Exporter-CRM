/**
 * Display formatting shared across the CRM screens.
 *
 * These three helpers were defined inside `ExporterDetailPage.tsx`. Splitting
 * that page into per-owner panels left two of them needed by more than one
 * panel, and the alternative to sharing was copying — which is how two panels
 * end up rendering the same timestamp two different ways.
 *
 * Moved verbatim; no behaviour changed.
 */

import { format } from 'date-fns';

/** `dd MMM yyyy`, or an em dash when there is nothing to show. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  return format(new Date(value), 'dd MMM yyyy');
}

/** `dd MMM yyyy, HH:mm` — used where the time of day carries meaning, such as
 * when an activity happened or when a follow-up falls due. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return format(new Date(value), 'dd MMM yyyy, HH:mm');
}

/** `DATA_COLLECTION` → `Data Collection`.
 *
 * For rendering a backend enum member to a person. Screens show the server's
 * vocabulary rather than inventing labels for it, so a value the API adds
 * appears correctly without a frontend change. */
export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
