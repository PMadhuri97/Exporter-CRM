/**
 * The side panel (frontend-plan §6.9): quick create and quick actions, as in
 * Dynamics quick create and HubSpot's create panel. It slides in from the right,
 * 480px wide (the full width under 768px), over a dimmed page. A header with the
 * verb and a close button, the fewest fields possible, and a footer with one
 * primary button and *Cancel*. Focus moves in on open and returns to the trigger
 * on close.
 *
 * The server stays the authority on what is valid: a 422 that names a field is
 * placed against that field (`sidePanelFieldError`), anything else sits in the
 * footer in the server's words.
 */

import type { FormEvent, ReactNode } from 'react';

import { ApiError } from '@/lib/api/errors';

import { Button } from './Button';
import { Sheet } from './Dialog';
import { FormError } from './Field';

/** The refusal's words for the footer — unless every one of them sits on a field. */
function footerMessage(error: unknown, fields: readonly string[]): string | null {
  if (!error) return null;
  if (error instanceof ApiError) {
    const named = error.fieldErrors ? Object.keys(error.fieldErrors) : [];
    if (named.length > 0 && named.every((field) => fields.includes(field))) return null;
    return error.message;
  }
  return error instanceof Error ? error.message : 'Something went wrong. Try again.';
}

export function SidePanel({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  onSubmit,
  pending = false,
  error,
  fields = [],
  submitDisabled = false,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A verb and an object: "Log a call", "New company", "Record a decision". */
  title: ReactNode;
  description?: ReactNode;
  submitLabel: string;
  onSubmit: () => void;
  pending?: boolean;
  /** The last refusal, as the mutation reported it. */
  error?: unknown;
  /** The field paths this panel places errors on, so the footer does not repeat them. */
  fields?: readonly string[];
  submitDisabled?: boolean;
  children: ReactNode;
}) {
  const formId = `side-panel-${String(title).replace(/\W+/g, '-').toLowerCase()}`;
  const message = footerMessage(error, fields);

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <div className="flex w-full flex-col gap-3">
          {message && <FormError>{message}</FormError>}
          <div className="flex justify-end gap-2">
            <Button onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <Button
              type="submit"
              form={formId}
              variant="primary"
              loading={pending}
              disabled={submitDisabled}
            >
              {submitLabel}
            </Button>
          </div>
        </div>
      }
    >
      <form
        id={formId}
        className="space-y-4"
        noValidate
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        {children}
      </form>
    </Sheet>
  );
}
