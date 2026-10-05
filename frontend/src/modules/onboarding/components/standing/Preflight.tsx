/**
 * Pre-flight: the handover guard as a checklist (frontend-plan §6.4).
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

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

export interface PreflightCondition {
  key: string;
  met: boolean;
  message: string;
  /** Where it is fixed, when the role may act there. */
  fixAt?: { to: string; label: string };
}

export function Preflight({
  blockedReason,
  conditions,
}: {
  blockedReason: string | null | undefined;
  conditions?: PreflightCondition[];
}) {
  if (conditions && conditions.length > 0) {
    const met = conditions.filter((condition) => condition.met).length;
    return (
      <div role="group" aria-label="Ready to hand over?" data-testid="preflight">
        <header className="flex items-baseline justify-between gap-3">
          <h3 className="text-lead font-semibold text-ink">Ready to hand over?</h3>
          <span className="text-secondary tabular-nums text-ink-3">
            {met} of {conditions.length}
          </span>
        </header>
        <ul className="mt-2 divide-y divide-line">
          {conditions.map((condition) => (
            <li key={condition.key} className="flex items-center gap-3 py-2 text-body">
              {condition.met ? (
                <Icon.check size={16} className="shrink-0 text-positive" aria-hidden />
              ) : (
                <Icon.close size={16} className="shrink-0 text-negative" aria-hidden />
              )}
              <span className={cn('flex-1', condition.met ? 'text-ink-2' : 'text-ink')}>
                <span className="sr-only">{condition.met ? 'Met: ' : 'Not met: '}</span>
                {condition.message}
              </span>
              {!condition.met && condition.fixAt && (
                <Link to={condition.fixAt.to} className="text-secondary font-medium text-ink underline decoration-line-strong underline-offset-[3px] hover:decoration-ink">
                  {condition.fixAt.label}
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
      data-testid="preflight"
      className="flex items-start gap-2.5 rounded-md border-l-2 border-attention-solid bg-attention-tint px-3.5 py-2.5"
    >
      <Icon.warning size={16} className="mt-0.5 shrink-0 text-attention" aria-hidden />
      <p className="text-body text-ink">
        <span className="font-medium">Not ready to hand over:</span> {blockedReason}
      </p>
    </div>
  );
}
