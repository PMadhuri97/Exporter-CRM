/**
 * The shell (frontend-plan §7.1): the rail, the context bar (breadcrumbs, ⌘K, the
 * avatar menu), the page, and on a narrow screen a bottom bar in place of the rail.
 * The command bar, the `?` sheet and the keyboard live here too, and all of them —
 * like the router — read the module table, so a role is offered the same modules
 * in every one of them.
 */

import { Suspense, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { Skeleton } from '@/components';
import { NoWorkspaceFrame, useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';
import { ShellProvider, useShellState } from '@/platform/shell';

import { BottomBar } from './BottomBar';
import { CommandBar } from './CommandBar';
import { ContextBar } from './ContextBar';
import { Rail } from './Rail';
import { ShortcutSheet } from './Shortcuts';
import { useGlobalShortcuts } from './useGlobalShortcuts';

/** While a screen's code loads (each one is its own chunk, G7): shaped, not a spinner. */
function ScreenLoading() {
  return (
    <div className="space-y-3" aria-hidden>
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="mt-6 h-40" />
    </div>
  );
}

function Workspace() {
  const { role } = useCurrentUser();
  const { shortcuts } = useShellState();
  const [commandOpen, setCommandOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  useGlobalShortcuts({
    role,
    openCommand: () => setCommandOpen(true),
    openSheet: () => setSheetOpen(true),
    pageShortcuts: shortcuts,
  });

  return (
    <div className="flex h-screen bg-paper">
      <Rail role={role} />
      <div className="flex min-w-0 flex-1 flex-col">
        <ContextBar role={role} onOpenCommand={() => setCommandOpen(true)} />
        <main className="flex-1 overflow-y-auto px-4 pb-24 pt-6 sm:px-8 lg:pb-10">
          <div className="mx-auto max-w-[90rem]">
            <Suspense fallback={<ScreenLoading />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <BottomBar role={role} />
      <CommandBar open={commandOpen} onOpenChange={setCommandOpen} role={role} />
      <ShortcutSheet open={sheetOpen} onOpenChange={setSheetOpen} role={role} />
    </div>
  );
}

export function AppShell() {
  const hasWorkspace = useCan('crm.read');

  // The API user, or a role nobody listed: no rail and no CRM words (R-33, G1).
  // The routes inside are still gated; only My profile renders here.
  if (!hasWorkspace) {
    return (
      <NoWorkspaceFrame>
        <Suspense fallback={<ScreenLoading />}>
          <Outlet />
        </Suspense>
      </NoWorkspaceFrame>
    );
  }

  return (
    <ShellProvider>
      <Workspace />
    </ShellProvider>
  );
}
