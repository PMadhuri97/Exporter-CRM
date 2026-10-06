/** Holds what pages register for the shell (see `context.ts`). */

import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { ShellContext, upsert, type Crumb, type Registry, type ShellState } from './context';

export function ShellProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbList] = useState<Registry<Crumb>[]>([]);

  const setCrumbs = useCallback(
    (owner: string, items: Crumb[] | null) => setCrumbList((list) => upsert(list, owner, items)),
    [],
  );

  const value = useMemo<ShellState>(
    () => ({
      // The most recently registered trail wins: the deepest page that set one.
      crumbs: crumbs.length > 0 ? crumbs[crumbs.length - 1]!.items : null,
      setCrumbs,
    }),
    [crumbs, setCrumbs],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
