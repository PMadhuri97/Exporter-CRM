/**
 * What counts as a reason for changing a live settings rule — the server's rule
 * (`backend/.../domain/change_reason.py`), applied as the administrator types. Keep the
 * two in step; the server is the authority and checks again.
 *
 * A ticket number in capitals comes first (`CHG-1042`, or `CHG0031234`), then a short
 * explanation: at least two real words (two or more Latin letters each) and ten
 * characters, so "chg-7", "CHG-7" alone or a run of symbols are refused.
 */

export const CHANGE_REASON_MAX_LENGTH = 500;
const MIN_TEXT_LENGTH = 10;
const MIN_WORDS = 2;
/** `ABC-123`, or capitals followed by five or more digits (`CHG0031234`), then the text. */
const REASON = /^([A-Z]{2,10}(?:-[0-9]+|[0-9]{5,}))(?:(?:\s*[:–—-]\s*|\s+)(.*))?$/;
const WORD = /[A-Za-z]{2,}/;

export const CHANGE_REASON_HINT =
  'A ticket number, then what changed (e.g. CHG-1042: raise the turnover floor). Kept with this version for audit.';

/** What is wrong with `text` as a reason for a change, or `null` when it will do. */
export function changeReasonProblem(text: string): string | null {
  const cleaned = text.trim().split(/\s+/).filter(Boolean).join(' ');
  if (!cleaned) return 'A reason for the change is required';
  if (cleaned.length > CHANGE_REASON_MAX_LENGTH) return `Keep the reason to ${CHANGE_REASON_MAX_LENGTH} characters`;
  const match = REASON.exec(cleaned);
  if (!match) return 'Start with a ticket number in capitals, e.g. CHG-1042: …';
  const explanation = match[2] ?? '';
  const words = explanation.split(' ').filter((word) => WORD.test(word));
  if (explanation.length < MIN_TEXT_LENGTH || words.length < MIN_WORDS) {
    return `After the ticket number, explain the change in at least ${MIN_WORDS} words and ${MIN_TEXT_LENGTH} characters`;
  }
  return null;
}
