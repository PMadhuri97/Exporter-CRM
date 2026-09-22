import type { UserRole } from '@/lib/api/types';

/**
 * Implements the role capability matrix in
 * `docs/exporter-crm-frontend-tickets.md` (updated 2026-09-21):
 *
 *   COMPLIANCE / ADMIN  — always unmasked.
 *   OPERATIONS          — masked, EXCEPT on records this user owns
 *                          (`isOwner`) — an ownership-scoped exception, not
 *                          a blanket role exception.
 *   DEVELOPER / API_USER — always masked, no reveal under any circumstance.
 *
 * `isOwner` answers "is the current user this record's assigned
 * relationship_manager" — callers compute that comparison themselves (see
 * that field's known backend gap in the ticket doc: it's currently a bare
 * display string, not a stable id, so this function does not attempt the
 * comparison itself).
 */
export function canReveal(role: UserRole, isOwner = false): boolean {
  switch (role) {
    case 'COMPLIANCE':
    case 'ADMIN':
      return true;
    case 'OPERATIONS':
      return isOwner;
    case 'DEVELOPER':
    case 'API_USER':
      return false;
  }
}

const VISIBLE_SUFFIX_LENGTH = 4;
const MASK_CHAR = '•';

/** Masks all but the trailing `VISIBLE_SUFFIX_LENGTH` characters. */
function maskTail(value: string): string {
  if (value.length <= VISIBLE_SUFFIX_LENGTH)
    return MASK_CHAR.repeat(value.length);
  const hiddenLength = value.length - VISIBLE_SUFFIX_LENGTH;
  return MASK_CHAR.repeat(hiddenLength) + value.slice(-VISIBLE_SUFFIX_LENGTH);
}

export interface MaskContext {
  role: UserRole;
  isOwner?: boolean;
}

/**
 * The one place PII rendering decisions get made — every screen that shows
 * PAN/GSTIN/IEC or similar identifiers calls this rather than re-deciding
 * masking logic per component.
 */
export function maskIdentifier(
  value: string | null | undefined,
  context: MaskContext,
): string | null {
  if (value === null || value === undefined) return value ?? null;
  if (canReveal(context.role, context.isOwner)) return value;
  return maskTail(value);
}
