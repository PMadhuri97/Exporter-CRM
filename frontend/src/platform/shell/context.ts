/**
 * What a page tells the shell about itself (frontend-plan §7): its breadcrumb
 * trail. Pages call the hook; `layout/` reads the state. Kept in `platform/` so a
 * module never imports the layout to feed it.
 *
 * The hook is a no-op outside a `ShellProvider`, so a page renders the same in a
 * unit test as in the app. Search offers no actions and pages bind no keys of their
 * own (§7.5): actions live on the record.
 */

import { createContext, useContext, useEffect, useId, useRef } from 'react';

export interface Crumb {
  label: string;
  /** Where the crumb links; the last crumb (the page itself) has none. */
  to?: string;
}

export interface Registry<T> {
  owner: string;
  items: T[];
}

export interface ShellState {
  crumbs: Crumb[] | null;
  setCrumbs: (owner: string, crumbs: Crumb[] | null) => void;
}

const NOOP = () => undefined;
export const ShellContext = createContext<ShellState>({ crumbs: null, setCrumbs: NOOP });

export function upsert<T>(list: Registry<T>[], owner: string, items: T[] | null): Registry<T>[] {
  const rest = list.filter((entry) => entry.owner !== owner);
  return items ? [...rest, { owner, items }] : rest;
}

/** For the layout only: what pages have registered. */
export function useShellState(): Pick<ShellState, 'crumbs'> {
  const { crumbs } = useContext(ShellContext);
  return { crumbs };
}

/** Sets the page's breadcrumb trail for as long as the calling page is on screen. */
export function useCrumbs(crumbs: Crumb[] | null): void {
  const { setCrumbs } = useContext(ShellContext);
  const owner = useId();
  const latest = useRef(crumbs);
  latest.current = crumbs;
  const signature = JSON.stringify(crumbs);

  useEffect(() => {
    setCrumbs(owner, latest.current);
  }, [owner, setCrumbs, signature]);

  useEffect(() => () => setCrumbs(owner, null), [owner, setCrumbs]);
}
