/**
 * Modal layers on Radix — focus trap, Escape to close, focus returned to the
 * opener, and a real title/description pair for screen readers. Used instead of
 * `window.confirm`, which blocks the page and cannot be styled or tested.
 */

import * as RadixDialog from '@radix-ui/react-dialog';
import type { ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { Button } from './Button';
import type { ButtonVariant } from './styles';

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 animate-fade-in bg-black/30" />
        <RadixDialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 animate-pop-in overflow-y-auto rounded-xl border border-line bg-surface p-6 shadow-float',
            size === 'sm' && 'max-w-sm',
            size === 'md' && 'max-w-lg',
            size === 'lg' && 'max-w-2xl',
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <RadixDialog.Title className="text-title font-semibold text-ink">{title}</RadixDialog.Title>
              <RadixDialog.Description
                className={description ? 'mt-1 text-body text-ink-2' : 'sr-only'}
              >
                {description ?? title}
              </RadixDialog.Description>
            </div>
            <RadixDialog.Close
              className="-mr-2 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded text-ink-2 transition-colors duration-quick hover:bg-sunken hover:text-ink"
              aria-label="Close"
            >
              <Icon.close size={20} aria-hidden />
            </RadixDialog.Close>
          </div>
          {children && <div className="mt-4">{children}</div>}
          {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

/** "Are you sure?" — for an action that cannot be undone. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  confirmVariant = 'primary',
  onConfirm,
  loading,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  confirmLabel: string;
  confirmVariant?: ButtonVariant;
  onConfirm: () => void;
  loading?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}

/**
 * A surface sliding in from an edge. `right` is the side panel (frontend-plan
 * §6.9): 480px wide, the full width under 768px, with a header, a scrolling body
 * and a footer. `left` is the navigation drawer on a narrow screen (§6.2). It
 * floats, so it carries the one shadow; the page behind stays put.
 */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  side = 'right',
  footer,
  className,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** `left` is the navigation drawer: its title is for assistive tech only. */
  side?: 'left' | 'right';
  footer?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 animate-fade-in bg-black/30" />
        <RadixDialog.Content
          className={cn(
            'fixed inset-y-0 z-50 flex flex-col bg-surface shadow-float',
            side === 'left' && 'left-0 w-64 max-w-[85vw] animate-slide-in-left',
            side === 'right' &&
              'right-0 w-full animate-slide-in-right border-l border-line md:w-[30rem] md:rounded-l-xl',
            className,
          )}
        >
          {side === 'left' ? (
            <>
              <RadixDialog.Title className="sr-only">{title}</RadixDialog.Title>
              <RadixDialog.Description className="sr-only">{description ?? title}</RadixDialog.Description>
              {children}
            </>
          ) : (
            <>
              <div className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-6 py-4">
                <div className="min-w-0">
                  <RadixDialog.Title className="text-title font-semibold text-ink">{title}</RadixDialog.Title>
                  <RadixDialog.Description
                    className={description ? 'mt-1 text-body text-ink-2' : 'sr-only'}
                  >
                    {description ?? title}
                  </RadixDialog.Description>
                </div>
                <RadixDialog.Close
                  className="-mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded text-ink-2 transition-colors duration-quick hover:bg-sunken hover:text-ink"
                  aria-label="Close"
                >
                  <Icon.close size={20} aria-hidden />
                </RadixDialog.Close>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
              {footer && (
                <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-line px-6 py-3">
                  {footer}
                </div>
              )}
            </>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
