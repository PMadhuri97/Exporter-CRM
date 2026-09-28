import type { UserRole } from '@/lib/api/types';

/**
 * Who may see a raw tax identifier:
 *
 *   COMPLIANCE / ADMIN                — unmasked.
 *   OPERATIONS / DEVELOPER / API_USER — masked, always.
 *
 * This mirrors `can_reveal_identifiers` in
 * `backend/app/modules/onboarding/api/schemas/exporter.py`, which is what
 * actually enforces it — the server masks before the value ever reaches the
 * browser, so this function decides whether to render a reveal control, not
 * whether the data is protected.
 *
 * It previously carried an ownership exception: OPERATIONS could reveal on
 * records where it was the assigned relationship manager. Architecture
 * decision 12 settles the prototype the other way — sales staff see masked
 * values, and relationship-manager ownership waits until after the prototype —
 * so both sides dropped that branch together. Re-adding it here without
 * changing the backend would produce a reveal control that reveals bullets.
 */
export function canReveal(role: UserRole): boolean {
  switch (role) {
    case 'COMPLIANCE':
    case 'ADMIN':
      return true;
    case 'OPERATIONS':
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
  if (canReveal(context.role)) return value;
  return maskTail(value);
}
