import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  SidePanel,
  DetailRow,
  Editable,
  EmptyLine,
  Panel,
  Skeleton,
  Tag,
  RequiredNote,
} from '@/components';
import { formatDateTime } from '@/lib/format';
import { roleLabel, useAuth, useCurrentUser } from '@/platform/auth';

import {
  useChangeOwnPassword,
  useOwnSessions,
  useRevokeOwnSession,
  useUpdateOwnProfile,
} from '../hooks';
import { assessPassword } from '../passwordStrength';
import { ROLE_DESCRIPTION } from '../roles';

import { PasswordField } from './PasswordField';

/** "Change password" (§8.9): a composer with the strength meter; it ends this session too. */
function ChangePassword({ onClose }: { onClose: () => void }) {
  const { logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const mutation = useChangeOwnPassword();
  const ready = currentPassword.length > 0 && assessPassword(newPassword).meetsPolicy;

  return (
    <SidePanel
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Change your password"
      description="Changing it signs you out everywhere, including here."
      submitLabel="Change password"
      pending={mutation.isPending}
      error={mutation.error}
      submitDisabled={!ready}
      onSubmit={() =>
        mutation.mutate(
          { current_password: currentPassword, new_password: newPassword },
          {
            onSuccess: async () => {
              toast.success('Password changed — please sign in again');
              // The server revoked every refresh token, including this tab's, so
              // staying signed in here would only work until the access token
              // expired. Ending the session now matches what actually happened.
              await logout();
            },
          },
        )
      }
    >
      <RequiredNote />
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
    </SidePanel>
  );
}

export function MyProfileTab() {
  const user = useCurrentUser();
  // `useCurrentUser` is populated once at sign-in, so a saved name is kept here
  // until the next sign-in brings it back from the server.
  const [savedName, setSavedName] = useState(user.full_name ?? '');
  const [changingPassword, setChangingPassword] = useState(false);

  const profileMutation = useUpdateOwnProfile();
  const sessionsQuery = useOwnSessions();
  const revokeMutation = useRevokeOwnSession();
  const sessions = sessionsQuery.data?.sessions ?? [];

  return (
    <div className="space-y-4">
      <Panel title="Your details">
        <dl>
          <DetailRow label="Email">
            <span className="text-secondary text-ink-2">{user.email}</span>
          </DetailRow>
          <DetailRow label="Full name">
            <Editable
              label="Full name"
              value={savedName}
              onSave={async (next) => {
                const name = next.trim();
                await profileMutation.mutateAsync({ full_name: name === '' ? null : name });
                setSavedName(name);
                // The context bar keeps the old name until the next sign-in; say so
                // rather than silently disagree with it.
                toast.success('Name saved — it will appear everywhere after your next sign-in');
              }}
            />
          </DetailRow>
          <DetailRow label="Role">
            <Tag tone="ink">{roleLabel(user.role)}</Tag>
            <p className="mt-1.5 text-caption text-ink-3">
              {ROLE_DESCRIPTION[user.role]} Only an administrator can change this.
            </p>
          </DetailRow>
        </dl>
      </Panel>

      <Panel
        title="Password"
        actions={
          <Button size="sm" onClick={() => setChangingPassword(true)}>
            Change password
          </Button>
        }
      >
        <p className="text-secondary text-ink-3">
          A new password needs at least 8 characters, an uppercase letter and a digit; the
          meter says what is still missing as you type.
        </p>
      </Panel>
      {changingPassword && <ChangePassword onClose={() => setChangingPassword(false)} />}

      <Panel title="Active sessions">
        {sessionsQuery.isLoading ? (
          <Skeleton className="h-16" />
        ) : sessionsQuery.isError ? (
          <p role="alert" className="text-body text-negative">
            Could not load your sessions.
          </p>
        ) : sessions.length === 0 ? (
          <EmptyLine>No active sessions.</EmptyLine>
        ) : (
          <ul className="divide-y divide-line">
            {sessions.map((session) => (
              <li key={session.id} className="flex items-center justify-between gap-3 py-2.5">
                <div>
                  <p className="text-body text-ink">Signed in {formatDateTime(session.created_at)}</p>
                  <p className="text-caption text-ink-3">Expires {formatDateTime(session.expires_at)}</p>
                </div>
                <Button
                  size="sm"
                  variant="subtle"
                  onClick={async () => {
                    try {
                      await revokeMutation.mutateAsync(session.id);
                      toast.success('Session revoked');
                    } catch (error) {
                      toast.error(
                        error instanceof Error ? error.message : 'Could not revoke that session',
                      );
                    }
                  }}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-caption text-ink-3">
          Revoking the session you are using now ends it when your current access token
          expires, not instantly.
        </p>
      </Panel>
    </div>
  );
}
