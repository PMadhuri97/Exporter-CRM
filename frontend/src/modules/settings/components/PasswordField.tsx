import { useId, useState } from 'react';

import { RequiredMark } from '@/components';
import { Icon } from '@/design/icons';

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
  'bg-line-strong',
  'bg-negative-solid',
  'bg-negative-solid',
  'bg-attention-solid',
  'bg-progress-solid',
  'bg-positive-solid',
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
      <label htmlFor={id} className="mb-1 block text-caption font-medium text-ink-2">
        {label}
        {required && <RequiredMark />}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          required={required}
          autoComplete={autoComplete}
          onChange={(event) => onChange(event.target.value)}
          className="input pr-10"
        />
        <button
          type="button"
          onClick={() => setVisible((shown) => !shown)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-3 transition-colors hover:text-ink"
        >
          {visible ? <Icon.conceal size={15} /> : <Icon.reveal size={15} />}
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
                    : 'bg-sunken'
                }`}
              />
            ))}
          </div>
          <p className="mt-1.5 text-caption text-ink-2" aria-live="polite">
            {strength.label}
            {strength.missing.length > 0 && (
              <span className="text-ink-3">
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
