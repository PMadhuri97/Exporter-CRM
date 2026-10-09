/**
 * Create a deal's buyer as a company.
 *
 * Opened by `CompanyPicker` once a search has found no company on file. It collects
 * the least a buyer company needs and hands it to the caller, which sends it as the
 * `create` form of `PUT /deals/{id}/buyer`: the server creates the company **outside
 * the pipeline** — a buyer, not a lead — and names it as the deal's buyer in one step.
 *
 * What it does not do is decide anything the server decides. It asks for a
 * registration number when the country is not India, because the CRM requires one and
 * saying so up front saves a round trip — but whether the value is acceptable, whether
 * a company on file already holds it, and whether a PAN fits a GSTIN are the server's
 * answers, shown as they come back. When the server says a company on file already
 * holds the identifier (409 `BUYER_COMPANY_ALREADY_KNOWN`), the form offers that
 * company instead of a duplicate.
 */

import { useState } from 'react';

import { Button, Field, Input, RequiredNote } from '@/components';
import { ApiError } from '@/lib/api/errors';

import type { CreateBuyerCompanyRequest } from '../types';

import { CountrySelect } from './CountrySelect';

export interface CreateBuyerCompanyFormProps {
  /** What the search already holds: the name typed, the country, any identifier. */
  initial: Partial<CreateBuyerCompanyRequest> & { name: string; country: string };
  /** Create and name the buyer. Rejects with the server's refusal. */
  onCreate(draft: CreateBuyerCompanyRequest): Promise<unknown>;
  /** Pick a company the server says already holds the identifier. */
  onChooseExisting(companyId: string): void;
  onCancel(): void;
}

function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function CreateBuyerCompanyForm({
  initial,
  onCreate,
  onChooseExisting,
  onCancel,
}: CreateBuyerCompanyFormProps) {
  const [name, setName] = useState(initial.name);
  const [country, setCountry] = useState(initial.country);
  const [pan, setPan] = useState(initial.pan ?? '');
  const [gstin, setGstin] = useState(initial.gstin ?? '');
  const [registration, setRegistration] = useState(initial.registration_number ?? '');
  const [error, setError] = useState<string | null>(null);
  const [existing, setExisting] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const countryCode = country.trim().toUpperCase();
  const indian = countryCode === 'IN';
  const ready =
    name.trim() !== '' &&
    /^[A-Z]{2}$/.test(countryCode) &&
    (indian || registration.trim() !== '');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setExisting(null);
    setPending(true);
    try {
      await onCreate({
        name: name.trim(),
        country: countryCode,
        pan: indian ? blankToNull(pan) : null,
        gstin: indian ? blankToNull(gstin) : null,
        registration_number: indian ? null : blankToNull(registration),
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create the buyer company');
      if (caught instanceof ApiError && caught.errorCode === 'BUYER_COMPANY_ALREADY_KNOWN') {
        const ids = caught.context?.company_ids;
        // One company: offer it. Several (a conflict): a person must decide which,
        // and a list of ids would not help them — the message says to search.
        if (Array.isArray(ids) && ids.length === 1) setExisting(String(ids[0]));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Create buyer company"
      className="flex flex-col gap-3 rounded-lg border border-line p-4"
    >
      <RequiredNote />
      <p className="text-body text-ink-2">
        A buyer company is created <span className="font-medium text-ink">outside the
        pipeline</span>: it is not a lead and changes no pipeline count. It is named as
        this deal's buyer at once.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Company name" htmlFor="create-buyer-name" required>
          <Input
            id="create-buyer-name"
            value={name}
            required
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="Country" htmlFor="create-buyer-country" required>
          <CountrySelect id="create-buyer-country" value={country} onChange={setCountry} />
        </Field>
        {indian ? (
          <>
            <Field label="PAN" htmlFor="create-buyer-pan" hint="The complete PAN, if known">
              <Input id="create-buyer-pan" value={pan} onChange={(e) => setPan(e.target.value)} />
            </Field>
            <Field
              label="GSTIN"
              htmlFor="create-buyer-gstin"
              hint="One complete GSTIN, if known"
            >
              <Input
                id="create-buyer-gstin"
                value={gstin}
                onChange={(e) => setGstin(e.target.value)}
              />
            </Field>
          </>
        ) : (
          <Field
            label="Registration number"
            htmlFor="create-buyer-registration"
            hint="Required for a company outside India: the number its own registrar issued"
            required
          >
            <Input
              id="create-buyer-registration"
              value={registration}
              required
              onChange={(e) => setRegistration(e.target.value)}
            />
          </Field>
        )}
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-negative/30 bg-negative-tint px-3 py-2 text-body text-ink"
        >
          {error}
          {existing ? (
            <div className="mt-2">
              <Button size="sm" variant="secondary" onClick={() => onChooseExisting(existing)}>
                Use the company on file
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button variant="subtle" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={pending}>
          Create buyer company
        </Button>
      </div>
    </form>
  );
}
