import { X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useCurrentUser } from '@/platform/auth';

import { useCreateUser, useUpdateUser } from '../hooks';
import { assessPassword } from '../passwordStrength';
import { ROLE_DESCRIPTION, ROLE_OPTIONS } from '../roles';
import type { AdminUser } from '../types';

import { PasswordField } from './PasswordField';

interface UserFormDialogProps {
  /** Absent = create a new account; present = edit this one. */
  user?: AdminUser;
  onClose: () => void;
}

export function UserFormDialog({ user, onClose }: UserFormDialogProps) {
  const isEdit = user !== undefined;
  const currentUser = useCurrentUser();
  const isSelf = isEdit && user.id === currentUser.id;

  const [email, setEmail] = useState(user?.email ?? '');
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [role, setRole] = useState<AdminUser['role']>(user?.role ?? 'OPERATIONS');
  const [password, setPassword] = useState('');

  const createMutation = useCreateUser();
  const updateMutation = useUpdateUser();
  const pending = createMutation.isPending || updateMutation.isPending;

  const passwordOk = assessPassword(password).meetsPolicy;
  const canSubmit = isEdit
    ? !pending
    : !pending && email.trim().length > 0 && passwordOk;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const name = fullName.trim() === '' ? null : fullName.trim();

    try {
      if (isEdit) {
        await updateMutation.mutateAsync({
          userId: user.id,
          // Never send `role` for your own account: the server refuses it with
          // a 409, so offering it would be a button that cannot work.
          body: isSelf ? { full_name: name } : { full_name: name, role },
        });
        toast.success('User updated');
      } else {
        await createMutation.mutateAsync({
          email: email.trim(),
          password,
          full_name: name,
          role,
        });
        toast.success('User created');
      }
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save user');
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isEdit ? 'Edit user' : 'Add user'}
        className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-lg"
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">
              {isEdit ? 'Edit user' : 'Add user'}
            </h2>
            <p className="text-xs text-ink-muted">
              {isEdit
                ? 'Change the display name and role for this account.'
                : 'Creates a working account with the role you choose.'}
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
          <div>
            <label
              htmlFor="user-email"
              className="mb-1 block text-xs font-medium text-ink-muted"
            >
              Email
            </label>
            <input
              id="user-email"
              type="email"
              value={email}
              required
              disabled={isEdit}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {isEdit && (
              <p className="mt-1 text-xs text-ink-faint">
                Email cannot be changed — no address-confirmation flow exists
                yet, so a silent change would lock the account out.
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="user-name"
              className="mb-1 block text-xs font-medium text-ink-muted"
            >
              Full name
            </label>
            <input
              id="user-name"
              type="text"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            />
          </div>

          <div>
            <label
              htmlFor="user-role"
              className="mb-1 block text-xs font-medium text-ink-muted"
            >
              Role
            </label>
            <select
              id="user-role"
              value={role}
              disabled={isSelf}
              onChange={(event) =>
                setRole(event.target.value as AdminUser['role'])
              }
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              {ROLE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-ink-faint">
              {isSelf
                ? 'You cannot change your own role — ask another administrator.'
                : ROLE_DESCRIPTION[role]}
            </p>
          </div>

          {!isEdit && (
            <PasswordField
              label="Initial password"
              value={password}
              onChange={setPassword}
              showStrength
              required
            />
          )}

          <div className="mt-2 flex justify-end gap-2">
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
              {pending ? 'Saving…' : isEdit ? 'Save changes' : 'Create user'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
