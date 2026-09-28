/**
 * Add a company — **owner: Developer 2** (L2-06, L2-14).
 *
 * Limited to `CreateExporterProfileRequest`'s real fields. The person adding
 * the company is never asked for their own contact — the backend takes it
 * from the signed-in session. The server refuses a PAN another company holds
 * (409) and warns, without refusing, about a shared GSTIN; the company page
 * shows that warning.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button, Card, Field, FormError, Input, PageHeader, Select } from '@/components';
import { ApiError } from '@/lib/api/errors';

import { useCreateExporterLead } from '../hooks';
import { paths } from '../paths';

const addCompanySchema = z.object({
  // The company's identity (docs/contracts/company-record.md §2.1).
  name: z.string().trim().min(1, 'Company name is required').max(255),
  country: z
    .string()
    .trim()
    .regex(/^[A-Za-z]{2}$/, 'Use a 2-letter country code (e.g. IN, US)')
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
  relationship_manager: z.string().max(255).optional().or(z.literal('')),
  gstin: z.string().max(15).optional().or(z.literal('')),
  pan: z.string().max(10).optional().or(z.literal('')),
  iec: z.string().max(10).optional().or(z.literal('')),
  cin: z.string().max(21).optional().or(z.literal('')),
  industry: z.string().max(255).optional().or(z.literal('')),
  website: z.string().max(2048).optional().or(z.literal('')),
});

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

export function AddExporterPage() {
  const navigate = useNavigate();
  const createLead = useCreateExporterLead();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AddCompanyFormValues>({
    resolver: zodResolver(addCompanySchema),
    defaultValues: { source: 'MANUAL' },
  });

  const onSubmit = async (values: AddCompanyFormValues) => {
    setServerError(null);
    try {
      const profile = await createLead.mutateAsync({
        name: values.name,
        country: values.country,
        source: values.source,
        relationship_manager: emptyToUndefined(values.relationship_manager),
        // One GSTIN from the form; a company may hold several (one per state).
        gstins: values.gstin ? [values.gstin] : undefined,
        pan: emptyToUndefined(values.pan),
        iec: emptyToUndefined(values.iec),
        cin: emptyToUndefined(values.cin),
        industry: emptyToUndefined(values.industry),
        website: emptyToUndefined(values.website),
      });
      toast.success(`${values.name} added as a lead`);
      navigate(paths.company(profile.customer_id));
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : 'Unable to create this company. Try again.',
      );
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        back={{ to: paths.companies, label: 'Companies' }}
        title="Add company"
        description="Every company starts as a lead. Qualification moves it on from there."
      />

      <Card className="p-6">
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-6">
          <FormError>{serverError}</FormError>

          <fieldset className="space-y-4">
            <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Company
            </legend>
            <Field label="Company name" htmlFor="company-name" error={errors.name?.message} required>
              <Input id="company-name" placeholder="e.g. Acme Exports Pvt Ltd" {...register('name')} />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Country" htmlFor="company-country" error={errors.country?.message} required>
                <Input
                  id="company-country"
                  className="uppercase"
                  placeholder="IN"
                  maxLength={2}
                  {...register('country')}
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

            <Field
              label="Relationship manager"
              htmlFor="company-rm"
              error={errors.relationship_manager?.message}
            >
              <Input id="company-rm" {...register('relationship_manager')} />
            </Field>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Identifiers
            </legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="PAN"
                htmlFor="company-pan"
                error={errors.pan?.message}
                hint="Unique — a PAN another company holds is refused."
              >
                <Input id="company-pan" placeholder="e.g. ABCDE1234F" {...register('pan')} />
              </Field>
              <Field label="GSTIN" htmlFor="company-gstin" error={errors.gstin?.message}>
                <Input id="company-gstin" placeholder="e.g. 27ABCDE1234F1Z5" {...register('gstin')} />
              </Field>
              <Field label="IEC" htmlFor="company-iec" error={errors.iec?.message}>
                <Input id="company-iec" {...register('iec')} />
              </Field>
              <Field label="CIN" htmlFor="company-cin" error={errors.cin?.message}>
                <Input id="company-cin" {...register('cin')} />
              </Field>
            </div>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Business
            </legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Industry" htmlFor="company-industry" error={errors.industry?.message}>
                <Input id="company-industry" {...register('industry')} />
              </Field>
              <Field label="Website" htmlFor="company-website" error={errors.website?.message}>
                <Input id="company-website" placeholder="https://…" {...register('website')} />
              </Field>
            </div>
          </fieldset>

          <div className="flex justify-end gap-2 border-t border-border pt-5">
            <Button variant="ghost" onClick={() => navigate(paths.companies)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Create company
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
