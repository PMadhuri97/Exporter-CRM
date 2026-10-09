/**
 * New company, in a side panel over the Companies list (frontend-plan §8.4, §6.9) —
 * Dynamics quick create with duplicate detection. `/companies/new` opens the list
 * with the panel open; closing it goes back to the list.
 *
 * One field first: an identifier
 * (PAN, GSTIN, IEC, CIN) or the name. Its kind is detected, and once the name and
 * the country are known the server is asked whether the company is already in Aner
 * (`POST /companies/match`, read-only and audited). Then only what the create needs:
 * name, country, source — and, outside India without a PAN, the registration number
 * its own registrar issued. Everything else is added on the company itself.
 *
 * Add a company.
 *
 * Limited to `CreateExporterProfileRequest`'s real fields. The person adding
 * the company is never asked for their own contact — the backend takes it
 * from the signed-in session. The server refuses a PAN another company holds
 * (409) and warns, without refusing, about a shared GSTIN; the company page
 * shows that warning.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useState, type ReactNode } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button, Field, FormError, Input, RequiredNote, Select, Sheet } from '@/components';
import { ApiError } from '@/lib/api/errors';

import {
  CountrySelect,
  detectEntry,
  DuplicatePanMessage,
  duplicatePanHolder,
  IdentifierLookup,
} from '../components';
import { useCreateExporterLead } from '../hooks';
import { paths } from '../paths';

import { ExportersListPage } from './ExportersListPage';

const addCompanySchema = z.object({
  // The company's identity (docs/contracts/company-record.md §2.1).
  name: z.string().trim().min(1, 'Company name is required').max(255),
  country: z
    .string()
    .trim()
    .regex(/^[A-Za-z]{2}$/, 'Choose a country')
    .transform((v) => v.toUpperCase()),
  source: z.enum([
    'MANUAL',
    'SALES',
    'REFERRAL',
    'RXIL',
    'PARTNER',
    'API',
    'BROKER',
    'EVENT',
    'EXISTING_CUSTOMER',
  ]),
  registration_number: z.string().max(100).optional().or(z.literal('')),
});
// The foreign-identity rule (a company outside India is identified by its registrar's number unless
// it holds a PAN) is checked in onSubmit: the PAN comes from the identifier lookup, not a field.

type AddCompanyFormValues = z.infer<typeof addCompanySchema>;

const SOURCE_LABEL: Record<AddCompanyFormValues['source'], string> = {
  MANUAL: 'Manual entry',
  SALES: 'Sales',
  REFERRAL: 'Referral',
  RXIL: 'RXIL',
  PARTNER: 'Partner',
  API: 'API',
  BROKER: 'Broker',
  EVENT: 'Event',
  EXISTING_CUSTOMER: 'Existing customer',
};

function emptyToUndefined(value: string | undefined): string | undefined {
  return value === '' ? undefined : value;
}

/** `/companies/new`: the list, with the New company panel open over it. */
export function AddExporterPage() {
  const navigate = useNavigate();
  return (
    <>
      <ExportersListPage />
      <NewCompanyPanel onClose={() => navigate(paths.companies)} />
    </>
  );
}

const FORM_ID = 'new-company';

export function NewCompanyPanel({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const createLead = useCreateExporterLead();
  const [serverError, setServerError] = useState<ReactNode>(null);
  const [entry, setEntry] = useState('');
  const detected = detectEntry(entry);

  const {
    control,
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AddCompanyFormValues>({
    resolver: zodResolver(addCompanySchema),
    defaultValues: { source: 'MANUAL' },
  });
  const name = watch('name') ?? '';
  const country = (watch('country') ?? '').trim().toUpperCase();
  // A PAN — typed, or inside a GSTIN — is itself an identity.
  const holdsPan = Boolean(detected.pan);

  const onSubmit = async (values: AddCompanyFormValues) => {
    setServerError(null);
    // Outside India and without a PAN, the registrar's number is the identity.
    if (values.country !== 'IN' && !holdsPan && !values.registration_number?.trim()) {
      setError('registration_number', { message: 'Required for a company outside India' });
      return;
    }
    try {
      const profile = await createLead.mutateAsync({
        name: values.name,
        country: values.country,
        source: values.source,
        pan: detected.pan,
        gstins: detected.kind === 'GSTIN' ? [detected.value] : undefined,
        iec: detected.kind === 'IEC' ? detected.value : undefined,
        cin: detected.kind === 'CIN' ? detected.value : undefined,
        registration_number: emptyToUndefined(values.registration_number),
      });
      toast.success(`${values.name} added as a lead`);
      navigate(paths.company(profile.customer_id));
    } catch (error) {
      // A duplicate PAN names the holder by id; link to it rather than print the id.
      const panHolder = duplicatePanHolder(error);
      setServerError(
        panHolder ? (
          <DuplicatePanMessage holderId={panHolder} />
        ) : error instanceof ApiError ? (
          error.message
        ) : (
          'Unable to create this company. Try again.'
        ),
      );
    }
  };

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="New company"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form={FORM_ID} variant="primary" loading={isSubmitting}>
            Create lead
          </Button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-5">
        <RequiredNote />
        <IdentifierLookup
          value={entry}
          onChange={(next) => {
            setEntry(next);
            // A name typed here is the company's name, unless one is already set.
            if (detectEntry(next).kind === 'name' && !getValues('name')) {
              setValue('name', next.trim());
            }
          }}
          label="Start with an identifier — PAN, GSTIN, IEC or CIN — or the name"
          name={name}
          country={country.length === 2 ? country : undefined}
        />

        <div className="space-y-4 border-t border-line pt-5">
          <Field label="Company name" htmlFor="company-name" error={errors.name?.message} required>
            <Input id="company-name" placeholder="e.g. Lakshmi Polymers Pvt Ltd" {...register('name')} />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Country" htmlFor="company-country" error={errors.country?.message} required>
              <Controller
                control={control}
                name="country"
                render={({ field }) => (
                  <CountrySelect
                    id="company-country"
                    value={field.value ?? ''}
                    invalid={Boolean(errors.country)}
                    onChange={field.onChange}
                  />
                )}
              />
            </Field>
            <Field label="Source" htmlFor="company-source" error={errors.source?.message} required>
              <Select id="company-source" {...register('source')}>
                {Object.entries(SOURCE_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {country.length === 2 && country !== 'IN' && !holdsPan && (
            <Field
              label="Registration number"
              htmlFor="company-registration-number"
              error={errors.registration_number?.message}
              hint="The number its own registrar issued — how a company outside India is identified."
              required
            >
              <Input
                id="company-registration-number"
                placeholder="e.g. KVK 12345678"
                {...register('registration_number')}
              />
            </Field>
          )}
        </div>

        <FormError>{serverError}</FormError>

        <p className="text-secondary text-ink-3">
          Contacts, branches and industry are added on the company itself.
        </p>
      </form>
    </Sheet>
  );
}
