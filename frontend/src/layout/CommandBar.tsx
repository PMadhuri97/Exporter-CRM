/**
 * The command bar, ⌘K / Ctrl K (frontend-plan §7.5) — the dialog. What it offers is
 * in `CommandBody.tsx`, loaded the first time it opens.
 */

import * as RadixDialog from '@radix-ui/react-dialog';
import { lazy, Suspense } from 'react';

import type { UserRole } from '@/lib/api/types';

const CommandBody = lazy(() => import('./CommandBody').then((m) => ({ default: m.CommandBody })));

export function CommandBar({
  open,
  onOpenChange,
  role,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  role: UserRole;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 animate-fade-in bg-black/25" />
        <RadixDialog.Content
          className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 animate-float-in overflow-hidden rounded-2xl border border-line bg-raised shadow-float"
          aria-describedby={undefined}
        >
          <RadixDialog.Title className="sr-only">Find or go to</RadixDialog.Title>
          {open && (
            <Suspense fallback={<div className="h-12" aria-hidden />}>
              <CommandBody role={role} close={() => onOpenChange(false)} />
            </Suspense>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
