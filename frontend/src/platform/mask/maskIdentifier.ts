import type { UserRole } from '@/lib/api/types';
import { can } from '@/platform/access';

/**
 * Who may see a raw tax identifier:
 *
 *   COMPLIANCE                                — unmasked.
 *   OPERATIONS / ADMIN / DEVELOPER / API_USER — masked, always.
 *
 * This mirrors `can_reveal_identifiers` in
 * `backend/app/modules/onboarding/api/schemas/masking.py` (the
 * `exporters:view_full_tax_id` permission), which is what
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
  // The `identifiers.reveal` capability (`platform/access`), so the role list lives in
  // one place. A role nobody listed reveals nothing.
  return can(role, 'identifiers.reveal');
}

const VISIBLE_SUFFIX_LENGTH = 4;
const MASK_CHAR = '•';

/**
 * Masks all but the trailing `VISIBLE_SUFFIX_LENGTH` characters, **whatever the role**.
 *
 * `maskIdentifier` below asks the role first and hands a privileged one the value
 * untouched. This does not ask: it is for the screen that holds a full value and has
 * been asked to cover it up — `Identifier`, where the eye starts closed, and a picker
 * option, which cannot hold an eye. It is safe on a value the server already masked:
 * the bullets stay bullets and the last four characters are the same four, so the
 * result is the same string.
 */
export function maskTail(value: string): string {
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
