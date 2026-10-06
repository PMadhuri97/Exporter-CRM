/**
 * The shortcut list, opened with Ctrl+/ as in Salesforce (frontend-plan §7.5). The
 * whole keyboard is these few keys, bound in `useGlobalShortcuts.ts`; Tab order does
 * the rest. Nothing fires while someone is typing.
 */

import { Dialog, Kbd } from '@/components';
import { commandKeyLabel } from '@/platform/shell';

function KeyRow({ keys, label }: { keys: string[][]; label: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-2">
      <span className="text-body text-ink-2">{label}</span>
      <span className="flex shrink-0 items-center gap-1.5 text-caption text-ink-3">
        {keys.map((combo, index) => (
          <span key={combo.join('+')} className="flex items-center gap-1">
            {index > 0 && <span className="mr-0.5">or</span>}
            {combo.map((key) => (
              <Kbd key={key}>{key}</Kbd>
            ))}
          </span>
        ))}
      </span>
    </li>
  );
}

export function ShortcutList({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const mod = commandKeyLabel();
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" size="sm">
      <ul className="divide-y divide-line" data-testid="shortcut-list">
        <KeyRow keys={[['/'], [mod, 'K']]} label="Search companies and pages" />
        <KeyRow keys={[[mod, '/']]} label="This list" />
        <KeyRow keys={[['Esc']]} label="Close a panel, menu or dialog" />
      </ul>
    </Dialog>
  );
}
