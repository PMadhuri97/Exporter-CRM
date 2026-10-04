/**
 * Binds the keyboard for the shell (frontend-plan §7.4) — see `Shortcuts.tsx` for
 * what each key does and the `?` sheet that lists them.
 */

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import type { UserRole } from '@/lib/api/types';
import { hasModifier, isTypingTarget, type PageShortcut } from '@/platform/shell';
import { navRowsFor } from '@/routes/modules';

/** How long `g` waits for its second key. */
const CHORD_MS = 1500;

export function useGlobalShortcuts({
  role,
  openCommand,
  openSheet,
  pageShortcuts,
}: {
  role: UserRole;
  openCommand: () => void;
  openSheet: () => void;
  pageShortcuts: PageShortcut[];
}) {
  const navigate = useNavigate();
  const chordAt = useRef(0);
  const latest = useRef({ role, openCommand, openSheet, pageShortcuts, navigate });
  latest.current = { role, openCommand, openSheet, pageShortcuts, navigate };

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const { role, openCommand, openSheet, pageShortcuts, navigate } = latest.current;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        openCommand();
        return;
      }
      if (event.defaultPrevented || hasModifier(event) || isTypingTarget(event.target)) return;
      // A dialog or sheet owns the keyboard while it is open.
      if (document.querySelector('[role="dialog"][data-state="open"]')) return;

      const key = event.key;
      if (Date.now() - chordAt.current < CHORD_MS) {
        chordAt.current = 0;
        const row = navRowsFor(role).find((candidate) => candidate.shortcut === key.toLowerCase());
        if (row) {
          event.preventDefault();
          navigate(row.to);
        }
        return;
      }
      if (key === 'g') {
        chordAt.current = Date.now();
        return;
      }
      if (key === '?') {
        event.preventDefault();
        openSheet();
        return;
      }
      if (key === '/') {
        const search = document.querySelector<HTMLElement>('[data-page-search]');
        if (search) {
          event.preventDefault();
          search.focus();
        }
        return;
      }
      const own = pageShortcuts.find((shortcut) => shortcut.key === key);
      if (own) {
        event.preventDefault();
        own.run();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
}
