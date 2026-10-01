/**
 * Wording for the background check's server-supplied keys — **owner: Developer 4A**.
 *
 * `clear_blocked_reasons` carries the four prerequisite names of A3
 * (`background-check.md` §13, §14.1). They are identifiers, not sentences, so the
 * screen says what each one asks of the person. This is wording only: which
 * prerequisites apply, and when, stays the server's decision. A key this file does
 * not know is shown as it arrived rather than hidden.
 */

const CLEAR_PREREQUISITE_LABELS: Record<string, string> = {
  risk_rating: 'choose a risk rating',
  no_checks_pending:
    'every verification check needs a final answer — none still pending, placeholder, or awaiting a review',
  screening_items_answered:
    'every screening item must be passed or exempt (a failed item means flagging the company instead)',
  evidence_recorded: 'at least one document, check or screening item must be on record',
};

export function describeClearBlocker(key: string): string {
  return CLEAR_PREREQUISITE_LABELS[key] ?? key;
}

// ── Developer 1 (compliance engine): check cycles (P2-3d) ──

const CYCLE_KIND_LABELS: Record<string, string> = {
  INITIAL: 'Initial check',
  RE_KYC: 'Re-KYC',
  RE_KYB: 'Re-KYB',
  FULL: 'Full re-check',
};

/** A check cycle's `kind`, for a person. An unknown kind is shown as it arrived. */
export function cycleKindLabel(kind: string): string {
  return CYCLE_KIND_LABELS[kind] ?? kind;
}
