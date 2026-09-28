import { useState } from 'react';
import { toast } from 'sonner';

import { useAuth, useCurrentUser } from '@/platform/auth';

import {
  useChangeOwnPassword,
  useOwnSessions,
  useRevokeOwnSession,
  useUpdateOwnProfile,
} from '../hooks';
import { assessPassword } from '../passwordStrength';
import { ROLE_CHIP_CLASS, ROLE_DESCRIPTION } from '../roles';

import { PasswordField } from './PasswordField';

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function Card({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      <p className="mb-4 text-xs text-ink-muted">{description}</p>
      {children}
    </section>
  );
}

export function MyProfileTab() {
  const user = useCurrentUser();
  const { logout } = useAuth();

  const [fullName, setFullName] = useState(user.full_name ?? '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const profileMutation = useUpdateOwnProfile();
  const passwordMutation = useChangeOwnPassword();
  const sessionsQuery = useOwnSessions();
  const revokeMutation = useRevokeOwnSession();

  const nameChanged = fullName.trim() !== (user.full_name ?? '');
  const passwordReady =
    currentPassword.length > 0 && assessPassword(newPassword).meetsPolicy;

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    try {
      await profileMutation.mutateAsync({
        full_name: fullName.trim() === '' ? null : fullName.trim(),
      });
      // `useCurrentUser` is populated once at sign-in, so the header would keep
      // showing the old name until the next page load. Say so rather than
      // silently disagreeing with the top bar.
      toast.success('Name saved — it will appear everywhere after your next sign-in');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save your name');
    }
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    try {
      await passwordMutation.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success('Password changed — please sign in again');
      // The server revoked every refresh token, including this tab's, so
      // staying signed in here would only work until the access token expired.
      // Ending the session now matches what actually happened.
      await logout();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Could not change your password',
      );
    }
  }

  const sessions = sessionsQuery.data?.sessions ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Your details" description="The name shown beside your sign-in.">
        <form onSubmit={saveProfile} className="flex flex-col gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-muted">
              Email
            </label>
            <p className="rounded-lg bg-surface-sunken px-3 py-2 font-mono text-sm text-ink-muted">
              {user.email}
            </p>
          </div>
          <div>
            <label
              htmlFor="profile-name"
              className="mb-1 block text-xs font-medium text-ink-muted"
            >
              Full name
            </label>
            <input
              id="profile-name"
              type="text"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-muted">
              Role
            </label>
            <span
              className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_CHIP_CLASS[user.role]}`}
            >
              {user.role}
            </span>
            <p className="mt-1.5 text-xs text-ink-faint">
              {ROLE_DESCRIPTION[user.role]} Only an administrator can change this.
            </p>
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!nameChanged || profileMutation.isPending}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {profileMutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title="Password"
        description="Changing it signs you out everywhere, including here."
      >
        <form onSubmit={changePassword} className="flex flex-col gap-3">
          <PasswordField
            label="Current password"
            value={currentPassword}
            onChange={setCurrentPassword}
            autoComplete="current-password"
            required
          />
          <PasswordField
            label="New password"
            value={newPassword}
            onChange={setNewPassword}
            showStrength
            required
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!passwordReady || passwordMutation.isPending}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {passwordMutation.isPending ? 'Changing…' : 'Change password'}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title="Active sessions"
        description="Each row is a signed-in session. Only times are recorded — no device or location is stored, so none is shown."
      >
        {sessionsQuery.isLoading && (
          <div className="h-16 animate-pulse rounded-lg bg-surface-sunken" />
        )}
        {sessionsQuery.isError && (
          <p className="text-sm text-status-failed">Could not load your sessions.</p>
        )}
        {!sessionsQuery.isLoading && sessions.length === 0 && (
          <p className="text-sm text-ink-muted">No active sessions.</p>
        )}
        <ul className="divide-y divide-border">
          {sessions.map((session) => (
            <li
              key={session.id}
              className="flex items-center justify-between gap-3 py-2.5"
            >
              <div>
                <p className="text-sm text-ink">
                  Signed in {formatDateTime(session.created_at)}
                </p>
                <p className="text-xs text-ink-faint">
                  Expires {formatDateTime(session.expires_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await revokeMutation.mutateAsync(session.id);
                    toast.success('Session revoked');
                  } catch (error) {
                    toast.error(
                      error instanceof Error
                        ? error.message
                        : 'Could not revoke that session',
                    );
                  }
                }}
                className="rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-ink-faint">
          Revoking the session you are using now ends it when your current access
          token expires, not instantly.
        </p>
      </Card>
    </div>
  );
}
