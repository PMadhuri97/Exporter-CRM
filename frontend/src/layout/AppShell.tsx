import { LogOut } from 'lucide-react';
import { Outlet } from 'react-router-dom';

import { useAuth, useCurrentUser } from '@/platform/auth';

import { Sidebar } from './Sidebar';

function TopBar() {
  const user = useCurrentUser();
  const { logout } = useAuth();

  return (
    <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-border bg-surface px-6">
      <div className="text-right">
        <p className="text-sm font-medium text-ink">
          {user.full_name ?? user.email}
        </p>
        <p className="text-xs capitalize text-ink-faint">
          {user.role.toLowerCase()}
        </p>
      </div>
      <button
        type="button"
        onClick={() => void logout()}
        aria-label="Sign out"
        className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink"
      >
        <LogOut size={16} />
      </button>
    </header>
  );
}

export function AppShell() {
  return (
    <div className="flex h-screen bg-surface-subtle">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
