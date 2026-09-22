import { Eye, EyeOff } from 'lucide-react';
import { useState } from 'react';

import { useCurrentUser } from '@/platform/auth';

import { canReveal, maskIdentifier } from './maskIdentifier';

interface MaskedValueProps {
  value: string | null | undefined;
  isOwner?: boolean;
  className?: string;
}

/**
 * Renders `value`, masked or not per the role capability matrix. The reveal
 * eye icon is only rendered at all when this user could ever reveal this
 * value — a role that can't reveal gets no icon, not a disabled one, per
 * the design principle in `docs/exporter-crm-frontend-tickets.md`
 * ("a disabled eye icon would still leak 'this data exists, you're just not
 * allowed'").
 */
export function MaskedValue({
  value,
  isOwner = false,
  className,
}: MaskedValueProps) {
  const { role } = useCurrentUser();
  const [revealed, setRevealed] = useState(false);

  if (value === null || value === undefined) {
    return <span className={className}>—</span>;
  }

  const mayReveal = canReveal(role, isOwner);
  const display =
    mayReveal && revealed ? value : maskIdentifier(value, { role, isOwner });

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono tabular-nums ${className ?? ''}`}
    >
      {display}
      {mayReveal && (
        <button
          type="button"
          onClick={() => setRevealed((prev) => !prev)}
          aria-label={revealed ? 'Hide value' : 'Reveal value'}
          aria-pressed={revealed}
          className="text-ink-faint hover:text-ink-muted transition-colors"
        >
          {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      )}
    </span>
  );
}
