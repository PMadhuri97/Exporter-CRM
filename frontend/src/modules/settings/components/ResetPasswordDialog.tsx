import { X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useResetUserPassword } from '../hooks';
import { assessPassword } from '../passwordStrength';
import type { AdminUser } from '../types';

import { PasswordField } from './PasswordField';

interface ResetPasswordDialogProps {
  user: AdminUser;
  onClose: () => void;
}

export function ResetPasswordDialog({ user, onClose }: ResetPasswordDialogProps) {
  const [password, setPassword] = useState('');
  const mutation = useResetUserPassword();
  const canSubmit = assessPassword(password).meetsPolicy && !mutation.isPending;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync({ userId: user.id, newPassword: password });
      toast.success('Password reset — every session for that account is signed out');
      onClose();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Could not reset password',
      );
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Reset password"
        className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-lg"
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Reset password</h2>
            <p className="text-xs text-ink-muted">
              For {user.email}. You will need to pass this on to them yourself —
              nothing is emailed.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-ink-faint hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <PasswordField
            label="New password"
            value={password}
            onChange={setPassword}
            showStrength
            required
          />
          <p className="rounded-lg bg-surface-sunken px-3 py-2 text-xs text-ink-muted">
            Every active session for this account is revoked, so anyone already
            signed in as them is signed out.
          </p>
          <div className="mt-1 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink-muted hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {mutation.isPending ? 'Resetting…' : 'Reset password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
