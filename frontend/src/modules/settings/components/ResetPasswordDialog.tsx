import { useState } from 'react';
import { toast } from 'sonner';

import { SidePanel } from '@/components';

import { useResetUserPassword } from '../hooks';
import { assessPassword } from '../passwordStrength';
import type { AdminUser } from '../types';

import { PasswordField } from './PasswordField';

interface ResetPasswordDialogProps {
  user: AdminUser;
  onClose: () => void;
}

/** Reset someone's password — a composer; nothing is emailed, the admin passes it on. */
export function ResetPasswordDialog({ user, onClose }: ResetPasswordDialogProps) {
  const [password, setPassword] = useState('');
  const mutation = useResetUserPassword();

  return (
    <SidePanel
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Reset password"
      description={`For ${user.email}. You will need to pass this on to them yourself — nothing is emailed.`}
      submitLabel="Reset password"
      pending={mutation.isPending}
      error={mutation.error}
      submitDisabled={!assessPassword(password).meetsPolicy}
      onSubmit={() =>
        mutation.mutate(
          { userId: user.id, newPassword: password },
          {
            onSuccess: () => {
              toast.success('Password reset — every session for that account is signed out');
              onClose();
            },
          },
        )
      }
    >
      <PasswordField
        label="New password"
        value={password}
        onChange={setPassword}
        showStrength
        required
      />
      <p className="text-secondary text-ink-3">
        Every active session for this account is revoked, so anyone already signed in as them
        is signed out.
      </p>
    </SidePanel>
  );
}
