/**
 * An identifier — PAN, GSTIN, IEC, CIN, a registration number (frontend-plan §6.14).
 * Replaces `MaskedValue` everywhere; the one component that owns the masking rule
 * on screen.
 *
 * - Set in the one UI face (§5.3 has no second family) with `tabular-nums`, so the
 *   figures line up in a column of them, and `whitespace-nowrap`, so the value is never
 *   broken across lines. `Editable` wraps a displayed value in `overflow-wrap: anywhere`
 *   — right for a long company name, wrong here: a PAN split over two lines reads as two
 *   fragments, and a reviewer reported exactly that. An identifier is one token or it is
 *   nothing, so it would rather overflow a narrow column than be cut in half.
 * - One step down the type scale (`text-caption`, 12px) from the facts around it. An
 *   unbreakable 21-character CIN at 13px ran past its column and under `Editable`'s
 *   pencil; a smaller size buys that room back without a second line of controls or a
 *   narrower label column. It applies to every identifier, not just the long one, so a
 *   column of them stays one size.
 * - The eye exists **only** for a role that may reveal (`identifiers.reveal`). A
 *   masked role gets no eye at all — "a disabled eye icon would still leak 'this
 *   data exists, you're just not allowed'" (architecture §9). The server already
 *   sends masked roles masked values; the bullets here repeat that.
 * - Copy is offered **only** where the full value is on screen — never beside
 *   bullets: copying them is useless, and the button would invite the question.
 *
 * **The eye starts closed.** This settles the open question frontend-plan §6.14 left
 * (either the eye goes, or a privileged role reads masked until it reveals) the second
 * way. Until then a role that may reveal was shown the full value *and* an eye, so the
 * button toggled between full and full and appeared broken — which is how a reviewer
 * found it.
 *
 * The server still sends these roles the value in full; what covers it is this screen,
 * for as long as nobody asks. That is worth having anyway: an identifier is not read on
 * most visits, and one left uncovered is one shown to whoever is behind the person at
 * the desk, or in a screen share. Revealing is now a deliberate act. `revealed` is this
 * component's own state: it survives a re-render (a refetch of the record keeps an
 * open eye open) and resets when the component mounts again — leaving the record and
 * coming back starts covered.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { useCurrentUser } from '@/platform/auth';

import { canReveal, maskTail } from './maskIdentifier';

const CONTROL =
  'rounded p-0.5 text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink';

export function Identifier({
  value,
  kind,
  className,
}: {
  value: string | null | undefined;
  /** What it is ("PAN"), for the copy confirmation. */
  kind?: string;
  className?: string;
}) {
  const { role } = useCurrentUser();
  const [revealed, setRevealed] = useState(false);

  if (value === null || value === undefined) {
    return <span className={cn('text-ink-3', className)}>—</span>;
  }

  const mayReveal = canReveal(role);
  const shown = mayReveal && revealed;

  // Masked unless this very screen is showing it: `maskTail` rather than
  // `maskIdentifier`, because the latter asks the role and hands a privileged one the
  // value back untouched — which is what made the eye do nothing.
  //
  // It runs for a masked role too, over a value the server already masked. That is
  // deliberate and predates this change: if the server ever sent a full value to a role
  // that may not read it, the screen still would not print it.
  const onScreen = shown ? value : maskTail(value);

  return (
    <span className={cn('inline-flex items-center gap-1 text-caption tabular-nums text-ink', className)}>
      <span className="whitespace-nowrap">{onScreen}</span>
      {mayReveal && (
        <button
          type="button"
          onClick={() => setRevealed((previous) => !previous)}
          aria-label={revealed ? 'Hide value' : 'Reveal value'}
          aria-pressed={revealed}
          className={CONTROL}
        >
          {/* The glyph is the STATE, not the action: an open eye while the value is on
              screen, a struck-through eye while it is covered. The accessible name is
              the action ("Hide value"), because that is what pressing does, and
              `aria-pressed` carries the same state the glyph shows. */}
          {revealed ? <Icon.reveal size={14} aria-hidden /> : <Icon.conceal size={14} aria-hidden />}
        </button>
      )}
      {/* Only once the value is actually on screen: copying bullets is useless, and
          copying a value the person has not revealed would put it on the clipboard
          without it ever being shown. */}
      {shown && (
        <button
          type="button"
          aria-label="Copy value"
          className={CONTROL}
          onClick={() => {
            void navigator.clipboard?.writeText(value).then(
              () => toast.success(`${kind ?? 'Value'} copied`),
              () => toast.error('Could not copy'),
            );
          }}
        >
          <Icon.copy size={14} aria-hidden />
        </button>
      )}
    </span>
  );
}
