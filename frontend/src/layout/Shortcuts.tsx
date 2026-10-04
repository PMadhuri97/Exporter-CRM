/**
 * The `?` sheet, and the keyboard (frontend-plan §7.4): ⌘K / Ctrl K opens the command bar from
 * anywhere; `g` then a letter goes to one of **this role's** modules; `/` focuses
 * the page's search; `?` opens the sheet listing this role's keys. A page adds its
 * own single keys with `usePageShortcuts`. Nothing fires while someone is typing.
 * The keys themselves are bound in `useGlobalShortcuts.ts`.
 */

import { Dialog, Kbd } from '@/components';
import type { UserRole } from '@/lib/api/types';
import { commandKeyLabel, useShellState } from '@/platform/shell';
import { navRowsFor } from '@/routes/modules';

function KeyRow({ keys, label }: { keys: string[]; label: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-body text-ink-2">{label}</span>
      <span className="flex shrink-0 items-center gap-1">
        {keys.map((key, index) => (
          <Kbd key={`${key}-${index}`}>{key}</Kbd>
        ))}
      </span>
    </li>
  );
}

/** The `?` sheet: only the keys this role has (§7.4). */
export function ShortcutSheet({
  open,
  onOpenChange,
  role,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  role: UserRole;
}) {
  const { shortcuts } = useShellState();
  const modules = navRowsFor(role).filter((row) => row.shortcut);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" size="sm">
      <div data-testid="shortcut-sheet">
        <h3 className="text-caption text-ink-3">Everywhere</h3>
        <ul className="mt-1 divide-y divide-line">
          <KeyRow keys={[commandKeyLabel(), 'K']} label="Find or go to" />
          <KeyRow keys={['/']} label="Search this page" />
          <KeyRow keys={['?']} label="This list" />
        </ul>
        <h3 className="mt-4 text-caption text-ink-3">Go to</h3>
        <ul className="mt-1 divide-y divide-line">
          {modules.map((row) => (
            <KeyRow key={row.to} keys={['g', row.shortcut!]} label={row.label} />
          ))}
        </ul>
        {shortcuts.length > 0 && (
          <>
            <h3 className="mt-4 text-caption text-ink-3">On this page</h3>
            <ul className="mt-1 divide-y divide-line">
              {shortcuts.map((shortcut) => (
                <KeyRow key={shortcut.key} keys={[shortcut.key]} label={shortcut.label} />
              ))}
            </ul>
          </>
        )}
      </div>
    </Dialog>
  );
}
