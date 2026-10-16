/**
 * Why a live rule is being changed — asked of every change on the settings pages
 * (qualification criteria, required documents, payment terms, sanctions lists).
 *
 * Each of those changes writes a new version of a rule the next lead, deal or
 * screening is judged against, so none may happen on a single click and none without
 * a reason a reviewer can follow: a ticket number (`CHG-1042`, `CHG0031234`) or an
 * explanation of a few words. The reason is kept on the version it wrote.
 *
 * `changeReasonProblem` (`./change-reason.ts`) is the server's rule applied as the
 * administrator types, so the commit button only lights up for a reason the server will
 * take. The server still checks, and its refusal is shown in its own words.
 */

import { useState, type ReactNode } from 'react';

import { Button, Dialog, Field, FormError, Textarea, sidePanelFieldError } from '@/components';

import { CHANGE_REASON_HINT, CHANGE_REASON_MAX_LENGTH, changeReasonProblem } from './change-reason';

/**
 * The reason, as a required field inside a form. Says what is wrong only once the
 * administrator has typed something (or the server refused it): an empty field is
 * already marked required, and the commit button stays off until it is filled.
 */
export function ChangeReasonField({
  id,
  value,
  onChange,
  serverError,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /** The request's refusal, if any; a 422 on `change_reason` is shown here. */
  serverError?: unknown;
}) {
  const problem = value.trim() ? changeReasonProblem(value) : null;
  return (
    <Field
      label="Reason for change"
      htmlFor={id}
      required
      hint={CHANGE_REASON_HINT}
      error={problem ?? sidePanelFieldError(serverError, 'change_reason')}
    >
      <Textarea
        id={id}
        rows={2}
        maxLength={CHANGE_REASON_MAX_LENGTH}
        value={value}
        placeholder="e.g. CHG-1042 — raise the floor as agreed by credit committee"
        onChange={(event) => onChange(event.target.value)}
        required
      />
    </Field>
  );
}

/**
 * A one-click change to a live rule (retire a term, stop using a list, stop requiring a
 * document) asks first: what will happen, and why it is being done. Nothing is sent
 * until a valid reason is given and the change is committed.
 */
export function ChangeReasonDialog({
  open,
  onOpenChange,
  title,
  consequence,
  confirmLabel,
  onConfirm,
  pending,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  /** What the change does to the live rule, in a sentence. */
  consequence: ReactNode;
  confirmLabel: string;
  onConfirm: (reason: string) => void;
  pending?: boolean;
  error?: unknown;
}) {
  const [reason, setReason] = useState('');
  const ready = changeReasonProblem(reason) === null;
  const close = (next: boolean) => {
    if (!next) setReason('');
    onOpenChange(next);
  };
  const fieldError = sidePanelFieldError(error, 'change_reason');

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title={title}
      description={consequence}
      footer={
        <>
          <Button onClick={() => close(false)} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="change-reason-dialog"
            disabled={!ready}
            loading={pending}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form
        id="change-reason-dialog"
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) onConfirm(reason.trim());
        }}
      >
        <ChangeReasonField id="change-reason-dialog-reason" value={reason} onChange={setReason} serverError={error} />
        {error && !fieldError ? (
          <FormError>{error instanceof Error ? error.message : 'Could not save the change'}</FormError>
        ) : null}
      </form>
    </Dialog>
  );
}
