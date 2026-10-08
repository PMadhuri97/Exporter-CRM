/**
 * A deal's value, currency and payment term.
 *
 * The term starts as the company's default; choosing another asks why, and the reason
 * is kept on the deal and in its history. Only current, offered terms are listed; a
 * term retired since stays shown on the deal it was agreed on. A closed deal's terms
 * are frozen, so it is offered no edit.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, FormPanel, Input, Panel, RequiredNote, Select, Textarea } from '@/components';
import { Icon } from '@/design/icons';

import { usePaymentTerms, useSetDealTerms } from '../hooks';
import type { Deal, SetDealTermsRequest } from '../types';

import { moneyLabel, termLabel } from './payment-term-labels';

function TermsForm({ deal, onDone }: { deal: Deal; onDone: () => void }) {
  const terms = usePaymentTerms();
  const save = useSetDealTerms(deal.id);
  const [value, setValue] = useState(deal.value_amount ?? '');
  const [currency, setCurrency] = useState(deal.currency ?? '');
  const [termId, setTermId] = useState(deal.payment_term?.id ?? '');
  const [reason, setReason] = useState('');
  const offered = (terms.data?.terms ?? []).filter((term) => term.active);
  const defaultCode = deal.company_default_payment_term?.code ?? null;
  const chosen = offered.find((term) => term.id === termId) ?? deal.payment_term ?? null;
  const termChanged = termId !== (deal.payment_term?.id ?? '');
  const needsReason = termChanged && defaultCode !== null && chosen?.code !== defaultCode;
  const ready = (!value || currency.trim().length === 3) && (!needsReason || reason.trim());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: SetDealTermsRequest = {};
    if (String(value) !== String(deal.value_amount ?? '')) body.value_amount = value === '' ? null : String(value);
    if (currency.trim().toUpperCase() !== (deal.currency ?? '')) body.currency = currency.trim().toUpperCase() || null;
    if (termChanged) body.payment_term_id = termId || null;
    if (needsReason) body.payment_term_override_reason = reason.trim();
    if (Object.keys(body).length === 0) {
      onDone();
      return;
    }
    try {
      await save.mutateAsync(body);
      toast.success('Deal terms saved');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the terms');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Value" htmlFor="deal-value">
          <Input id="deal-value" type="number" min={0} step="0.01" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Field label="Currency" htmlFor="deal-currency" required={Boolean(value)}>
          <Input id="deal-currency" value={currency} maxLength={3} placeholder="e.g. USD" onChange={(e) => setCurrency(e.target.value)} />
        </Field>
      </div>
      <Field label="Payment term" htmlFor="deal-term">
        <Select id="deal-term" value={termId} onChange={(e) => setTermId(e.target.value)}>
          <option value="">No payment term</option>
          {deal.payment_term && !offered.some((term) => term.id === deal.payment_term!.id) && (
            <option value={deal.payment_term.id}>{termLabel(deal.payment_term)}</option>
          )}
          {offered.map((term) => (
            <option key={term.id} value={term.id}>
              {term.label}
              {term.code === defaultCode ? ' (company default)' : ''}
            </option>
          ))}
        </Select>
      </Field>
      {needsReason && (
        <Field label="Why this term instead of the company's default" htmlFor="deal-term-reason" required>
          <Textarea id="deal-term-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      )}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={save.isPending}>
          Save terms
        </Button>
      </div>
    </form>
  );
}

export function DealTermsPanel({ deal, canEdit }: { deal: Deal; canEdit: boolean }) {
  const [editing, setEditing] = useState(false);
  return (
    <Panel
      title="Value and terms"
      actions={
        canEdit && (
          <Button size="sm" variant="subtle" onClick={() => setEditing(true)}>
            <Icon.edit size={14} /> Edit
          </Button>
        )
      }
    >
      {editing && (
        <FormPanel title="Value and terms" onClose={() => setEditing(false)}>
          <TermsForm deal={deal} onDone={() => setEditing(false)} />
        </FormPanel>
      )}
      <dl className="grid gap-2 text-body sm:grid-cols-2">
        <div>
          <dt className="text-caption text-ink-3">Value</dt>
          <dd className="text-ink" data-testid="deal-value">
            {moneyLabel(deal.value_amount, deal.currency) ?? 'Not set'}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-ink-3">Payment term</dt>
          <dd className="text-ink" data-testid="deal-term">
            {termLabel(deal.payment_term)}
          </dd>
        </div>
        {deal.payment_term_override_reason && (
          <div className="sm:col-span-2">
            <dt className="text-caption text-ink-3">
              Differs from the company default
              {deal.company_default_payment_term ? ` (${deal.company_default_payment_term.label})` : ''} because
            </dt>
            <dd className="text-ink">{deal.payment_term_override_reason}</dd>
          </div>
        )}
      </dl>
    </Panel>
  );
}
