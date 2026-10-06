import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { buttonClasses } from '@/components';
import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import { useAuth } from '@/platform/auth';

/**
 * The frame for a signed-in user with no CRM capability — the API user, or a role
 * nobody listed (§4.3). No navigation, no CRM words and no counts: the brand, the page, and
 * a way to sign out. Only routes every role may use (Settings → My profile) render
 * inside it; everything else is gated and renders `NotFound`.
 */
export function NoWorkspaceFrame({ children }: { children: ReactNode }) {
  const { logout } = useAuth();
  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
        <Link to="/" className="rounded">
          <BrandMark />
        </Link>
        <button
          type="button"
          onClick={() => void logout()}
          className={buttonClasses({ variant: 'subtle', size: 'sm' })}
        >
          <Icon.signOut size={16} aria-hidden />
          Sign out
        </button>
      </header>
      <main className="flex-1 px-4 py-5 sm:px-6 sm:py-6">
        <div className="mx-auto max-w-3xl">{children}</div>
      </main>
    </div>
  );
}

/** What `/` shows a user with no workspace. */
export function NoWorkspace() {
  return (
    <div className="mx-auto mt-10 max-w-lg rounded border border-line bg-surface px-6 py-10 text-center">
      <h1 className="text-title font-semibold text-ink">No workspace yet</h1>
      <p className="mt-2 text-body text-ink-2">
        Your account doesn&apos;t have access to a workspace yet. Ask an administrator.
      </p>
      <Link to="/settings" className={buttonClasses({ variant: 'secondary', className: 'mt-6' })}>
        My profile
      </Link>
    </div>
  );
}
