import { LogOut } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { buttonClasses } from '@/components';
import { useAuth } from '@/platform/auth';

/**
 * The frame for a signed-in user with no CRM capability — the API user, or a role
 * nobody listed (§4.3). No rail, no CRM words and no counts: the brand, the page, and
 * a way to sign out. Only routes every role may use (Settings → My profile) render
 * inside it; everything else is gated and renders `NotFound`.
 */
export function NoWorkspaceFrame({ children }: { children: ReactNode }) {
  const { logout } = useAuth();
  return (
    <div className="flex min-h-screen flex-col bg-surface-subtle">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white dark:text-surface">
            A
          </span>
          <span className="text-sm font-semibold text-ink">Aner Labs</span>
        </Link>
        <button
          type="button"
          onClick={() => void logout()}
          className={buttonClasses({ variant: 'ghost', size: 'sm' })}
        >
          <LogOut size={15} />
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
    <div className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
      <h1 className="text-lg font-semibold text-ink">No workspace yet</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Your account doesn&apos;t have access to a workspace yet. Ask an administrator.
      </p>
      <Link to="/settings" className={buttonClasses({ variant: 'secondary', className: 'mt-6' })}>
        My profile
      </Link>
    </div>
  );
}
