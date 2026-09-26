import { Eye, EyeOff } from 'lucide-react';
import { useId, useState } from 'react';

import { assessPassword } from '../passwordStrength';

interface PasswordFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Show the strength meter. Off for "current password" fields, where
   * grading a password the user already has is noise. */
  showStrength?: boolean;
  autoComplete?: string;
  required?: boolean;
}

const BAR_COLOR = [
  'bg-border-strong',
  'bg-status-failed',
  'bg-status-failed',
  'bg-status-review',
  'bg-brand-500',
  'bg-status-passed',
] as const;

export function PasswordField({
  label,
  value,
  onChange,
  showStrength = false,
  autoComplete = 'new-password',
  required = false,
}: PasswordFieldProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const strength = assessPassword(value);

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-ink-muted">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          required={required}
          autoComplete={autoComplete}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-lg border border-border px-3 py-2 pr-10 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        />
        <button
          type="button"
          onClick={() => setVisible((shown) => !shown)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-faint transition-colors hover:text-ink"
        >
          {visible ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>

      {showStrength && value.length > 0 && (
        <div className="mt-2">
          <div className="flex gap-1" role="presentation">
            {[1, 2, 3, 4, 5].map((step) => (
              <span
                key={step}
                className={`h-1 flex-1 rounded-full ${
                  step <= strength.score
                    ? BAR_COLOR[strength.score]
                    : 'bg-surface-sunken'
                }`}
              />
            ))}
          </div>
          <p className="mt-1.5 text-xs text-ink-muted" aria-live="polite">
            {strength.label}
            {strength.missing.length > 0 && (
              <span className="text-ink-faint">
                {' — still needs '}
                {strength.missing.join(', ')}
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
