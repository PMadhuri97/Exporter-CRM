/**
 * "This company cannot be identified yet" — IQ-7's completion list, seen from the
 * company itself (`remaining-work.md` R-28).
 *
 * Shown when the company holds neither a PAN nor a registration number
 * (`identity_type` is null). It says what would identify it, and whether a rule
 * requires it — a foreign company's registration number is IQ-7's requirement; an
 * Indian company's PAN is only worth having. It goes away by itself once the edit is
 * saved, because the server recomputes `identity_type` on every identifier edit
 * (R-16). The edit itself is the company panel's, so this offers no second form.
 */

import { Fingerprint } from 'lucide-react';

export interface IdentityGapNoticeProps {
  country: string | null;
  /** Whether this viewer may edit the company — otherwise it explains, nothing more. */
  canEdit: boolean;
}

export function IdentityGapNotice({ country, canEdit }: IdentityGapNoticeProps) {
  const code = (country ?? '').trim().toUpperCase();
  const [needed, required] = !code
    ? ['a country, and then the identifier that country uses', true]
    : code === 'IN'
      ? ['a PAN', false]
      : ['the registration number its own registrar issued', true];

  return (
    <div
      role="status"
      data-testid="identity-gap-notice"
      className={`flex gap-3 rounded-lg border p-4 text-sm ${
        required
          ? 'border-status-review/40 bg-status-review/10'
          : 'border-dashed border-border-strong bg-surface-subtle'
      }`}
    >
      <Fingerprint size={16} className="mt-0.5 shrink-0 text-ink-faint" />
      <p className="text-ink">
        <span className="font-medium">
          This company cannot be identified yet: it holds no PAN and no registration
          number.
        </span>{' '}
        <span className="text-ink-muted">
          It needs {needed}
          {required
            ? ' — required for a company outside India (IQ-7).'
            : ' — not required, but it cannot be matched by identifier without one.'}
          {canEdit ? ' Add it with Edit below.' : ''}
        </span>
      </p>
    </div>
  );
}
