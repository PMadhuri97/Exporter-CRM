/**
 * The shell's keyboard (frontend-plan §7.5): `/` and Ctrl+K open search, Ctrl+/
 * lists the shortcuts. Esc is each panel's, menu's and dialog's own. No chords and
 * no single-letter actions; `/` never fires while someone is typing.
 */

import { useEffect, useRef } from 'react';

import { hasModifier, isTypingTarget } from '@/platform/shell';

export function useGlobalShortcuts({
  openSearch,
  openShortcuts,
}: {
  openSearch: () => void;
  openShortcuts: () => void;
}) {
  const latest = useRef({ openSearch, openShortcuts });
  latest.current = { openSearch, openShortcuts };

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const { openSearch, openShortcuts } = latest.current;
      const withMod = event.metaKey || event.ctrlKey;
      if (withMod && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        openSearch();
        return;
      }
      if (withMod && !event.altKey && event.key === '/') {
        event.preventDefault();
        openShortcuts();
        return;
      }
      if (event.defaultPrevented || hasModifier(event) || isTypingTarget(event.target)) return;
      // A dialog or side panel owns the keyboard while it is open.
      if (document.querySelector('[role="dialog"][data-state="open"]')) return;
      if (event.key === '/') {
        event.preventDefault();
        openSearch();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
}
