/**
 * An identifier — PAN, GSTIN, IEC, CIN, a registration number (frontend-plan §6.6).
 * Replaces `MaskedValue` everywhere; the one component that owns the masking rule
 * on screen.
 *
 * - Set in mono, so characters line up and read one by one.
 * - The eye exists **only** for a role that may reveal (`identifiers.reveal`). A
 *   masked role gets no eye at all — "a disabled eye icon would still leak 'this
 *   data exists, you're just not allowed'" (architecture §9). The server already
 *   sends masked roles masked values; the bullets here repeat that.
 * - Copy is offered **only** where the full value is on screen — never beside
 *   bullets: copying them is useless, and the button would invite the question.
 *
 * Open question (reported, not decided here): a role that may reveal
 * already reads identifiers in full, so its eye changes nothing visible. Either the
 * eye goes, or those roles read masked until they reveal (frontend-plan §6.6).
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { useCurrentUser } from '@/platform/auth';

import { canReveal, maskIdentifier } from './maskIdentifier';

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
  // What is on screen is the full value for a role that may reveal (see above).
  const fullOnScreen = mayReveal;

  return (
    <span className={cn('inline-flex items-center gap-1 font-mono text-data tabular-nums text-ink', className)}>
      {/* Unchanged from MaskedValue: a role that may reveal reads the value in full
          ("never masks PAN for COMPLIANCE"); every other role reads it masked. */}
      <span>{shown ? value : maskIdentifier(value, { role })}</span>
      {mayReveal && (
        <button
          type="button"
          onClick={() => setRevealed((previous) => !previous)}
          aria-label={revealed ? 'Hide value' : 'Reveal value'}
          aria-pressed={revealed}
          className={CONTROL}
        >
          {revealed ? <Icon.conceal size={14} aria-hidden /> : <Icon.reveal size={14} aria-hidden />}
        </button>
      )}
      {fullOnScreen && (
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
