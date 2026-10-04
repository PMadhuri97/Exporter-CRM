/** Holds what pages register for the shell (see `context.ts`). */

import { useCallback, useMemo, useState, type ReactNode } from 'react';

import {
  ShellContext,
  upsert,
  type CommandAction,
  type Crumb,
  type PageShortcut,
  type Registry,
  type ShellState,
} from './context';

export function ShellProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbList] = useState<Registry<Crumb>[]>([]);
  const [actions, setActionList] = useState<Registry<CommandAction>[]>([]);
  const [shortcuts, setShortcutList] = useState<Registry<PageShortcut>[]>([]);

  const setCrumbs = useCallback(
    (owner: string, items: Crumb[] | null) => setCrumbList((list) => upsert(list, owner, items)),
    [],
  );
  const setActions = useCallback(
    (owner: string, items: CommandAction[] | null) => setActionList((list) => upsert(list, owner, items)),
    [],
  );
  const setShortcuts = useCallback(
    (owner: string, items: PageShortcut[] | null) => setShortcutList((list) => upsert(list, owner, items)),
    [],
  );

  const value = useMemo<ShellState>(
    () => ({
      // The most recently registered trail wins: the deepest page that set one.
      crumbs: crumbs.length > 0 ? crumbs[crumbs.length - 1]!.items : null,
      actions: actions.flatMap((entry) => entry.items),
      shortcuts: shortcuts.flatMap((entry) => entry.items),
      setCrumbs,
      setActions,
      setShortcuts,
    }),
    [crumbs, actions, shortcuts, setCrumbs, setActions, setShortcuts],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
