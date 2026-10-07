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

/** `GATHERING_PAPERWORK` → `Gathering Paperwork`.
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

/**
 * Now, written the way an `<input type="datetime-local">` reads a `min`.
 *
 * Deliberately built from the local parts rather than `toISOString().slice(0, 16)`:
 * that string is UTC, and the input compares it against what the person sees on their
 * own clock. East of UTC it would bar valid times; west of it, it would let a past time
 * through — which is exactly the mistake this `min` exists to prevent.
 *
 * It is a floor for pickers whose value the server refuses in the past: a follow-up's
 * due date and a reschedule. The server still refuses it (`ACTIVITY_DUE_IN_PAST`,
 * `FOLLOW_UP_RESCHEDULE_IN_PAST`) — this only stops the screen offering what would be
 * turned down, and a page left open past the chosen minute will still rely on that.
 */
export function nowForDateTimeInput(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}`
  );
}

/** Today, for an `<input type="date">` `min`. The date half of the above. */
export function todayForDateInput(now: Date = new Date()): string {
  return nowForDateTimeInput(now).slice(0, 10);
}
