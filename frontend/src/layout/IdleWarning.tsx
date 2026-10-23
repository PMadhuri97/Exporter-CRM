/**
 * "Are you still there?" — shown in every tab a minute before the inactivity timeout
 * (`AuthProvider`). Staying signed in counts as activity, so every other tab's warning
 * closes with it; closing the dialog any other way counts too, since it took a person to
 * do it. Doing nothing signs out every tab when the countdown reaches zero.
 */

import { Button, Dialog } from '@/components';
import { useAuth } from '@/platform/auth';

export function IdleWarning() {
  const { idleWarningSeconds, staySignedIn, logout } = useAuth();
  const open = typeof idleWarningSeconds === 'number';

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) staySignedIn();
      }}
      size="sm"
      title="Are you still there?"
      description={
        open
          ? `For your security you will be signed out in ${idleWarningSeconds} second${
              idleWarningSeconds === 1 ? '' : 's'
            }.`
          : undefined
      }
      footer={
        <>
          <Button onClick={() => void logout()}>Sign out</Button>
          <Button variant="primary" onClick={staySignedIn}>
            Stay signed in
          </Button>
        </>
      }
    />
  );
}
