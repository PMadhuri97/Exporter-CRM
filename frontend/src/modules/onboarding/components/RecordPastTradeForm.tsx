/**
 * Record past trade on a relationship — `remaining-work.md` R-27 (plan P5-8).
 *
 * What two companies traded before they came to us: an invoice with **no deal**,
 * and, if anybody knows, how it was paid. It is "claimed" until somebody has seen
 * proof (`proof_status`), and the screens say so.
 *
 * Two requests, because that is the API: `POST /trade-relationships/{id}/invoices`
 * records the invoice, then `POST /trade-invoices/{id}/outcomes` appends the outcome.
 * An invoice's identity is frozen once written, so the form never re-sends it: if the
 * outcome is refused after the invoice was recorded, it says exactly that and keeps
 * only the outcome open, against the invoice that now exists.
 *
 * Nothing here decides a rule. A `PARTIAL` outcome needs `amount_paid` and a duplicate
 * invoice number is refused — the server says which, and its words are shown.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, Input, Select, Textarea } from '@/components';

import { recordTradeOutcome } from '../api';
import { useRecordTradeInvoice } from '../hooks';
import type { TradePaymentStatus, TradeProofStatus } from '../types';

const PAYMENT_STATUSES: { value: TradePaymentStatus; label: string }[] = [
  { value: 'PAID', label: 'Paid' },
  { value: 'PARTIAL', label: 'Part paid' },
  { value: 'UNPAID', label: 'Unpaid' },
  { value: 'DISPUTED', label: 'Disputed' },
  { value: 'UNKNOWN', label: 'Not known' },
];

export interface RecordPastTradeFormProps {
  relationshipId: string;
  /** The other party, so the form says who the invoice is with. */
  counterpartyName: string;
  /** Called once everything asked for is recorded. */
  onDone(): void;
  onCancel(): void;
}

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function RecordPastTradeForm({
  relationshipId,
  counterpartyName,
  onDone,
  onCancel,
}: RecordPastTradeFormProps) {
  const queryClient = useQueryClient();
  const recordInvoice = useRecordTradeInvoice(relationshipId);
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('');
  const [paymentStatus, setPaymentStatus] = useState<TradePaymentStatus | ''>('');
  const [amountPaid, setAmountPaid] = useState('');
  const [proofStatus, setProofStatus] = useState<TradeProofStatus>('CLAIMED');
  const [note, setNote] = useState('');
  /** Set once the invoice exists: from then on only the outcome can be sent. */
  const [recordedInvoiceId, setRecordedInvoiceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const invoiceReady =
    recordedInvoiceId !== null ||
    (invoiceNumber.trim() !== '' &&
      invoiceDate !== '' &&
      amount.trim() !== '' &&
      /^[A-Za-z]{3}$/.test(currency.trim()));

  async function sendOutcome(invoiceId: string) {
    await recordTradeOutcome(invoiceId, {
      payment_status: paymentStatus as TradePaymentStatus,
      proof_status: proofStatus,
      ...(amountPaid.trim() ? { amount_paid: amountPaid.trim() } : {}),
      ...(note.trim() ? { evidence_note: note.trim() } : {}),
    });
    // What `useRecordTradeOutcome` refreshes. Not that hook itself: the invoice id is
    // only known once the first request has answered.
    void queryClient.invalidateQueries({ queryKey: ['tradeInvoice', invoiceId] });
    void queryClient.invalidateQueries({ queryKey: ['tradeRelationship', relationshipId] });
    void queryClient.invalidateQueries({ queryKey: ['companyHistory'] });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    let invoiceId = recordedInvoiceId;
    try {
      if (invoiceId === null) {
        try {
          const invoice = await recordInvoice.mutateAsync({
            invoice_number: invoiceNumber.trim(),
            invoice_date: invoiceDate,
            amount: amount.trim(),
            currency: currency.trim().toUpperCase(),
            // Past trade: no deal (P5-8).
          });
          invoiceId = invoice.id;
        } catch (caught) {
          setError(message(caught, 'Could not record the invoice'));
          return;
        }
      }
      if (paymentStatus) {
        try {
          await sendOutcome(invoiceId);
        } catch (caught) {
          // The invoice exists and cannot be re-sent; only the outcome is left.
          setRecordedInvoiceId(invoiceId);
          setError(
            `The invoice is recorded, but its outcome was refused: ${message(
              caught,
              'no reason given',
            )}`,
          );
          return;
        }
      }
      toast.success(
        paymentStatus ? 'Past invoice and its outcome recorded' : 'Past invoice recorded',
      );
      onDone();
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Record past invoice"
      className="mt-2 flex flex-col gap-3 rounded-lg border border-line bg-paper p-4"
    >
      <p className="text-sm text-ink-2">
        An invoice with <span className="font-medium text-ink">{counterpartyName}</span> from
        before either company came to us. It records no deal, and its outcome stays
        "claimed" until somebody has seen proof.
      </p>
      <fieldset disabled={recordedInvoiceId !== null} className="grid gap-3 sm:grid-cols-2">
        <Field label="Invoice number" htmlFor="past-invoice-number" required>
          <Input
            id="past-invoice-number"
            value={invoiceNumber}
            onChange={(e) => setInvoiceNumber(e.target.value)}
          />
        </Field>
        <Field label="Invoice date" htmlFor="past-invoice-date" required>
          <Input
            id="past-invoice-date"
            type="date"
            value={invoiceDate}
            onChange={(e) => setInvoiceDate(e.target.value)}
          />
        </Field>
        <Field label="Amount" htmlFor="past-invoice-amount" required hint="As invoiced">
          <Input
            id="past-invoice-amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field
          label="Currency"
          htmlFor="past-invoice-currency"
          required
          hint="ISO code, e.g. USD. Stored as invoiced, never converted."
        >
          <Input
            id="past-invoice-currency"
            maxLength={3}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
          />
        </Field>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="How it was paid"
          htmlFor="past-invoice-status"
          hint="Leave blank if nobody knows yet"
        >
          <Select
            id="past-invoice-status"
            value={paymentStatus}
            onChange={(e) => setPaymentStatus(e.target.value as TradePaymentStatus | '')}
          >
            <option value="">No outcome yet</option>
            {PAYMENT_STATUSES.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </Select>
        </Field>
        {paymentStatus ? (
          <Field label="Proof" htmlFor="past-invoice-proof">
            <Select
              id="past-invoice-proof"
              value={proofStatus}
              onChange={(e) => setProofStatus(e.target.value as TradeProofStatus)}
            >
              <option value="CLAIMED">Claimed — nobody has shown proof yet</option>
              <option value="PROVEN">Proven — we have seen evidence</option>
            </Select>
          </Field>
        ) : null}
        {paymentStatus === 'PARTIAL' ? (
          <Field label="Amount paid" htmlFor="past-invoice-paid" hint="In the invoice's currency">
            <Input
              id="past-invoice-paid"
              inputMode="decimal"
              value={amountPaid}
              onChange={(e) => setAmountPaid(e.target.value)}
            />
          </Field>
        ) : null}
        {paymentStatus ? (
          <Field label="Note" htmlFor="past-invoice-note" className="sm:col-span-2">
            <Textarea
              id="past-invoice-note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        ) : null}
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-negative/30 bg-negative-tint px-3 py-2 text-sm text-ink"
        >
          {error}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button variant="quiet" onClick={recordedInvoiceId ? onDone : onCancel} disabled={pending}>
          {recordedInvoiceId ? 'Close' : 'Cancel'}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={!invoiceReady || (recordedInvoiceId !== null && !paymentStatus)}
          loading={pending}
        >
          {recordedInvoiceId ? 'Record the outcome' : 'Record past invoice'}
        </Button>
      </div>
    </form>
  );
}
