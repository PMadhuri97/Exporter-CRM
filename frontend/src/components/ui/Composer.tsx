/**
 * The composer (frontend-plan §6.10): the one surface that replaces a form box in
 * the middle of the page. A sheet — from the right on a wide screen, from the bottom
 * on a narrow one — with a verb for a title, the fewest fields, and a footer with one
 * primary action. Focus moves in on open and returns to the trigger on close.
 *
 * The server stays the authority on what is valid: a 422 that names a field is
 * placed against that field (`composerFieldError`), anything else sits in the footer
 * in the server's words.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from 'react';

import { ApiError } from '@/lib/api/errors';

import { Button } from './Button';
import { Sheet } from './Dialog';
import { FormError } from './Field';

const WIDE = '(min-width: 1024px)';

function useWide(): boolean {
  const [wide, setWide] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(WIDE).matches : true,
  );
  useEffect(() => {
    if (!window.matchMedia) return;
    const query = window.matchMedia(WIDE);
    const update = () => setWide(query.matches);
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);
  return wide;
}

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

export function Composer({
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
  /** A verb: "Log a call", "Propose Clear", "Withdraw the deal". */
  title: ReactNode;
  description?: ReactNode;
  submitLabel: string;
  onSubmit: () => void;
  pending?: boolean;
  /** The last refusal, as the mutation reported it. */
  error?: unknown;
  /** The field paths this composer places errors on, so the footer does not repeat them. */
  fields?: readonly string[];
  submitDisabled?: boolean;
  children: ReactNode;
}) {
  const wide = useWide();
  const formId = `composer-${String(title).replace(/\W+/g, '-').toLowerCase()}`;
  const message = footerMessage(error, fields);

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      side={wide ? 'right' : 'bottom'}
      footer={
        <div className="flex w-full flex-col gap-3">
          {message && <FormError>{message}</FormError>}
          <div className="flex justify-end gap-2">
            <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={pending}>
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
