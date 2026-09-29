/**
 * The duplicate-PAN refusal (`DUPLICATE_PAN`, 409) names the company that holds the
 * PAN by its id, in `error_context.existing_customer_id`. The server's message
 * repeats that raw id; the screens show a link to the company instead.
 *
 * Kept apart from `DuplicatePanMessage.tsx` so that file exports only a component
 * (react-refresh's rule).
 */

import { ApiError } from '@/lib/api/errors';

/** The id of the company that already holds the PAN, when `error` is that refusal. */
export function duplicatePanHolder(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.errorCode !== 'DUPLICATE_PAN') return null;
  const holder = error.context?.existing_customer_id;
  return typeof holder === 'string' ? holder : null;
}
