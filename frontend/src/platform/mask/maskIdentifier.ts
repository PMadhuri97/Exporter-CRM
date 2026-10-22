/**
 * Covering a tax identifier on screen.
 *
 * **Who may reveal one is not decided here.** It is a permission the server grants and
 * enforces — `exporters:view_full_tax_id`, the same one `can_reveal_identifiers` in
 * `backend/app/modules/onboarding/api/schemas/masking.py` reads — and a screen asks
 * for it through `useCanRevealIdentifiers`. The server masks before a value ever
 * reaches the browser, so nothing here protects the data; it decides what a screen
 * prints.
 *
 * This file used to answer "who may reveal" from a role list of its own. That was one
 * answer too many, and the two drifted apart the first time somebody used them:
 * granting the permission to the relationship manager unmasked the values on the way
 * out, while the screen went on covering them with no eye to open — the full value
 * crossing the network and no way to read it. The question now has one answer, and it
 * is the server's.
 */

const VISIBLE_SUFFIX_LENGTH = 4;
const MASK_CHAR = '•';

/**
 * Masks all but the trailing `VISIBLE_SUFFIX_LENGTH` characters, **whatever the role**.
 *
 * It does not ask who is looking: it is for the screen that holds a full value and has
 * been asked to cover it up — `Identifier`, where the eye starts closed, and a picker
 * option, which cannot hold an eye. It is safe on a value the server already masked:
 * the bullets stay bullets and the last four characters are the same four, so the
 * result is the same string.
 */
export function maskTail(value: string): string {
  if (value.length <= VISIBLE_SUFFIX_LENGTH) return MASK_CHAR.repeat(value.length);
  const hiddenLength = value.length - VISIBLE_SUFFIX_LENGTH;
  return MASK_CHAR.repeat(hiddenLength) + value.slice(-VISIBLE_SUFFIX_LENGTH);
}
