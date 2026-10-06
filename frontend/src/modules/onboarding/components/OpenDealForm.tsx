/**
 * Open a deal on a company.
 *
 * One form, used from the Deals tab and from the conversation's READY_NOW
 * prompt (seam S2), so the two can never ask for different things. A deal
 * always starts at OPEN; the buyer and the paperwork are added on the deal.
 * Opening one also moves the conversation to READY_NOW on the server, and
 * `useOpenDeal` refreshes the gauge.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, FormPanel, Input } from '@/components';

import { useOpenDeal } from '../hooks';
import type { Deal } from '../types';

export function OpenDealForm({
  customerId,
  onClose,
  onOpened,
}: {
  customerId: string;
  onClose: () => void;
  /** After the server has opened it — the prompt goes to the new deal's page. */
  onOpened?: (deal: Deal) => void;
}) {
  const [reference, setReference] = useState('');
  const mutation = useOpenDeal(customerId);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const deal = await mutation.mutateAsync({ reference: reference.trim() });
      toast.success('Deal opened — the conversation is now Ready now');
      onClose();
      onOpened?.(deal);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open the deal');
    }
  }

  return (
    <FormPanel title="Open a deal" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Field
          label="Reference"
          htmlFor={`deal-reference-${customerId}`}
          hint="A short label, so this deal is recognisable in a list. The buyer and the paperwork are added on the deal itself."
        >
          <Input
            id={`deal-reference-${customerId}`}
            type="text"
            value={reference}
            required
            placeholder="Rotterdam shipment, March"
            onChange={(event) => setReference(event.target.value)}
          />
        </Field>
        <div className="flex justify-end">
          <Button
            type="submit"
            variant="primary"
            disabled={reference.trim() === ''}
            loading={mutation.isPending}
          >
            Open deal
          </Button>
        </div>
      </form>
    </FormPanel>
  );
}
