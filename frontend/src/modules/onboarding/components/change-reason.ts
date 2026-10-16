/**
 * What counts as a reason for changing a live settings rule — the server's rule
 * (`backend/.../domain/change_reason.py`), applied as the administrator types. Keep the
 * two in step; the server is the authority and checks again.
 */

export const CHANGE_REASON_MAX_LENGTH = 500;
const MIN_LENGTH = 15;
const MIN_WORDS = 3;
/** `ABC-123`, or letters followed by five or more digits (`CHG0031234`). */
const TICKET = /\b[A-Za-z]{2,10}(?:-\d+|\d{5,})\b/;

export const CHANGE_REASON_HINT =
  'A ticket number (e.g. CHG-1042) or a short explanation. Kept with this version for audit.';

/** What is wrong with `text` as a reason for a change, or `null` when it will do. */
export function changeReasonProblem(text: string): string | null {
  const cleaned = text.trim().split(/\s+/).filter(Boolean).join(' ');
  if (!cleaned) return 'A reason for the change is required';
  if (cleaned.length > CHANGE_REASON_MAX_LENGTH) return `Keep the reason to ${CHANGE_REASON_MAX_LENGTH} characters`;
  if (TICKET.test(cleaned)) return null;
  if (cleaned.length < MIN_LENGTH || cleaned.split(' ').length < MIN_WORDS) {
    return `Give a ticket number (e.g. CHG-1042) or explain the change in at least ${MIN_WORDS} words`;
  }
  return null;
}
