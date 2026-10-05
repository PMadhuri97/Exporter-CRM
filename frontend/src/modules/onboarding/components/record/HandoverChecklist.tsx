/**
 * Handover readiness: the handover guard as a checklist (frontend-plan §6.11).
 *
 * **Today (fallback):** the server sends the guard's verdict as one sentence,
 * `handover_blocked_reason`, and this shows it verbatim in one attention callout —
 * "Not ready to hand over: …". It does **not** split the sentence on ";" to fake a
 * list: the rows would be the client's guess at the server's structure.
 *
 * **With structured `handover_conditions`**: pass `conditions` and
 * each one becomes a row — met or not, in the server's words, with an optional link
 * to where it is fixed. Nothing else changes for the callers.
 *
 * Nothing at all is drawn for a role the server gives no reason to (Developer):
 * no reason, no callout.
 */

import { Link } from 'react-router-dom';

import { LINK_CLASSES } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

export interface HandoverCondition {
  key: string;
  met: boolean;
  message: string;
  /** Where it is fixed, when the role may act there. */
  fixAt?: { to: string; label: string };
}

export function HandoverChecklist({
  blockedReason,
  conditions,
}: {
  blockedReason: string | null | undefined;
  conditions?: HandoverCondition[];
}) {
  if (conditions && conditions.length > 0) {
    const met = conditions.filter((condition) => condition.met).length;
    return (
      <div role="group" aria-label="Handover readiness" data-testid="handover-checklist">
        <header className="flex items-baseline justify-between gap-3">
          <h3 className="text-heading font-semibold text-ink">Handover readiness</h3>
          <span className="text-secondary tabular-nums text-ink-3">
            {met} of {conditions.length} met
          </span>
        </header>
        <ul className="mt-2 divide-y divide-line">
          {conditions.map((condition) => (
            <li key={condition.key} className="flex items-center gap-3 py-2 text-body">
              {condition.met ? (
                <Icon.passed size={20} weight="regular" className="shrink-0 text-positive" aria-hidden />
              ) : (
                <Icon.error size={20} className="shrink-0 text-negative" aria-hidden />
              )}
              <span className={cn('flex-1', condition.met ? 'text-ink-2' : 'text-ink')}>
                <span className="sr-only">{condition.met ? 'Met: ' : 'Not met: '}</span>
                {condition.message}
              </span>
              {!condition.met && condition.fixAt && (
                <Link to={condition.fixAt.to} className={`text-secondary ${LINK_CLASSES}`}>
                  {condition.fixAt.label}
                  <span aria-hidden> ›</span>
                </Link>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (!blockedReason) return null;
  return (
    <div
      role="note"
      data-testid="handover-checklist"
      className="flex items-start gap-2.5 rounded border border-attention-solid/40 bg-attention-tint px-3 py-2.5"
    >
      <Icon.warning size={20} className="shrink-0 text-attention" aria-hidden />
      <p className="text-body text-ink">
        <span className="font-semibold">Not ready to hand over:</span> {blockedReason}
      </p>
    </div>
  );
}
