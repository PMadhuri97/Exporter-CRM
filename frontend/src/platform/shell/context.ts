/**
 * What a page tells the shell about itself (frontend-plan §7): its breadcrumb
 * trail, the actions ⌘K should offer "on this company / deal", and its own
 * keyboard shortcuts. Pages call the hooks; `layout/` reads the state. Kept in
 * `platform/` so a module never imports the layout to feed it.
 *
 * Every hook is a no-op outside a `ShellProvider`, so a page renders the same in
 * a unit test as in the app. Actions and shortcuts must come only from served
 * data (`allowed_*`, `can_*`) — the shell lists what it is given and decides
 * nothing (§4.5).
 */

import { createContext, useContext, useEffect, useId, useRef } from 'react';

export interface Crumb {
  label: string;
  /** Where the crumb links; the last crumb (the page itself) has none. */
  to?: string;
}

export interface CommandAction {
  id: string;
  label: string;
  /** A key that does the same on the page, shown beside the action. */
  shortcut?: string;
  /** Extra words ⌘K should match on ("call", "phone" for "Log a call"). */
  keywords?: string[];
  run: () => void;
}

export interface PageShortcut {
  /** A single key, as `KeyboardEvent.key` reports it (`l`, `c`, `j`). */
  key: string;
  label: string;
  run: () => void;
}

export interface Registry<T> {
  owner: string;
  items: T[];
}

export interface ShellState {
  crumbs: Crumb[] | null;
  actions: CommandAction[];
  shortcuts: PageShortcut[];
  setCrumbs: (owner: string, crumbs: Crumb[] | null) => void;
  setActions: (owner: string, actions: CommandAction[] | null) => void;
  setShortcuts: (owner: string, shortcuts: PageShortcut[] | null) => void;
}

const NOOP = () => undefined;
export const ShellContext = createContext<ShellState>({
  crumbs: null,
  actions: [],
  shortcuts: [],
  setCrumbs: NOOP,
  setActions: NOOP,
  setShortcuts: NOOP,
});

export function upsert<T>(list: Registry<T>[], owner: string, items: T[] | null): Registry<T>[] {
  const rest = list.filter((entry) => entry.owner !== owner);
  return items ? [...rest, { owner, items }] : rest;
}

/** For the layout only: what pages have registered. */
export function useShellState(): Pick<ShellState, 'crumbs' | 'actions' | 'shortcuts'> {
  const { crumbs, actions, shortcuts } = useContext(ShellContext);
  return { crumbs, actions, shortcuts };
}

/**
 * Registers `items` under this component while it is mounted. `signature` decides
 * when the list really changed (labels and ids, not function identity), and the
 * latest `run` functions are always the ones called.
 */
function useRegistration<T extends object>(
  register: (owner: string, items: T[] | null) => void,
  items: T[] | null,
  signature: string,
) {
  const owner = useId();
  const latest = useRef(items);
  latest.current = items;

  useEffect(() => {
    const current = latest.current;
    register(
      owner,
      current
        ? current.map((item, index) =>
            'run' in item
              ? { ...item, run: () => (latest.current?.[index] as { run?: () => void })?.run?.() }
              : item,
          )
        : null,
    );
  }, [owner, register, signature]);

  useEffect(() => () => register(owner, null), [owner, register]);
}

/** Sets the context bar's trail for as long as the calling page is on screen. */
export function useCrumbs(crumbs: Crumb[] | null): void {
  const { setCrumbs } = useContext(ShellContext);
  useRegistration<Crumb>(setCrumbs, crumbs, JSON.stringify(crumbs));
}

/** Offers `actions` in ⌘K's "On this page" group while the caller is mounted. */
export function useCommandActions(actions: CommandAction[]): void {
  const { setActions } = useContext(ShellContext);
  useRegistration<CommandAction>(
    setActions,
    actions,
    JSON.stringify(actions.map(({ id, label, shortcut }) => [id, label, shortcut])),
  );
}

/** Binds single keys on the page (listed in the `?` sheet) while the caller is mounted. */
export function usePageShortcuts(shortcuts: PageShortcut[]): void {
  const { setShortcuts } = useContext(ShellContext);
  useRegistration<PageShortcut>(
    setShortcuts,
    shortcuts,
    JSON.stringify(shortcuts.map(({ key, label }) => [key, label])),
  );
}
