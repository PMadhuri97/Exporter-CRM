/**
 * *New deal* from the Deals page: choose the selling company, give the deal a
 * reference, and open it.
 *
 * The same request the company page's `OpenDealForm` sends, so the two cannot
 * ask for different things: a deal starts at OPEN, opening it moves the seller's
 * conversation to Ready now, and the buyer and the paperwork are added on the deal
 * itself — which is where this panel goes once the deal exists.
 *
 * Only a prospect or a customer may have a deal opened (the server refuses a lead
 * with `DEAL_COMPANY_NOT_READY`). Leads and buyer-only companies are still listed,
 * greyed out with the reason, so nobody wonders where their company went.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { Field, Input, SidePanel, sidePanelFieldError } from '@/components';

import { JOURNEY_LABEL } from '../constants';
import { useOpenDealOnCompany } from '../hooks';
import { paths } from '../paths';
import type { ExporterProfileListItem } from '../types';

import { CompanySearchSelect } from './CompanySearchSelect';

/** Why `company` cannot be the seller on a new deal, or `null` when it can. */
function sellerUnavailableReason(company: ExporterProfileListItem): string | null {
  if (company.pipeline_status === 'NOT_IN_PIPELINE') return 'Not in the pipeline — a buyer only';
  if (company.journey === 'LEAD') return "Leads can't have deals yet";
  return null;
}

function describeSeller(company: ExporterProfileListItem): string {
  return [company.country, company.pipeline_status === 'NOT_IN_PIPELINE' ? null : JOURNEY_LABEL[company.journey]]
    .filter(Boolean)
    .join(' · ');
}

export function NewDealPanel({ open, onOpenChange }: { open: boolean; onOpenChange(open: boolean): void }) {
  const navigate = useNavigate();
  const [sellerId, setSellerId] = useState<string | null>(null);
  const [reference, setReference] = useState('');
  const mutation = useOpenDealOnCompany();

  function close(next: boolean) {
    if (!next) {
      setSellerId(null);
      setReference('');
      mutation.reset();
    }
    onOpenChange(next);
  }

  function submit() {
    if (!sellerId || !reference.trim()) return;
    mutation.mutate(
      { companyId: sellerId, body: { reference: reference.trim() } },
      {
        onSuccess: (deal) => {
          toast.success("Deal opened — the seller's conversation is now Ready now");
          close(false);
          navigate(paths.deal(deal.id));
        },
      },
    );
  }

  return (
    <SidePanel
      open={open}
      onOpenChange={close}
      title="New deal"
      submitLabel="Open deal"
      onSubmit={submit}
      pending={mutation.isPending}
      error={mutation.error}
      fields={['reference']}
      submitDisabled={!sellerId || reference.trim() === ''}
    >
      <CompanySearchSelect
        label="Seller"
        value={sellerId}
        onChange={(id) => {
          setSellerId(id);
          mutation.reset();
        }}
        placeholder="Search companies by name"
        unavailable={sellerUnavailableReason}
        describe={describeSeller}
      />
      <Field
        label="Reference"
        htmlFor="new-deal-reference"
        hint="A short label, so this deal is recognisable in a list."
        error={sidePanelFieldError(mutation.error, 'reference')}
      >
        <Input
          id="new-deal-reference"
          type="text"
          value={reference}
          required
          maxLength={200}
          placeholder="Rotterdam shipment, March"
          onChange={(event) => setReference(event.target.value)}
        />
      </Field>
    </SidePanel>
  );
}
