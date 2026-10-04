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
        <RadixDialog.Overlay className="fixed inset-0 z-40 animate-fade-in bg-black/35" />
        <RadixDialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 animate-pop-in overflow-y-auto rounded-2xl border border-line bg-raised p-6 shadow-float',
            size === 'sm' && 'max-w-sm',
            size === 'md' && 'max-w-lg',
            size === 'lg' && 'max-w-2xl',
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <RadixDialog.Title className="font-display text-display-sm text-ink">
                {title}
              </RadixDialog.Title>
              <RadixDialog.Description
                className={description ? 'mt-1 text-body text-ink-2' : 'sr-only'}
              >
                {description ?? title}
              </RadixDialog.Description>
            </div>
            <RadixDialog.Close
              className="rounded-md p-1 text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink"
              aria-label="Close"
            >
              <Icon.close size={16} aria-hidden />
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
 * A surface sliding in from an edge (§6.10, §6.11): from the right beside a list
 * on a wide screen, from the bottom on a narrow one, from the left for the main
 * menu. It floats, so it carries the one shadow; the page behind stays put.
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
  /** `left` is the menu: its title is for assistive tech only. */
  side?: 'left' | 'right' | 'bottom';
  footer?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 animate-fade-in bg-black/35" />
        <RadixDialog.Content
          className={cn(
            'fixed z-50 flex flex-col bg-raised shadow-float',
            side === 'left' && 'inset-y-0 left-0 w-60 max-w-[85vw] animate-slide-in-left',
            side === 'right' &&
              'inset-y-0 right-0 w-[32rem] max-w-[92vw] animate-slide-in-right overflow-y-auto border-l border-line p-6',
            side === 'bottom' &&
              'inset-x-0 bottom-0 max-h-[88vh] animate-slide-in-up overflow-y-auto rounded-t-2xl border-t border-line p-5',
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
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <RadixDialog.Title className="font-display text-display-sm text-ink">
                    {title}
                  </RadixDialog.Title>
                  <RadixDialog.Description
                    className={description ? 'mt-1 text-body text-ink-2' : 'sr-only'}
                  >
                    {description ?? title}
                  </RadixDialog.Description>
                </div>
                <RadixDialog.Close
                  className="rounded-md p-1 text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink"
                  aria-label="Close"
                >
                  <Icon.close size={16} aria-hidden />
                </RadixDialog.Close>
              </div>
              <div className="mt-5 flex-1">{children}</div>
              {footer && (
                <div className="mt-6 flex flex-wrap justify-end gap-2 border-t border-line pt-4">
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
