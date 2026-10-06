import { ApiError } from '@/lib/api/errors';

/** The message a refusal gives for `field`, if it named that field. */
export function sidePanelFieldError(error: unknown, field: string): string | undefined {
  return error instanceof ApiError ? (error.fieldErrors?.[field] ?? undefined) : undefined;
}
